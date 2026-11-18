from calendar import monthrange
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from .db import encode
from .integrations import demonstration_signature
from .rules import aggregate, applicable, calculate, input_values, entry_base, rating_grade, PERIODS
from .security import audit, digest, now, require, role, uid


STATES = {'draft':'Черновик','submitted':'На проверке','returned':'На доработке',
          'checked':'Готов к подписанию','signed':'Подписан'}


def track_key(track):
    require(track in ('source','demo'),422,'Выберите контур методики.')
    return track


def period_key(period,kind):
    require(isinstance(period,str) and re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',period),422,'Период указывается в формате ГГГГ-ММ.')
    require(kind in PERIODS,422,'Некорректная периодичность.')
    month = int(period[-2:])
    require(kind=='month' or kind=='quarter' and month%3==0 or kind=='year' and month==12,
            422,'Выберите завершающий месяц квартала или года.')
    return period


def get_method(tx,track,period,kind,pin=False):
    track_key(track)
    period_key(period,kind)
    selected = tx.one('SELECT method FROM periods WHERE track=? AND period=? AND kind=?',(track,period,kind))
    if selected:
        method = tx.one('SELECT * FROM methods WHERE id=?',(selected['method'],))
    else:
        method = tx.one("SELECT * FROM methods WHERE track=? AND status='published' AND effective<=? "
                        'ORDER BY effective DESC,created DESC LIMIT 1',(track,period))
    require(method,404,'Для этого периода нет опубликованной версии.')
    if pin and not selected:
        tx.insert('periods',{'track':track,'period':period,'kind':kind,'method':method['id']})
    return dict(method,content=json.loads(method['content']))


def get_region(tx,id):
    region = tx.one('SELECT * FROM regions WHERE id=?',(id,))
    require(region,404,'Организация не найдена.')
    return region


def current_packages(tx,track,period,kind,region=None):
    query = ('SELECT p.* FROM packages p WHERE p.track=? AND p.period=? AND p.kind=? AND NOT EXISTS '
             '(SELECT 1 FROM packages n WHERE n.track=p.track AND n.period=p.period AND n.kind=p.kind '
             'AND n.region=p.region AND n.department=p.department AND n.revision>p.revision)')
    return tx.all(query + (' AND p.region=?' if region else ''),
                  (track,period,kind,region) if region else (track,period,kind))


def entries_for(method,region,period,kind,department=None):
    return [e for e in method['content']['entries'] if applicable(e,region,period,kind)
            and (department is None or e['department']==department)]


def get_package(tx,user,id):
    p = tx.one('SELECT * FROM packages WHERE id=?',(id,))
    require(p,404,'Пакет не найден.')
    if user['role']=='reporter':
        require(p['region']==user['scope'],403,'Пакет другой организации.')
    elif user['role'] in ('reviewer','signer'):
        require(p['department']==user['scope'],403,'Пакет другого подразделения.')
        require(p['status']!='draft',404,'Пакет ещё не направлен на проверку.')
    else:
        role(user,'analyst')
    return p


def base_package(track,period,kind,region,department,method,revision=1,parent=None,facts=None,notes=None):
    return dict(id=uid(),track=track,period=period,kind=kind,region=region,department=department,
                method=method,revision=revision,parent=parent,status='draft',facts=encode(facts or {}),
                notes=encode(notes or {}),signature=None,generation=0,updated=now())


def open_package(tx,user,track,period,kind,department):
    role(user,'reporter')
    region = get_region(tx,user['scope'])
    method = get_method(tx,track,period,kind,pin=True)
    require(entries_for(method,region,period,kind,department),404,'В периоде нет субкомпонентов этого подразделения.')
    existing = next((p for p in current_packages(tx,track,period,kind,region['id'])
                     if p['department']==department),None)
    if existing:
        return existing['id']
    package = base_package(track,period,kind,region['id'],department,method['id'])
    tx.insert('packages',package)
    audit(tx,user['id'],package['id'],'create')
    return package['id']


def package_entries(tx,p):
    method = get_method(tx,p['track'],p['period'],p['kind'])
    return entries_for(method,get_region(tx,p['region']),p['period'],p['kind'],p['department'])


def evidence(tx,id):
    return tx.all('SELECT id,component,name,media_type,sha256,size FROM attachments WHERE package=? ORDER BY id',(id,))


def history(tx,id):
    events = tx.all('SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor WHERE object=? ORDER BY happened,id',(id,))
    return [dict(row,detail=json.loads(row['detail'])) for row in events]


def signing_payload(p, attachments):
    keys = ('id','track','period','kind','region','department','method','revision','parent')
    return dict({k:p[k] for k in keys},facts=json.loads(p['facts']),attachments=attachments)


def package_detail(tx,user,id):
    p = get_package(tx,user,id)
    region = get_region(tx,p['region'])
    attachments = evidence(tx,id)
    signature = json.loads(p['signature']) if p['signature'] else None
    if signature:
        signature['valid_digest'] = signature['sha256']==digest(encode(signing_payload(p,attachments)))
    facts = json.loads(p['facts'])
    signed = p['status']=='signed' and signature and signature['valid_digest']
    components = [dict(e,calculation=calculate(e,facts.get(e['code'],{}),p['period'],p['kind'],signed,True))
                  for e in package_entries(tx,p)]
    revisions = tx.all('SELECT id,revision,status,updated FROM packages WHERE track=? AND period=? AND kind=? '
                       'AND region=? AND department=? ORDER BY revision DESC',
                       tuple(p[k] for k in ('track','period','kind','region','department')))
    events = history(tx,id)
    require(not (user['role'] in ('reviewer','signer') and p['status']=='draft'),404,'Пакет ещё не отправлен.')
    return dict(p,facts=facts,notes=json.loads(p['notes']),region_name=region['name'],signature=signature,
                entries=components,attachments=attachments,history=events,
                revisions=[r for r in revisions if user['role'] not in ('reviewer','signer') or r['status']!='draft'])


def list_packages(tx,user,track,period,kind):
    role(user,'reporter','reviewer','signer','analyst')
    method = get_method(tx,track,period,kind)
    regions = ([get_region(tx,user['scope'])] if user['role']=='reporter'
               else tx.all('SELECT * FROM regions ORDER BY name'))
    current = {(p['region'],p['department']):p for p in current_packages(tx,track,period,kind)}
    result = []
    for region in regions:
        assigned = entries_for(method,region,period,kind,user['scope'] if user['role'] in ('reviewer','signer') else None)
        for department in sorted({e['department'] for e in assigned}):
            p = current.get((region['id'],department))
            if user['role'] in ('reviewer','signer') and (not p or p['status']=='draft'):
                continue
            result.append({'id':p['id'] if p else None,'region':region['id'],'region_name':region['name'],
                           'department':department,'status':p['status'] if p else 'missing',
                           'revision':p['revision'] if p else None,'updated':p['updated'] if p else None,
                           'count':sum(e['department']==department for e in assigned)})
    calendar = deadlines(tx,period,kind)
    today = calendar_today().isoformat()
    notices = []
    if user['role']=='reporter':
        returns = sum(p['status']=='returned' for p in result)
        outstanding = sum(p['status'] in ('draft','missing') for p in result)
        if returns:
            notices.append({'count':returns,'label':'Пакеты возвращены на доработку'})
        if outstanding and today>calendar['submission']:
            notices.append({'count':outstanding,'label':'Истёк срок представления пакетов'})
    if user['role'] in ('reviewer','signer'):
        target = 'checked' if user['role']=='signer' else 'submitted'
        pending = sum(p['status']==target for p in result)
        if pending:
            label = ('Истёк срок проверки или подписания' if today>calendar['review'] else
                     'Ожидают подписания' if target=='checked' else 'Ожидают проверки')
            notices.append({'count':pending,'label':label})
    return {'method':method['name'],'packages':result,'notifications':notices}


def current_guard(tx,p,generation):
    latest = next((x for x in current_packages(tx,p['track'],p['period'],p['kind'],p['region'])
                   if x['department']==p['department']),None)
    require(latest and latest['id']==p['id'] and p['generation']==generation,409,
            'Версия пакета изменилась. Обновите страницу.')


def update_package(tx,user,id,action,body):
    p = get_package(tx,user,id)
    current_guard(tx,p,body.get('generation'))
    state = p['status']
    facts = json.loads(p['facts'])
    notes = json.loads(p['notes'])
    entries = {e['code']:e for e in package_entries(tx,p)}
    detail = {}
    updates = {}
    if action in ('save','submit','revise'):
        role(user,'reporter')
    elif action in ('return','check'):
        role(user,'reviewer')
    elif action=='sign':
        role(user,'signer')
    else:
        require(False,404,'Действие не найдено.')
    if action=='save':
        require(state in ('draft','returned'),409,'Редактирование на этой стадии недоступно.')
        incoming = body.get('facts')
        require(isinstance(incoming,dict) and set(incoming)<=entries.keys(),422,'Неизвестный субкомпонент.')
        if state=='returned':
            require(set(incoming)<=notes.keys(),422,'Доступны только строки, возвращённые на доработку.')
        changes = {}
        for code,fields in incoming.items():
            rule = entries[code].get('rule')
            require(rule,422,f'Поля {code} требуют уточнения методики.')
            after = input_values(rule,fields)
            before = facts.get(code,{})
            if after!=before:
                changes[code] = {'before':before,'after':after}
            facts[code] = after
        updates['facts'] = encode(facts)
        detail['changes'] = changes
    elif action=='submit':
        require(state in ('draft','returned'),409,'Пакет нельзя отправить на этой стадии.')
        for code,e in entries.items():
            if e.get('rule') is None:
                continue
            result = calculate(e,facts.get(code,{}),p['period'],p['kind'],preview=True)
            fields = e['rule']['fields']
            require(len(facts.get(code,{}))==len(fields),422,f'Заполните исходные данные для {code}.')
            require(result['status']!='impossible',422,f'Проверьте исходные данные для {code}: расчёт невозможен.')
        updates.update(status='submitted')
    elif action=='return':
        require(state in ('submitted','checked'),409,'Пакет должен быть на проверке.')
        comments = body.get('comments')
        require(isinstance(comments,dict) and comments and set(comments)<=entries.keys() and
                all(isinstance(v,str) and 1<=len(v.strip())<=1500 for v in comments.values()),
                422,'Укажите причину по каждой возвращаемой строке.')
        updates.update(status='returned',notes=encode({k:v.strip() for k,v in comments.items()}))
        detail = comments
    elif action=='check':
        require(state=='submitted',409,'Пакет должен быть на проверке.')
        updates.update(status='checked')
    elif action=='sign':
        require(state=='checked',409,'Ожидается проверка сотрудником подразделения.')
        check_event = tx.one("SELECT actor FROM audit WHERE object=? AND action='check' ORDER BY happened DESC LIMIT 1",(id,))
        require(check_event and check_event['actor']!=user['id'],403,'Проверяющий и подписант должны различаться.')
        sig = demonstration_signature(signing_payload(p,evidence(tx,id)),user['id'])
        detail = sig
        updates.update(status='signed',signature=encode(sig))
    elif action=='revise':
        require(state=='signed',409,'Новая редакция создаётся для подписанного пакета.')
        reason = body.get('reason','')
        require(isinstance(reason,str) and 3<=len(reason.strip())<=1500,422,'Укажите основание корректировки.')
        new = base_package(p['track'],p['period'],p['kind'],p['region'],p['department'],p['method'],
                           p['revision']+1,id,facts)
        tx.insert('packages',new)
        for file in tx.all('SELECT * FROM attachments WHERE package=?',(id,)):
            tx.insert('attachments',dict(file,id=uid(),package=new['id']))
        audit(tx,user['id'],new['id'],'revise',{'parent':id,'reason':reason.strip()})
        return {'id':new['id']}
    tx.update('packages',id,dict(updates,updated=now(),generation=p['generation']+1))
    audit(tx,user['id'],id,action,detail)
    if action=='sign':
        persist_result(tx,p)
    return {'id':id}



def add_attachment(tx,user,id,generation,code,filename,media_type,content):
    role(user,'reporter')
    p = get_package(tx,user,id)
    current_guard(tx,p,generation)
    require(p['status'] in ('draft','returned'),409,'Загрузка доступна в черновике или при доработке.')
    require(code in {e['code'] for e in package_entries(tx,p)},422,'Неизвестный субкомпонент.')
    require(p['status']!='returned' or code in json.loads(p['notes']),422,'Строка не возвращена на доработку.')
    require(len(evidence(tx,id))<20 and 0<len(content)<=5*1024*1024,422,'Допустимо до 20 файлов по 5 МБ.')
    safe = re.sub(r'[^\w .()-]','_',str(filename))[:100].strip(' .')
    magic = {'application/pdf':b'%PDF-', 'image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff'}
    require(safe and media_type in magic and content.startswith(magic[media_type]),422,'Поддерживаются PDF, PNG и JPEG.')
    file = {'id':uid(),'package':id,'component':code,'name':safe,'media_type':media_type,'sha256':digest(content),
            'size':len(content)}
    tx.insert('attachments',dict(file,content=content))
    tx.update('packages',id,{'generation':p['generation']+1,'updated':now()})
    audit(tx,user['id'],id,'attach',file)
    return file


def allow_delete_attachment(tx,user,id,attachment,generation):
    role(user,'reporter')
    p = get_package(tx,user,id)
    current_guard(tx,p,generation)
    file = tx.one('SELECT component,name FROM attachments WHERE id=? AND package=?',(attachment,id))
    require(file,404,'Файл не найден.')
    require(p['status']=='draft' or p['status']=='returned' and file['component'] in json.loads(p['notes']),409,
            'Файл доступен только для чтения.')
    tx.query('DELETE FROM attachments WHERE id=?',(attachment,))
    tx.update('packages',id,{'generation':p['generation']+1,'updated':now()})
    audit(tx,user['id'],id,'detach',file)


def signed_facts(tx,p):
    if p['status']!='signed' or not p['signature']:
        return None
    sig = json.loads(p['signature'])
    if sig['sha256'] != digest(encode(signing_payload(p,evidence(tx,p['id'])))):
        return None
    return json.loads(p['facts'])


def result_data(tx,method,region,period,kind,packages,preview=False,signed_only=False):
    content = method['content']
    by_department = {p['department']:p for p in packages}
    available = {}
    for department,p in by_department.items():
        confirmed = signed_facts(tx,p)
        if confirmed is not None:
            available[department] = (confirmed,True)
        elif not signed_only:
            available[department] = (json.loads(p['facts']),False)
    rows = []
    for e in content['entries']:
        if e['inactive'] or e['applicability'].get('kind','dgd') != region['kind']:
            continue
        if applicable(e,region,period,kind):
            facts,signed = available.get(e['department'],({},False))
            values = facts.get(e['code'],{})
            calc = calculate(e,values,period,kind,signed,preview)
        else:
            values = {}
            calc = dict(base=float(entry_base(e)),actual=None,points=None,status='na')
        keys=('code','name','department','metric','metric_name','metric_weight','indicator','indicator_name','block','weight')
        form_target = e.get('form_target') if method['track']=='source' else None
        if method['track']=='demo' and e.get('rule',{}).get('bands'):
            form_target = e['rule']['bands'][0]['target']
        rows.append(dict({k:e[k] for k in keys},**calc,values=values,target=form_target))
    blocked = content.get('aggregate_blockers',{})
    total = aggregate(rows,region['kind'],content.get('ctl_denominator'),blocks=bool(blocked.get(region['kind'])))
    deputies = []
    month_end = f'{period}-{monthrange(int(period[:4]),int(period[-2:]))[1]}'
    for deputy in tx.all('SELECT * FROM deputies WHERE region=? AND starts<=? AND (ends IS NULL OR ends>=?) ORDER BY name',
                         (region['id'],month_end,month_end)):
        assignments = json.loads(deputy['assignments']).get(method['track'],[])
        selected = [r for r in rows if r['code'] in assignments or r['metric'] in assignments]
        value = aggregate(selected,'deputy',blocks=bool(blocked.get('deputy')))
        deputies.append(dict({k:deputy[k] for k in ('id','name','title','starts','ends')},person=deputy['person'] or deputy['id'],assignments=assignments,
                             total=value['total'],status=value['status'],
                             blocks=sorted({r['block'] for r in selected if r['status']!='na'})))
    return dict(total,rows=rows,deputies=deputies,method=method['id'],method_name=method['name'],
                blockers=blocked.get(region['kind'],[]),region=region['id'],region_name=region['name'],
                kind=kind,period=period,track=method['track'])


def latest_result(tx,track,period,kind,region):
    saved = tx.one('SELECT * FROM results WHERE track=? AND period=? AND kind=? AND region=? ORDER BY revision DESC LIMIT 1',
                   (track,period,kind,region))
    if saved:
        return dict(json.loads(saved['content']),revision=saved['revision'],saved_at=saved['created'])
    return None


def persist_result(tx,p):
    method = get_method(tx,p['track'],p['period'],p['kind'])
    packages = current_packages(tx,p['track'],p['period'],p['kind'],p['region'])
    region = get_region(tx,p['region'])
    result = result_data(tx,method,region,p['period'],p['kind'],packages,signed_only=True)
    if result['status']!='ok':
        return
    versions = {x['department']:x['id'] for x in packages if x['status']=='signed'}
    previous = latest_result(tx,p['track'],p['period'],p['kind'],p['region'])
    tx.insert('results',{'id':uid(),'track':p['track'],'period':p['period'],'kind':p['kind'],'region':p['region'],
                         'method':method['id'],'revision':previous['revision']+1 if previous else 1,'created':now(),
                         'content':encode(dict(result,packages=versions))})


def result_card(tx,user,track,period,kind,region_id,revision=None):
    role(user,'analyst','reporter')
    require(user['role']=='analyst' or user['scope']==region_id,403,'Чужая организация.')
    method = get_method(tx,track,period,kind)
    region = get_region(tx,region_id)
    history_rows = tx.all('SELECT revision,created FROM results WHERE track=? AND period=? AND kind=? AND region=? ORDER BY revision DESC',
                          (track,period,kind,region_id))
    current = current_packages(tx,track,period,kind,region_id)
    preliminary = result_data(tx,method,region,period,kind,current,preview=user['role']=='reporter')
    saved = latest_result(tx,track,period,kind,region_id)
    if revision is not None:
        record = tx.one('SELECT content,revision,created FROM results WHERE track=? AND period=? AND kind=? AND region=? AND revision=?',
                        (track,period,kind,region_id,revision))
        require(record,404,'Редакция результата не найдена.')
        saved = dict(json.loads(record['content']),revision=record['revision'],saved_at=record['created'])
    return {'official':saved,'working':preliminary,'history':history_rows}


def previous_period(period,kind):
    y,m = map(int,period.split('-'))
    idx = y*12+m-1-{'month':1,'quarter':3,'year':12}[kind]
    return f'{idx//12:04}-{idx%12+1:02}'


def calendar_today():
    try:
        return datetime.now(ZoneInfo('Asia/Qyzylorda')).date()
    except ZoneInfoNotFoundError:
        return (datetime.utcnow()+timedelta(hours=5)).date()


def deadlines(tx,period,kind):
    year,month = map(int,period.split('-'))
    following_year,following_month = year+int(month==12),month%12+1
    override = tx.one('SELECT value FROM settings WHERE id=?',(f'calendar:{kind}:{period}',))
    dates = {task:date(following_year,following_month,day).isoformat()
             for task,day in [('submission',5),('review',10),('export',15)]}
    return json.loads(override['value']) if override else dict(dates,reason='Пункты 9–11 приложения 1')


def dashboard(tx,user,track,period,kind):
    role(user,'analyst')
    method = get_method(tx,track,period,kind)
    regions = tx.all('SELECT * FROM regions ORDER BY name')
    packages = current_packages(tx,track,period,kind)
    old = previous_period(period,kind)
    calendar = deadlines(tx,period,kind)
    records, deputies, problems = [],[],[]
    counts = {k:0 for k in ('draft','submitted','returned','checked','signed','missing')}
    block_points = {}
    today = calendar_today().isoformat()
    late = 0
    package_index = {(p['region'],p['department']):p for p in packages}
    for region in regions:
        assigned = entries_for(method,region,period,kind)
        if not assigned:
            continue
        active_packages = []
        for department in {e['department'] for e in assigned}:
            p = package_index.get((region['id'],department))
            state = p['status'] if p else 'missing'
            counts[state] += 1
            if p:
                active_packages.append(p)
            if today>calendar['review'] and state in ('submitted','checked'):
                late += 1
        saved = latest_result(tx,track,period,kind,region['id'])
        preceding = latest_result(tx,track,old,kind,region['id'])
        decision = saved or result_data(tx,method,region,period,kind,active_packages)
        total = decision['total']
        delta = round(total-preceding['total'],4) if preceding and total is not None else None
        records.append({'id':region['id'],'name':region['name'],'subject':region['kind'],'total':total,
                        'status':decision['status'],'grade':rating_grade(total,track=='demo'),'delta':delta,
                        'received':sum(p['status']=='signed' for p in active_packages),
                        'expected':len({e['department'] for e in assigned})})
        old_deputies = {d.get('person',d['id']):d['total'] for d in preceding['deputies']} if preceding else {}
        for d in decision['deputies']:
            before = old_deputies.get(d.get('person',d['id']))
            deputies.append(dict(d,region=region['name'],region_id=region['id'],grade=rating_grade(d['total'],track=='demo'),
                                 delta=round(d['total']-before,4) if d['total'] is not None and before is not None else None))
        if saved and region['kind']=='dgd':
            for block,scores in saved['groups']['block'].items():
                if scores['base'] and scores['points'] is not None:
                    block_points.setdefault(block,[]).append(float(scores['points'])/float(scores['base'])*100)
        for r in decision['rows']:
            if r['status']=='blocked' or r['status']=='ok' and r['points']<r['base']:
                problems.append(dict(r,region=region['name'],region_id=region['id']))
    records.sort(key=lambda r:(r['total'] is None,-(r['total'] or 0),r['name']))
    deputies.sort(key=lambda r:(r['total'] is None,-(r['total'] or 0),r['name']))
    series = []
    point = period
    for _ in range(6 if kind=='month' else 4):
        scores = []
        for region in regions:
            if region['kind']=='dgd':
                saved = latest_result(tx,track,point,kind,region['id'])
                if saved:
                    scores.append(saved['total'])
        series.append({'period':point,'value':sum(scores)/len(scores) if scores else None})
        point = previous_period(point,kind)
    values = [r['total'] for r in records if r['subject']=='dgd' and r['total'] is not None]
    return {'method':method['name'],'records':records,'deputies':deputies,'counts':counts,'late':late,
            'calendar':calendar,'date':today,'average':sum(values)/len(values) if values else None,
            'series':series[::-1],'blocks':{b:sum(v)/len(v) for b,v in block_points.items()},
            'problems':problems,'dgd_count':sum(r['kind']=='dgd' for r in regions)}


def deputy_history(tx,user,id,track,period,kind):
    role(user,'analyst')
    track_key(track)
    period_key(period,kind)
    subject = tx.one('SELECT * FROM deputies WHERE id=?',(id,))
    require(subject,404,'Запись заместителя не найдена.')
    rows = tx.all('SELECT period,revision,content FROM results '
                  'WHERE track=? AND kind=? AND region=? AND period<=? ORDER BY period DESC,revision DESC',
                  (track,kind,subject['region'],period))
    series = []
    person = subject['person'] or subject['id']
    for record in rows:
        saved = json.loads(record['content'])
        match = next((d for d in saved['deputies'] if d.get('person',d['id'])==person),None)
        if match:
            series.append(dict(match,period=record['period'],revision=record['revision'],method=saved['method_name']))
    return {'name':subject['name'],'title':subject['title'],'results':series}
