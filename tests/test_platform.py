from copy import deepcopy
from http import client
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from openpyxl import load_workbook
from pypdf import PdfReader

from kpi.db import DB, ROOT
from kpi.rules import aggregate, applicable, calculate, validate_rule
from kpi.seed import PASSWORD, demo_content
from kpi.server import Handler, make_server

CATALOG = json.loads((ROOT/'data'/'catalog.json').read_text('utf8'))
REFERENCE = {row['code']:row for row in CATALOG['entries']}
DEMO = {row['code']:row for row in demo_content(CATALOG)['entries']}


class RuleTests(unittest.TestCase):
    def test_catalog_coverage(self):
        self.assertEqual(len(REFERENCE), 88)
        self.assertEqual(len({row['metric'] for row in REFERENCE.values()}), 29)
        self.assertEqual(len({row['indicator'] for row in REFERENCE.values()}), 14)
        self.assertEqual(len({row['block'] for row in REFERENCE.values()}), 5)
        self.assertEqual({s:len(x['formulas']) for s,x in CATALOG['workbook'].items()},
                         {'Абай':128,'Расчеты KPI':128,'Перечень KPI':0,'ШКАЛА':0})
        for row in REFERENCE.values():
            if not row['blockers']:
                self.assertIsNotNone(row['rule'], row['code'])
                from kpi.rules import entry_base
                validate_rule(row['rule'], entry_base(row))

    def test_original_rows_and_boundary(self):
        row = REFERENCE['S007']
        self.assertEqual(calculate(row,{'A':20,'B':20},'2026-10','month',True)['points'],60)
        self.assertEqual(calculate(row,{'A':'19.9999','B':20},'2026-10','month',True)['points'],0)
        row = REFERENCE['S018']
        self.assertEqual(calculate(row,{'A':98,'B':100},'2026-09','quarter',True)['points'],7)
        self.assertEqual(calculate(row,{'A':'98.001','B':100},'2026-09','quarter',True)['points'],0)

    def test_special_volume_brackets(self):
        row = REFERENCE['S042']
        first = calculate(row,{'A':8,'B':100},'2026-10','month',True)
        second = calculate(row,{'A':16,'B':200},'2026-10','month',True)
        self.assertEqual(first['actual'],second['actual'])
        self.assertEqual((first['points'],second['points']),(4,5))

    def test_nullable_states(self):
        row = REFERENCE['S007']
        def run(values,signed=False):
            return calculate(row,values,'2026-10','month',signed)
        self.assertEqual(run({})['status'],'missing')
        self.assertEqual(run({'A':0,'B':100})['status'],'unconfirmed')
        self.assertEqual(run({'A':0,'B':100},True)['points'],0)
        self.assertEqual(run({'A':10,'B':0},True)['status'],'impossible')
        self.assertEqual(calculate(REFERENCE['S021'],{},'2026-09','quarter',True)['status'],'blocked')

    def test_period_and_territory(self):
        data = {'kind':'dgd','id':'abai'}
        self.assertFalse(applicable(REFERENCE['S018'],data,'2026-09','month'))
        self.assertTrue(applicable(REFERENCE['S018'],data,'2026-09','quarter'))
        self.assertFalse(applicable(REFERENCE['S082'],data,'2026-09','quarter'))
        self.assertTrue(applicable(REFERENCE['S082'],data,'2026-12','year'))
        self.assertTrue(applicable(REFERENCE['S045'],data,'2026-09','month'))
        self.assertFalse(applicable(REFERENCE['S046'],data,'2026-09','month'))
        configured = dict(REFERENCE['S016'],control_dates=['08-15'])
        self.assertTrue(applicable(configured,data,'2026-08','month'))
        self.assertFalse(applicable(configured,data,'2026-09','month'))

    def test_three_subject_calculations(self):
        def row(metric,ind,base,points):
            return dict(metric=metric,indicator=ind,block='A',base=base,points=points,status='ok')
        items = [row('1.1','1',60,60),row('1.2','1',40,20),row('2.1','2',100,50)]
        result = aggregate(items,'dgd')
        self.assertEqual(result['total'],65)
        self.assertEqual(result['groups']['indicator']['1']['points'],80)
        self.assertEqual(result['groups']['metric']['1.2']['points'],20)
        self.assertEqual(aggregate(items[:2],'ctl',100)['total'],80)
        self.assertEqual(aggregate(items[:2],'ctl')['status'],'blocked')
        self.assertEqual(aggregate(items[1:],'deputy')['total'],50)

    def test_grade_source_precision(self):
        from kpi.rules import rating_grade
        self.assertIsNone(rating_grade(89.5))
        self.assertEqual(rating_grade(89.5,demo=True)['code'],'B')
        self.assertEqual(rating_grade(90)['code'],'A')

    def test_ast_whitelist(self):
        payload = deepcopy(DEMO['S001']['rule'])
        for expression in ('__import__("os")','A.__class__','A**B','[A,B]','(lambda:1)()'):
            payload['expression']=expression
            with self.assertRaises(ValueError, msg=expression):
                validate_rule(payload,100)

    def test_invalid_variant_overlap(self):
        rule = deepcopy(REFERENCE['S042']['rule'])
        rule['variants'][0]['high'] = 101
        with self.assertRaisesRegex(ValueError,'пересекаются'):
            validate_rule(rule,5)

    def test_invalid_weights(self):
        from kpi.methodology import validate_content
        from kpi.security import Problem
        entries = demo_content(CATALOG)
        validate_content(entries)
        entries['entries'][0]['metric_weight'] = 99
        with self.assertRaises((ValueError,Problem)):
            validate_content(entries)


class MemorySocket:
    def __init__(self,request):
        self.reader = BytesIO(request)
        self.writer = BytesIO()

    def makefile(self, mode, *args):
        return self.reader if 'r' in mode else self.writer

    def sendall(self,data):
        self.writer.write(data)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        db = DB(os.environ.get('KPI_TEST_DATABASE') or Path(cls.temp.name)/'isolated.sqlite3')
        cls.server = make_server(db,port=0)
        cls.live = os.getenv('KPI_TEST_LIVE')=='1'
        if cls.live:
            cls.worker = Thread(target=cls.server.serve_forever,daemon=True)
            cls.worker.start()
        cls.sessions = {}

    @classmethod
    def tearDownClass(cls):
        if cls.live:
            cls.server.shutdown()
            cls.worker.join()
        cls.server.server_close()
        cls.temp.cleanup()

    def send(self,path,verb='GET',payload=None,user=None,expected=200,content_type='application/json'):
        body = payload if isinstance(payload,bytes) else json.dumps(payload).encode() if payload is not None else b''
        headers = {'Content-Length':str(len(body)),'Content-Type':content_type,'Host':'127.0.0.1'}
        if user:
            headers['Cookie'] = self.sessions[user]
        if self.live:
            conn = client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=8)
            conn.request(verb,path,body,headers)
            response = conn.getresponse()
            status, raw = response.status, response.read()
            headers = {k.lower():v for k,v in response.getheaders()}
            conn.close()
        else:
            lines = '\r\n'.join(f'{k}: {v}' for k,v in headers.items())
            wire = f'{verb} {path} HTTP/1.0\r\n{lines}\r\n\r\n'.encode()+body
            sock = MemorySocket(wire)
            Handler(sock,('127.0.0.1',12345),self.server)
            head,raw = sock.writer.getvalue().split(b'\r\n\r\n',1)
            lines = head.decode('latin1').split('\r\n')
            status = int(lines.pop(0).split()[1])
            headers = {k.lower():v.strip() for k,v in (line.split(':',1) for line in lines if line)}
        data = json.loads(raw) if 'application/json' in headers['content-type'] else raw
        self.assertEqual(status,expected,f'{verb} {path}: {data if isinstance(data,dict) else type(data)}')
        return data,headers

    def login(self,user):
        if user not in self.sessions:
            result, headers = self.send('/api/login','POST',{'username':user,'password':PASSWORD})
            self.assertEqual(result['id'],user)
            self.assertIn('HttpOnly',headers['set-cookie'])
            self.sessions[user] = headers['set-cookie'].split(';',1)[0]

    def test_access(self):
        self.send('/api/dashboard',expected=401)
        self.login('dgd')
        self.send('/api/dashboard',user='dgd',expected=403)
        self.send('/api/report?region=astana',user='dgd',expected=403)
        self.login('tech')
        self.send('/api/methods',user='tech',expected=403)
        self.assertEqual(self.send('/api/health')[0]['status'],'ok')
        self.assertIn('Вход'.encode(), self.send('/app.js')[0])

    def test_complete_workflow_and_history(self):
        reporter,reviewer,signer,analyst = 'dgd','reviewer-dasur','signer-dasur','analyst'
        for user in (reporter,reviewer,signer,analyst,'reviewer-dta'):
            self.login(user)
        listed,_ = self.send('/api/packages',user=reporter)
        package = next(row for row in listed['packages'] if row['department']=='ДАСУР')
        self.assertEqual(package['status'],'draft')
        path = '/api/packages/'+package['id']
        self.send(path,user=reviewer,expected=404)
        self.send(path,user='reviewer-dta',expected=403)
        current,_ = self.send(path,user=reporter)
        generation = current['generation']
        def post(action,user,body=None,expected=200):
            nonlocal generation
            result,_ = self.send(path+'/'+action,'POST',dict(body or {},generation=generation),user,expected)
            if expected==200:
                generation += 1
            return result
        post('save',reporter,{'facts':{'S001':{'A':'105','B':'0'}}})
        post('submit',reporter,expected=422)
        post('save',reporter,{'facts':{'S001':{'A':'105','B':'100'}}})
        pdf_stub = b'%PDF-1.4\nsynthetic\n'
        target = path+f'/attachment?generation={generation}&code=S001&name=test.pdf'
        file,_ = self.send(target,'POST',pdf_stub,reporter,content_type='application/pdf')
        generation+=1
        download,_ = self.send(path+'/attachment/'+file['id'],user=reporter)
        self.assertEqual(download,pdf_stub)
        self.send(path+'/save','POST',dict(generation=generation-1,facts={}),reporter,409)
        post('submit',reporter)
        post('sign',signer,expected=409)
        post('return',reviewer,{'comments':{'S001':'Проверить сумму.'}})
        returned,_ = self.send(path,user=reporter)
        self.assertEqual(returned['notes']['S001'],'Проверить сумму.')
        post('save',reporter,{'facts':{'S001':{'A':'103','B':'100'}}})
        post('submit',reporter)
        post('check',reviewer)
        post('sign',reviewer,expected=403)
        post('sign',signer)
        signed,_ = self.send(path,user=reporter)
        self.assertTrue(signed['signature']['valid_digest'])
        self.assertEqual(signed['signature']['label'],'Демонстрационная подпись')
        original,_ = self.send('/api/report?region=abai',user=analyst)
        self.assertEqual(original['official']['revision'],1)
        self.assertIsNotNone(original['official']['total'])
        self.assertTrue(original['official']['deputies'])
        post('save',reporter,{'facts':{}},expected=409)
        created = post('revise',reporter,{'reason':'Контрольная корректировка'})
        revised = '/api/packages/'+created['id']
        still_original,_ = self.send('/api/report?region=abai',user=analyst)
        self.assertEqual(still_original['official']['total'],original['official']['total'])
        result,_ = self.send(revised,user=reporter)
        self.assertEqual(result['revision'],2)
        self.assertEqual(result['facts']['S001']['A'],'103')
        for step,user,data in [('save',reporter,{'facts':{'S001':{'A':'80','B':'100'}}}),('submit',reporter,{}),
                               ('check',reviewer,{}),('sign',signer,{})]:
            self.send(revised+'/'+step,'POST',dict(data,generation=result['generation']),user)
            result['generation']+=1
        updated,_ = self.send('/api/report?region=abai',user=analyst)
        self.assertEqual(updated['official']['revision'],2)
        self.assertLess(updated['official']['total'],original['official']['total'])
        self.assertEqual(len(updated['history']),2)
        stored,_ = self.send('/api/report?region=abai&revision=1',user=analyst)
        self.assertEqual(stored['official'],original['official'])
        history,_ = self.send(path,user=reporter)
        self.assertEqual(history['facts']['S001']['A'],'103')
        self.assertTrue({'submit','return','check','sign'}<={row['action'] for row in history['history']})

    def test_deputy_assignment_history(self):
        for user in ('analyst','method','dgd'):
            self.login(user)
        original,_ = self.send('/api/deputies/astana-1/results',user='analyst')
        self.assertGreater(len(original['results']),1)
        self.send('/api/deputies/astana-1/results',user='dgd',expected=403)
        change,_ = self.send('/api/deputies','POST',dict(previous='astana-1',region='astana',
                             name=original['name'],title=original['title'],starts='2026-11-01',
                             track='demo',assignments=['S017']),'method')
        history,_ = self.send('/api/deputies/'+change['id']+'/results',user='analyst')
        self.assertEqual(history['results'],original['results'])
        current,_ = self.send('/api/report?region=astana&period=2026-11',user='analyst')
        assignments = next(d['assignments'] for d in current['working']['deputies'] if d['id']==change['id'])
        self.assertEqual(assignments,['S017'])

    def test_export_and_import(self):
        for user in ('analyst','dgd-astana'):
            self.login(user)
        data,_ = self.send('/api/export.xlsx',user='analyst')
        wb = load_workbook(BytesIO(data),read_only=True)
        self.assertEqual(wb.sheetnames,['Свод','Расчет KPI','Заместители','Реквизиты'])
        self.assertEqual(wb['Реквизиты']['B6'].value,'Синтетические сведения')
        wb.close()
        data,_ = self.send('/api/export.pdf?region=ctl',user='analyst')
        pages = PdfReader(BytesIO(data)).pages
        self.assertIn('Центральная таможенная лаборатория',pages[0].extract_text())
        query = '?period=2026-11'
        p,_ = self.send('/api/packages'+query,'POST',{'department':'ДАСУР'},'dgd-astana')
        path = '/api/packages/'+p['id']
        template,_ = self.send(path+'/template.xlsx',user='dgd-astana')
        wb=load_workbook(BytesIO(template))
        wb['Ввод']['D2']='102'
        wb['Ввод']['D3']='100'
        updated=BytesIO()
        wb.save(updated)
        check,_=self.send(path+'/import?generation=0','POST',updated.getvalue(),'dgd-astana')
        self.assertEqual(check,{'applied':False,'issues':[],'ready':1})
        self.send(path+'/import?generation=0&apply=1','POST',updated.getvalue(),'dgd-astana')
        p,_=self.send(path,user='dgd-astana')
        self.assertEqual(p['facts'],{'S001':{'A':'102','B':'100'}})

    def test_version_publish_and_pin(self):
        for user in ('method','approval','analyst','dgd'):
            self.login(user)
        before,_ = self.send('/api/report?region=astana',user='analyst')
        version,_ = self.send('/api/methods','POST',dict(parent='demo-v1',name='Проверка 2.0',
                               reason='Поднять минимальную цель',effective='2026-11'),'method')
        path = '/api/methods/'+version['id']
        self.send(path+'/publish','POST',{},'method',409)
        v,_ = self.send(path,user='method')
        original = next(e for e in v['content']['entries'] if e['code']=='S001')
        changed = deepcopy(original)
        changed['rule']['bands'][0]['target'] = 105
        self.send(path+'/entry','PUT',{'entry':changed,'original':original},'method')
        diff,_ = self.send(path+'/diff',user='method')
        self.assertEqual(diff[0]['after']['rule']['bands'][0]['target'],105)
        score,_ = self.send(path+'/preview','POST',
                            {'code':'S001','period':'2026-11','values':{'A':102,'B':100}},'method')
        self.assertEqual(score['points'],90)
        self.send(path+'/submit','POST',{},'method')
        self.send(path+'/approve','POST',{},'method',403)
        self.send(path+'/approve','POST',{},'approval')
        self.send(path+'/publish','POST',{},'method')
        after,_ = self.send('/api/report?region=astana',user='analyst')
        self.assertEqual(before['official'],after['official'])
        later,_ = self.send('/api/packages?period=2026-12',user='dgd')
        self.assertEqual(later['method'],'Проверка 2.0')
        self.send(path+'/entry','PUT',{'entry':original,'original':changed},'method',409)

    def test_source_discrepancies_block_totals(self):
        self.login('analyst')
        data,_=self.send('/api/dashboard?track=source',user='analyst')
        self.assertGreater(len(data['records']),0)
        self.assertTrue(all(r['total'] is None and r['status']=='blocked' for r in data['records']))
        source,_=self.send('/api/discrepancies',user='analyst')
        self.assertIn('M-021',{x['id'] for x in source if x['blocking']})
