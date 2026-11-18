"""Synthesize a demo database. Excel facts and cached results are never copied."""
import json
import os
import random

from .db import ROOT, encode
from .integrations import demonstration_signature
from .security import audit, now, password_hash
from .workflow import base_package, entries_for, get_method, persist_result, signing_payload

PASSWORD = 'Kpi-demo-26!'
REGIONS = [
    ('abai','Абайская область'),('akmola','Акмолинская область'),('aktobe','Актюбинская область'),
    ('almaty-obl','Алматинская область'),('atyrau','Атырауская область'),('east','Восточно-Казахстанская область'),
    ('jambyl','Жамбылская область'),('jetisu','Область Жетісу'),('west','Западно-Казахстанская область'),
    ('karaganda','Карагандинская область'),('kostanay','Костанайская область'),('kyzylorda','Кызылординская область'),
    ('mangystau','Мангистауская область'),('pavlodar','Павлодарская область'),('north','Северо-Казахстанская область'),
    ('turkistan','Туркестанская область'),('ulytau','Область Ұлытау'),('astana','г. Астана'),
    ('almaty','г. Алматы'),('shymkent','г. Шымкент'),('ctl','Центральная таможенная лаборатория'),
]
DEPTS = {'dasur':'ДАСУР','dna':'ДНА','audit':'ДА','dta':'ДТА','personnel':'ДУПиВА','service':'ДГУ',
         'fl':'ДАНПФЛ','dtk':'ДТК','debts':'УРНД','dkn':'ДКН','training':'УМЦ'}
ACCOUNTS = [
    ('analyst','Управление стратегического развития','analyst',''),
    ('dgd','Специалист ДГД Абайской области','reporter','abai'),
    ('dgd-astana','Специалист ДГД г. Астаны','reporter','astana'),
    ('ctl','Специалист ЦТЛ','reporter','ctl'),
    ('method','Администратор методики','method',''),
    ('approval','Утверждающий методику','approver',''),
    ('tech','Технический администратор','technical',''),
]
ACCOUNTS += [(f'{role}-{id}',f'{label} · {dep}',role,dep) for id,dep in DEPTS.items()
             for role,label in [('reviewer','Проверяющий'),('signer','Подписант')]]


def demo_content(catalog):
    by_code = {e['code']:e for e in catalog['entries']}
    entries = []
    selected = [
        ('S001', '1','1.1','Фискальный блок',100,'ДАСУР',100,'ge'),
        ('S017', '4','4.3','Администрирование',100,'ДАНПФЛ',80,'ge'),
        ('S057', '7','7.1','Контрольный блок',45,'ДА',20,'le'),
        ('S058', '7','7.1','Контрольный блок',55,'ДА',1,'le'),
        ('S081', '12','12.1','Сервисный блок',100,'ДУПиВА',100,'ge'),
        ('S088', '14','14.1','Управленческий блок',100,'ДУПиВА',0,'eq'),
        ('S039', '5','5.4','Администрирование',100,'ДТА',100,'ge'),
        ('S041', '5','5.5','Администрирование',100,'ДТА',100,'ge'),
    ]
    for code,indicator,metric,block,weight,dept,target,op in selected:
        src = by_code[code]
        fields = src['rule']['fields']
        if code=='S039':
            fields = [{'key':'A','label':'Экспертизы в демонстрационный срок','min':0},
                      {'key':'B','label':'Все проведённые экспертизы','min':0}]
        metric_weight = 50 if src['applicability']['kind']=='ctl' else 100
        base = metric_weight * weight / 100
        cuts = [(target,base)]
        if op=='ge':
            cuts += [(target*0.95,base*0.9),(target*0.90,base*0.8),(target*0.80,base*0.65)]
        elif op=='le':
            cuts += [(target*1.25,base*0.85),(target*1.5,base*0.7)]
        bands = [{'op':op,'target':round(t,3),'points':round(p,4)} for t,p in cuts]
        expr = 'A' if code=='S088' else 'A/B*100'
        keys = ('code','name','source','indicator_name','metric_name','applicability','cumulative')
        entries.append(dict({k:src[k] for k in keys},indicator=indicator,metric=metric,block=block,
                            weight=weight,metric_weight=metric_weight,cadence='month',department=dept,
                            instruction='Демонстрационный сценарий. Веса, периодичность и пороги изменены для проверки платформы.',
                            blockers=[],inactive=False,rule={'expression':expr,'fields':fields,'bands':bands,'default':0}))
    return {'entries':entries,'ctl_denominator':100,'aggregate_blockers':{}}


def create_signed(tx,p,signer,reviewer):
    p = dict(p,status='signed')
    p['signature'] = encode(demonstration_signature(signing_payload(p,[]),signer))
    tx.insert('packages',p)
    audit(tx,reviewer,p['id'],'check',{'seed':True})
    audit(tx,signer,p['id'],'sign',{'seed':True,'label':'Демонстрационная подпись'})


def facts_for(entries,randomizer,quality):
    facts = {}
    for e in entries:
        code = e['code']
        target = e['rule']['bands'][0]['target']
        jitter = randomizer.uniform(-3,3)
        if code=='S088':
            facts[code] = {'A':'0' if quality>80 or randomizer.random()>0.06 else '1'}
        elif code in ('S057','S058'):
            actual = target * (1+(93-quality-jitter)/55)
            facts[code] = {'A':str(round(actual*10,2)),'B':'1000'}
        else:
            actual = min(target*(1+(quality-91+jitter)/120),100) if code!='S001' else quality+8+jitter
            facts[code] = {'A':str(round(actual*10,2)),'B':'1000'}
    return facts


def seed(db):
    with db.transaction(write=True) as tx:
        if tx.one('SELECT id FROM methods WHERE id=?',('demo-v1',)):
            return
        for id,name,role,scope in ACCOUNTS:
            tx.insert('users',dict(id=id,name=name,role=role,scope=scope,password=password_hash(PASSWORD),active=1))
        for id,name in REGIONS:
            tx.insert('regions',dict(id=id,name=name,kind='ctl' if id=='ctl' else 'dgd'))
        catalog = json.loads((ROOT/'data'/'catalog.json').read_text('utf8'))
        entries = catalog['entries']
        source = {'entries':entries,'ctl_denominator':None,
                  'aggregate_blockers':{'dgd':['G-02','G-06'],'ctl':['G-03','G-06','G-08'],'deputy':['G-04','G-06']}}
        for track,name,content in [('demo','Демонстрационная методика 1.0',demo_content(catalog)),
                                   ('source','Редакция по исходным документам',source)]:
            tx.insert('methods',dict(id=f'{track}-v1',track=track,parent=None,name=name,effective='2026-01',
                                     reason='Первичная загрузка',status='published',author='method',approver=None,
                                     created=now(),content=encode(content)))
        for i,(id,name) in enumerate(REGIONS):
            codes = [(['S039','S041'],['S039','S041'])] if id=='ctl' else [
                (['S001','S017'],['1.1','4.3']),(['S057','S058','S081','S088'],['7.1','12.1','14.1'])]
            titles = ['Заместитель по администрированию','Заместитель по контролю']
            for j,(demo,source) in enumerate(codes):
                tx.insert('deputies',dict(id=f'{id}-{j+1}',region=id,name=f'Демонстрационный заместитель {i*2+j+1:02d}',
                                         title=titles[j],starts='2026-01-01',ends=None,person=f'{id}-{j+1}',
                                         assignments=encode(dict(demo=demo,source=source))))

        randomizer = random.Random(20261116)
        periods = [(f'2026-{m:02d}','month') for m in range(5,11)]
        periods += [('2026-06','quarter'),('2026-09','quarter')]
        for period,kind in periods:
            method = get_method(tx,'demo',period,kind,pin=True)
            for i,(id,name) in enumerate(REGIONS):
                region = {'id':id,'kind':'ctl' if id=='ctl' else 'dgd'}
                selected = entries_for(method,region,period,kind)
                quality = 78 + (i*7%17) + (int(period[-2:])-5)*0.75 + randomizer.uniform(-3,3)
                facts = facts_for(selected,randomizer,quality)
                by_dept = {value:key for key,value in DEPTS.items()}
                unfinished = {'abai':'draft','aktobe':'submitted','north':'returned','jambyl':'checked',
                              'mangystau':'missing','ulytau':'submitted'}
                last = None
                for department in sorted({e['department'] for e in selected}):
                    state = (unfinished.get(id,'signed') if period=='2026-10' and department=='ДАСУР'
                             else 'signed')
                    if state=='missing':
                        continue
                    branch = by_dept[department]
                    p = base_package('demo',period,kind,id,department,method['id'],
                                     facts={e['code']:facts[e['code']] for e in selected if e['department']==department})
                    if state=='signed':
                        create_signed(tx,p,f'signer-{branch}',f'reviewer-{branch}')
                        last = p
                    else:
                        notes = {'S001':'Уточните поступления за отчётный период.'} if state=='returned' else {}
                        tx.insert('packages',dict(p,status=state,notes=encode(notes)))
                        if state=='checked':
                            audit(tx,f'reviewer-{branch}',p['id'],'check',{'seed':True})
                        if state=='returned':
                            audit(tx,f'reviewer-{branch}',p['id'],'return',notes)
                if last:
                    persist_result(tx,last)
