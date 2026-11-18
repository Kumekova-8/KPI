from datetime import date
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import logging
import mimetypes
import os
import re
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit

from . import exchange, methodology as methods, workflow as flow
from .db import DB, ROOT, encode
from .integrations import SyntheticSource
from .security import Problem, actor, audit, digest, login, password_hash, public_user, require, role
from .seed import seed

LOG = logging.getLogger('kpi')
MAX_BODY = 5*1024*1024
ATTEMPTS = {}
LOCK = threading.Lock()
FRONTEND = ROOT/'web'


def bytes_response(data,media,name):
    return data,media,{'Content-Disposition':f"attachment; filename*=UTF-8''{quote(name)}"}


def save_calendar(tx,user,period,kind,body):
    role(user,'method')
    flow.period_key(period,kind)
    keys = ('submission','review','export')
    values = {k:date.fromisoformat(body.get(k,'')).isoformat() for k in keys}
    require(list(values.values())==sorted(values.values()) and all(v>period+'-31' for v in values.values()),
            422,'Сроки должны идти по порядку и наступать после отчётного периода.')
    values['reason'] = methods.text_field(body.get('reason'),'Основание переноса',2000)
    identifier = f'calendar:{kind}:{period}'
    if tx.one('SELECT id FROM settings WHERE id=?',(identifier,)):
        tx.update('settings',identifier,{'value':encode(values)})
    else:
        tx.insert('settings',{'id':identifier,'value':encode(values)})
    audit(tx,user['id'],identifier,'calendar',values)
    return values


def technical(tx,user,path,http_method,body):
    role(user,'technical')
    if path=='/api/technical' and http_method=='GET':
        integrations = [{'code':key,'name':label,'status':'Требуется подключение'} for key,label in
                        [('sdf','SDF'),('isna','ИСНА'),('keden','Кеден'),('esf','ИС ЭСФ'),('nca','NCALayer / НУЦ РК')]]
        return {'users':[public_user(u) for u in tx.all('SELECT * FROM users ORDER BY role,id')],
                'events':tx.all('SELECT actor,happened,action,object FROM audit ORDER BY happened DESC LIMIT 35'),
                'database':'PostgreSQL' if tx.postgres else 'SQLite', 'integrations':integrations}
    if path=='/api/technical/users' and http_method=='POST':
        id = methods.text_field(body.get('id'),'Логин',60)
        require(re.fullmatch('[a-z][a-z0-9.-]{2,59}',id),422,'Некорректный логин.')
        account = tx.one('SELECT * FROM users WHERE id=?',(id,))
        if account:
            require(user['id']!=id and type(body.get('active')) is bool,422,'Укажите состояние другой учётной записи.')
            active = int(body['active'])
            tx.update('users',id,{'active':active})
            if not active:
                tx.query('DELETE FROM sessions WHERE actor=?',(id,))
        else:
            name = methods.text_field(body.get('name'),'Имя')
            access = body.get('role')
            scope = body.get('scope','')
            require(access in ('reporter','reviewer','signer','analyst','technical'),422,
                    'Полномочия конструктора и утверждения назначаются при настройке развёртывания.')
            password = body.get('password','')
            require(isinstance(password,str) and 12<=len(password)<=128,422,'Введите пароль из 12–128 символов.')
            if access=='reporter':
                flow.get_region(tx,scope)
            if access in ('reviewer','signer'):
                require(isinstance(scope,str) and 1<=len(scope)<=60,422,'Введите ответственное подразделение.')
            tx.insert('users',dict(id=id,name=name,role=access,scope=scope,password=password_hash(password),active=1))
        audit(tx,user['id'],id,'manage_user')
        return public_user(tx.one('SELECT * FROM users WHERE id=?',(id,)))
    raise Problem(404,'Раздел не найден.')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_PUT(self):
        self.handle_request('PUT')

    def do_DELETE(self):
        self.handle_request('DELETE')

    def log_message(self, format, *args):
        LOG.info('%s %s',self.client_address[0],format % args)

    def respond(self,status,data,media='application/json; charset=utf-8',headers=None):
        if not isinstance(data,bytes):
            data = encode(data).encode()
        self.send_response(status)
        self.send_header('Content-Type',media)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; form-action 'self'; base-uri 'none'")
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.end_headers()
        self.wfile.write(data)

    def body_bytes(self):
        size = int(self.headers.get('Content-Length') or '0')
        if not 0<=size<=MAX_BODY:
            self.close_connection=True
            raise Problem(413,'Превышен размер запроса.')
        return self.rfile.read(size)

    def body_json(self):
        data = json.loads(self.body_bytes() or b'{}')
        require(isinstance(data,dict),422,'Ожидается JSON-объект.')
        return data

    def cookie(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get('Cookie',''))
        return cookies['kpi_session'].value if 'kpi_session' in cookies else None

    def handle_request(self,http_method):
        try:
            request = urlsplit(self.path)
            path = request.path.rstrip('/') or '/'
            params = {k:v[-1] for k,v in parse_qs(request.query).items()}
            if not path.startswith('/api/'):
                return self.static(path,http_method)
            if http_method!='GET':
                origin = self.headers.get('Origin')
                allowed = os.environ.get('KPI_ORIGIN')
                same_origin = origin==allowed if allowed else origin and urlsplit(origin).netloc==self.headers.get('Host')
                require(not origin or same_origin,403,'Запрос должен исходить из интерфейса платформы.')
            if path=='/api/health' and http_method=='GET':
                return self.respond(200,{'status':'ok','mode':'demo'})
            raw_upload = (path.endswith(('/attachment','/import')) and http_method=='POST')
            body = (self.body_bytes() if raw_upload else self.body_json()) if http_method in ('POST','PUT') else {}
            if path=='/api/login' and http_method=='POST':
                return self.sign_in(body)
            with self.server.db.transaction(write=http_method!='GET') as tx:
                cookie = self.cookie()
                user = actor(tx,cookie)
                if path=='/api/logout' and http_method=='POST':
                    tx.query('DELETE FROM sessions WHERE token=?',(digest(cookie),))
                    result = ({'ok':True},'application/json; charset=utf-8',
                              {'Set-Cookie':'kpi_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
                else:
                    result = self.dispatch(tx,user,http_method,path,params,body)
            if isinstance(result,tuple):
                return self.respond(200,*result)
            return self.respond(200,result)
        except Problem as error:
            self.respond(error.status,{'error':str(error)})
        except ValueError as error:
            self.respond(422,{'error':str(error)})
        except (BrokenPipeError,ConnectionResetError):
            LOG.debug('Client disconnected')
        except Exception:
            LOG.exception('Unexpected request error')
            self.respond(500,{'error':'Внутренняя ошибка сервера.'})

    def sign_in(self,body):
        ip = self.client_address[0]
        stamp = time.monotonic()
        with LOCK:
            for key,events in list(ATTEMPTS.items()):
                recent = [event for event in events if stamp-event<60]
                if recent:
                    ATTEMPTS[key] = recent
                else:
                    ATTEMPTS.pop(key,None)
            events = ATTEMPTS.setdefault(ip,[])
            require(len(events)<20,429,'Слишком много попыток. Повторите через минуту.')
            events.append(stamp)
        with self.server.db.transaction(write=True) as tx:
            cookie,user = login(tx,body.get('username'),body.get('password'))
        flags = '; Secure' if os.getenv('KPI_SECURE_COOKIE')=='1' else ''
        self.respond(200,user,headers={'Set-Cookie':f'kpi_session={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800{flags}'})

    def static(self,path,http_method):
        require(http_method=='GET',405,'Действие недоступно.')
        name = 'index.html' if path=='/' else path.lstrip('/')
        require(re.fullmatch(r'[A-Za-z0-9._-]+\.(html|css|js|ico)',name),404,'Страница не найдена.')
        file = FRONTEND/name
        require(file.is_file(),404,'Страница не найдена.')
        media = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        self.respond(200,file.read_bytes(),media+'; charset=utf-8')

    def dispatch(self,tx,user,verb,path,q,body):
        track,period,kind = (q.get('track','demo'),q.get('period','2026-10'),q.get('kind','month'))
        if verb=='GET':
            if path=='/api/me':
                return public_user(user)
            if path=='/api/regions':
                if user['role']=='reporter':
                    return [flow.get_region(tx,user['scope'])]
                role(user,'method','approver','analyst','technical')
                return tx.all('SELECT * FROM regions ORDER BY kind,name')
            if path=='/api/dashboard':
                return flow.dashboard(tx,user,track,period,kind)
            if path=='/api/report':
                return flow.result_card(tx,user,track,period,kind,q.get('region'),
                                        int(q['revision']) if q.get('revision') else None)
            if path=='/api/packages':
                return flow.list_packages(tx,user,track,period,kind)
            if path=='/api/calendar':
                flow.period_key(period,kind)
                return flow.deadlines(tx,period,kind)
            if path=='/api/methods':
                return methods.list_methods(tx,user)
            if path=='/api/discrepancies':
                role(user,'method','approver','analyst')
                catalog = json.loads((ROOT/'data'/'catalog.json').read_text('utf8'))
                return catalog['issues']
            deputy = re.fullmatch(r'/api/deputies/([a-z0-9-]+)/results',path)
            if deputy:
                return flow.deputy_history(tx,user,deputy[1],track,period,kind)
            if path=='/api/deputies':
                role(user,'method','approver','analyst')
                return [dict(x,assignments=json.loads(x['assignments']))
                        for x in tx.all('SELECT * FROM deputies ORDER BY region,starts,name')]
            if path=='/api/export.xlsx':
                xlsx = exchange.report_workbook(tx,user,track,period,kind,q.get('region'))
                return bytes_response(xlsx,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',f'KPI КГД {period}.xlsx')
            if path=='/api/export.pdf':
                pdf = exchange.report_pdf(tx,user,track,period,kind,q.get('region'),q.get('deputy'))
                return bytes_response(pdf,'application/pdf',f'KPI КГД {period}.pdf')
        if verb=='POST':
            if path=='/api/packages':
                id = flow.open_package(tx,user,track,period,kind,body.get('department'))
                return {'id':id}
            if path=='/api/methods':
                return methods.new_version(tx,user,body)
            if path=='/api/deputies':
                return methods.assign_deputy(tx,user,body)
        if path=='/api/calendar' and verb=='PUT':
            return save_calendar(tx,user,period,kind,body)
        if path.startswith('/api/technical'):
            return technical(tx,user,path,verb,body)
        match = re.fullmatch(r'/api/packages/([a-f0-9]{32})(?:/([a-z.]+))?(?:/([a-f0-9]{32}))?',path)
        if match:
            return self.package_request(tx,user,verb,q,body,*match.groups())
        match = re.fullmatch(r'/api/methods/([a-z0-9-]+)(?:/([a-z_]+))?',path)
        if match:
            identifier,action = match.groups()
            if verb=='GET':
                if action=='diff':
                    return methods.compare_versions(tx,user,identifier)
                if action=='history':
                    methods.get_version(tx,user,identifier)
                    return flow.history(tx,identifier)
                if action is None:
                    return methods.get_version(tx,user,identifier)
            if verb=='PUT' and action=='aggregate':
                return methods.aggregate_decision(tx,user,identifier,body)
            if verb=='PUT' and action=='entry':
                return methods.save_entry(tx,user,identifier,body)
            if verb=='POST' and action=='preview':
                return methods.preview_rule(tx,user,identifier,body)
            if verb=='POST' and action:
                return methods.method_action(tx,user,identifier,action)
        raise Problem(404,'Действие не найдено.')

    def package_request(self,tx,user,verb,q,body,id,action,file_id):
        if verb=='GET':
            if not action:
                return flow.package_detail(tx,user,id)
            if action=='template.xlsx':
                xlsx = exchange.package_template(tx,user,id)
                return bytes_response(xlsx,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Ввод KPI.xlsx')
            if action=='signature':
                p = flow.package_detail(tx,user,id)
                require(p['signature'],404,'Подписанная версия пока недоступна.')
                raw = flow.get_package(tx,user,id)
                data = {'payload':flow.signing_payload(raw,p['attachments']),'signature':p['signature']}
                return bytes_response(encode(data).encode(),'application/json; charset=utf-8','Подписанный пакет KPI.json')
            if action=='attachment' and file_id:
                flow.get_package(tx,user,id)
                file = tx.one('SELECT * FROM attachments WHERE id=? AND package=?',(file_id,id))
                require(file and digest(bytes(file['content']))==file['sha256'],404,'Файл отсутствует или нарушена целостность.')
                return bytes_response(bytes(file['content']),file['media_type'],file['name'])
        if verb=='POST':
            if action=='attachment':
                return flow.add_attachment(tx,user,id,int(q.get('generation','-1')),q.get('code'),q.get('name'),
                                           self.headers.get('Content-Type',''),body)
            if action=='import':
                return exchange.package_import(tx,user,id,body,int(q.get('generation','-1')),q.get('apply')=='1')
            if action=='prefill':
                role(user,'reporter')
                p = flow.get_package(tx,user,id)
                require(p['track']=='demo',422,'Синтетический источник доступен в демонстрационном контуре.')
                facts = json.loads(p['facts'])
                notes = json.loads(p['notes'])
                codes = [e['code'] for e in flow.package_entries(tx,p)
                         if not facts.get(e['code']) and (p['status']!='returned' or e['code'] in notes)]
                data = SyntheticSource().fetch(p['region'],p['period'],p['kind'],codes)
                require(data,422,'Для незаполненных строк нет синтетического источника.')
                result = flow.update_package(tx,user,id,'save',dict(body,facts={k:v['values'] for k,v in data.items()}))
                audit(tx,user['id'],id,'source_prefill',data)
                return result
            if action:
                return flow.update_package(tx,user,id,action,body)
        if verb=='DELETE' and action=='attachment' and file_id:
            flow.allow_delete_attachment(tx,user,id,file_id,int(q.get('generation','-1')))
            return {'ok':True}
        raise Problem(404,'Действие не найдено.')


def make_server(db,host='127.0.0.1',port=8765):
    db.migrate()
    seed(db)
    server = ThreadingHTTPServer((host,port),Handler)
    server.db = db
    return server


def main():
    parser = argparse.ArgumentParser(description='Локальная демонстрация KPI КГД')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    with make_server(DB(),args.host,args.port) as server:
        print(f'Local: http://{args.host}:{server.server_port}',flush=True)
        server.serve_forever()


if __name__=='__main__':
    main()
