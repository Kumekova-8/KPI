from collections import defaultdict
from datetime import date
from decimal import Decimal
import json
import re

from .db import encode
from .rules import CADENCES, calculate, dec, entry_base, validate_rule
from .security import audit, now, require, role, uid
from .workflow import get_region, period_key


def list_methods(tx,user):
    role(user,'method','approver','analyst')
    return tx.all('SELECT id,track,parent,name,effective,reason,status,author,approver,created '
                  'FROM methods ORDER BY created DESC,id')


def get_version(tx,user,id):
    role(user,'method','approver','analyst')
    version = tx.one('SELECT * FROM methods WHERE id=?',(id,))
    require(version,404,'Версия методики не найдена.')
    return dict(version,content=json.loads(version['content']))


def text_field(value, label, limit=200):
    require(isinstance(value,str) and 1<=len(value.strip())<=limit,422,f'Заполните поле «{label}».')
    return value.strip()


def settings_fields(body):
    name = text_field(body.get('name'),'Название')
    reason = text_field(body.get('reason'),'Основание изменений',2000)
    effective = body.get('effective')
    period_key(effective,'month')
    return dict(name=name,reason=reason,effective=effective)


def new_version(tx,user,body):
    role(user,'method')
    parent = get_version(tx,user,body.get('parent'))
    id = uid()
    tx.insert('methods',dict(settings_fields(body),id=id,track=parent['track'],parent=parent['id'],
                            status='draft',author=user['id'],approver=None,created=now(),content=encode(parent['content'])))
    audit(tx,user['id'],id,'new_method',{'parent':parent['id']})
    return {'id':id}


def validate_entry(e):
    for key,label in [('code','Код'),('indicator','Код индикатора'),('indicator_name','Индикатор'),
                      ('metric','Код показателя'),('metric_name','Показатель'),('name','Субкомпонент'),
                      ('block','Блок'),('department','Ответственное подразделение'),('source','Источник')]:
        text_field(e.get(key),label,500)
    for key in ('code','indicator','metric'):
        require(re.fullmatch(r'[A-Za-z0-9.\-]{1,25}',e[key]),422,'Допустимы латинские буквы, цифры, точка и дефис в кодах.')
    require(e.get('cadence') in CADENCES,422,'Укажите периодичность.')
    dates = e.get('control_dates', ['09-15','12-31'] if e['cadence']=='control' else [])
    if e['cadence']=='control':
        require(isinstance(dates,list) and dates and
                all(isinstance(day,str) and re.fullmatch(r'\d{2}-\d{2}',day) for day in dates),
                422,'Укажите контрольные даты в формате ММ-ДД.')
        require(len({date.fromisoformat('2001-'+day).month for day in dates})==len(dates),
                422,'Допустима одна контрольная дата в пределах месяца.')
    require(type(e.get('inactive')) is bool and type(e.get('cumulative')) is bool,422,'Некорректный признак применимости.')
    for weight in ('metric_weight','weight'):
        require(0<dec(e[weight])<=100,422,'Вес должен быть больше 0 и не выше 100%.')
    applicability = e.get('applicability')
    require(isinstance(applicability,dict) and applicability.get('kind') in ('dgd','ctl') and
            isinstance(applicability.get('regions',[]),list),422,'Укажите применимость.')
    if not e.get('blockers'):
        require(isinstance(e.get('rule'),dict),422,'Укажите правило.')
        validate_rule(e['rule'],entry_base(e))


def validate_content(content,check_weights=True):
    entries = content['entries']
    require(1<=len(entries)<=500,422,'Допустимо до 500 субкомпонентов.')
    require(len({e['code'] for e in entries})==len(entries),422,'Коды субкомпонентов должны быть уникальными.')
    metrics = {}
    by_metric = defaultdict(Decimal)
    by_indicator = defaultdict(Decimal)
    indicators = {}
    for e in entries:
        if e['inactive']:
            continue
        validate_entry(e)
        subject = e['applicability']['kind']
        ind = (subject,e['indicator'])
        props = (e['indicator_name'],e['block'])
        require(indicators.setdefault(ind,props)==props,422,f'Разные названия или блок у индикатора {ind[1]}.')
        key = (subject,e['metric'])
        spec = (ind,dec(e['metric_weight']),e['metric_name'])
        if key not in metrics:
            metrics[key] = spec
            by_indicator[ind] += spec[1]
        require(metrics[key]==spec,422,f'Разные настройки показателя {key[1]}.')
        by_metric[key] += dec(e['weight'])
    require(metrics,422,'Добавьте активные субкомпоненты.')
    if check_weights:
        for label,group in [('показатель',by_metric),('индикатор',by_indicator)]:
            for (subject,code),value in group.items():
                require(value==100,422,f'Сумма весов для {label} {code} ({subject}) равна {value}%, требуется 100%.')


def save_entry(tx,user,id,body):
    role(user,'method')
    version = get_version(tx,user,id)
    require(version['status']=='draft',409,'Редактирование доступно в черновике.')
    new = body.get('entry')
    require(isinstance(new,dict),422,'Нет данных субкомпонента.')
    content = version['content']
    entries = content['entries']
    existing = next((e for e in entries if e['code']==new.get('code')),None)
    require(existing==body.get('original'),409,'Строка изменилась. Обновите версию.')
    if existing:
        new = dict(existing,**{k:v for k,v in new.items() if k in {
            'indicator','indicator_name','metric','metric_name','name','block','department','source','instruction',
            'metric_weight','weight','cadence','control_dates','cumulative','applicability','inactive','rule'}})
        if body.get('resolution'):
            reason = text_field(body['resolution'],'Решение по расхождению',2000)
            new.update(blockers=[],resolution=reason)
    else:
        new = dict(new,blockers=[])
    validate_entry(new)
    for region in new['applicability'].get('regions',[]):
        require(get_region(tx,region)['kind']==new['applicability']['kind'],422,'Тип организации не совпадает.')
    # A metric's weight and an indicator's name are shared by every active child.
    for index,e in enumerate(entries):
        if e['code']==new['code']:
            entries[index] = new
        elif e['applicability']['kind']==new['applicability']['kind']:
            if e['indicator']==new['indicator']:
                e.update(indicator_name=new['indicator_name'],block=new['block'])
            if e['metric']==new['metric']:
                e.update(metric_weight=new['metric_weight'],metric_name=new['metric_name'])
    if not existing:
        entries.append(new)
    for entry in entries:
        if not entry['inactive']:
            validate_entry(entry)
    tx.update('methods',id,{'content':encode(content)})
    audit(tx,user['id'],id,'save_rule',{'code':new['code'],'before':body.get('original'),'after':new})
    return new


def method_action(tx,user,id,action):
    version = get_version(tx,user,id)
    if action=='submit':
        role(user,'method')
        require(version['status']=='draft',409,'Версия уже направлена.')
        validate_content(version['content'])
        updates = {'status':'review'}
    elif action in ('approve','send_back'):
        role(user,'approver')
        require(version['status']=='review' and version['author']!=user['id'],409,'Требуется независимое согласование.')
        updates = {'status':'approved' if action=='approve' else 'draft','approver':user['id'] if action=='approve' else None}
    elif action=='publish':
        role(user,'method')
        require(version['status']=='approved' and version['approver']!=user['id'],409,
                'Опубликовать можно версию после независимого утверждения.')
        latest = tx.one("SELECT effective FROM methods WHERE track=? AND status='published' ORDER BY effective DESC LIMIT 1",
                        (version['track'],))
        require(not latest or version['effective']>latest['effective'],422,'Дата должна быть позже предыдущей публикации.')
        updates = {'status':'published'}
    else:
        require(False,404,'Действие не найдено.')
    tx.update('methods',id,updates)
    audit(tx,user['id'],id,action,{'effective':version['effective'],'reason':version['reason']})
    return get_version(tx,user,id)


def compare_versions(tx,user,id):
    version = get_version(tx,user,id)
    if not version['parent']:
        return []
    before = get_version(tx,user,version['parent'])
    old = {e['code']:e for e in before['content']['entries']}
    new = {e['code']:e for e in version['content']['entries']}
    return [{'code':code,'before':old.get(code),'after':new.get(code)} for code in sorted(old.keys()|new.keys())
            if old.get(code)!=new.get(code)]


def preview_rule(tx,user,id,body):
    version = get_version(tx,user,id)
    period,kind = body.get('period'),body.get('kind','month')
    period_key(period,kind)
    entry = body.get('entry') if version['status']=='draft' and user['role']=='method' else None
    if not entry:
        entry = next((e for e in version['content']['entries'] if e['code']==body.get('code')),None)
    require(entry,404,'Субкомпонент не найден.')
    validate_entry(entry)
    return calculate(entry,body.get('values',{}),period,kind,preview=True)


def assign_deputy(tx,user,body):
    role(user,'method')
    region = get_region(tx,body.get('region'))
    name = text_field(body.get('name'),'Имя')
    title = text_field(body.get('title'),'Должность')
    starts = date.fromisoformat(body.get('starts','')).isoformat()
    ends = date.fromisoformat(body['ends']).isoformat() if body.get('ends') else None
    require(not ends or ends>=starts,422,'Проверьте даты работы.')
    track = body.get('track','demo')
    version = tx.one("SELECT content FROM methods WHERE track=? AND status='published' ORDER BY effective DESC LIMIT 1",(track,))
    require(version,422,'Укажите контур методики.')
    codes = {e['code'] for e in json.loads(version['content'])['entries'] if e['applicability']['kind']==region['kind']}
    assignments = body.get('assignments')
    require(isinstance(assignments,list) and assignments and set(assignments)<=codes,422,'Укажите допустимые субкомпоненты.')
    previous = tx.one('SELECT * FROM deputies WHERE id=?',(body.get('previous'),))
    if body.get('previous'):
        require(previous and previous['region']==region['id'] and previous['starts']<starts,422,'Некорректная дата изменения.')
        from datetime import timedelta
        boundary = (date.fromisoformat(starts)-timedelta(days=1)).isoformat()
        require(not previous['ends'] or previous['ends']==boundary,409,'Период назначения уже закрыт.')
        tx.update('deputies',previous['id'],{'ends':boundary})
        previous_assignments = json.loads(previous['assignments'])
    else:
        previous_assignments = {}
    id = uid()
    tx.insert('deputies',dict(id=id,region=region['id'],name=name,title=title,starts=starts,
                             ends=ends,person=(previous['person'] or previous['id']) if previous else id,
                             assignments=encode(dict(previous_assignments,**{track:assignments}))))
    audit(tx,user['id'],id,'assign_deputy',{'previous':body.get('previous'),'track':track,'assignments':assignments})
    return {'id':id}



def aggregate_decision(tx,user,id,body):
    role(user,'method')
    version = get_version(tx,user,id)
    require(version['status']=='draft',409,'Редактирование доступно в черновике.')
    subject = body.get('subject')
    require(subject in ('dgd','ctl','deputy'),422,'Укажите объект расчёта.')
    content = version['content']
    unresolved = content.setdefault('aggregate_blockers',{})
    require(unresolved.get(subject),409,'Для этого объекта нет открытых вопросов агрегации.')
    reason = text_field(body.get('reason'),'Решение и реквизиты утверждения',2000)
    decision = {'issues':unresolved[subject],'reason':reason}
    if subject=='ctl':
        denominator = dec(body.get('denominator'))
        require(denominator>0,422,'Утверждённый знаменатель должен быть положительным.')
        content['ctl_denominator']=float(denominator)
        decision['denominator']=float(denominator)
    content.setdefault('aggregate_decisions',{})[subject]=decision
    unresolved[subject]=[]
    tx.update('methods',id,{'content':encode(content)})
    audit(tx,user['id'],id,'aggregate_decision',dict(decision,subject=subject))
    return decision
