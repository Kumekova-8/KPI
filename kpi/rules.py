"""Bounded arithmetic and declarative scoring. All arithmetic uses Decimal."""
import ast
from decimal import Decimal, DecimalException
import operator
import re

OPERATIONS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
COMPARISONS = {'ge': operator.ge, 'gt': operator.gt, 'le': operator.le, 'lt': operator.lt, 'eq': operator.eq}
CADENCES = {'month','quarter','year','multi','control'}
PERIODS = {'month','quarter','year'}
STATUS = {
    'ok':'Рассчитано', 'missing':'Данные не представлены', 'unconfirmed':'Данные не подтверждены',
    'na':'Не применяется', 'impossible':'Расчёт невозможен', 'blocked':'Требуется уточнение методики',
    'preview':'Предварительный расчёт',
}


def dec(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError('Ожидается число.')
    try:
        result = Decimal(str(value).replace(',', '.'))
    except DecimalException as exc:
        raise ValueError('Ожидается число.') from exc
    if not result.is_finite() or abs(result) > Decimal('1e20'):
        raise ValueError('Число вне допустимого диапазона.')
    return result


def parse(expression, keys):
    if not isinstance(expression,str) or len(expression)>220:
        raise ValueError('Длина формулы должна быть не более 220 символов.')
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except SyntaxError as exc:
        raise ValueError('Некорректная арифметическая формула.') from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 80:
        raise ValueError('Формула слишком сложна.')
    for node in nodes:
        if isinstance(node, (ast.Expression, ast.Load)) or type(node) in OPERATIONS:
            continue
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATIONS:
            continue
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            dec(node.value)
            continue
        if isinstance(node, ast.Name) and node.id in keys:
            continue
        raise ValueError('Допустимы поля, числа, скобки и действия +, −, ×, ÷.')
    if {n.id for n in nodes if isinstance(n,ast.Name)} != set(keys):
        raise ValueError('Каждое поле правила должно участвовать в формуле.')
    return tree.body


def evaluate(tree, data):
    if isinstance(tree, ast.Name):
        return data[tree.id]
    if isinstance(tree, ast.Constant):
        return dec(tree.value)
    left = evaluate(tree.left, data)
    right = evaluate(tree.right, data)
    return OPERATIONS[type(tree.op)](left, right)


def entry_base(entry):
    return dec(entry['metric_weight']) * dec(entry['weight']) / 100


def validate_rule(rule, base):
    fields = rule.get('fields')
    if not isinstance(fields,list) or not 1 <= len(fields) <= 16:
        raise ValueError('Укажите от 1 до 16 исходных полей.')
    keys = [field.get('key','') for field in fields]
    if len(set(keys)) != len(keys) or not all(re.fullmatch('[A-Z][A-Z0-9_]{0,15}', k) for k in keys):
        raise ValueError('Коды исходных полей должны быть уникальными латинскими идентификаторами.')
    if any(not isinstance(f.get('label'),str) or not f['label'].strip() for f in fields):
        raise ValueError('Введите названия исходных полей.')
    for field in fields:
        if field.get('min') is not None:
            dec(field['min'])
    parse(rule.get('expression'), keys)

    def validate_bands(bands):
        if not isinstance(bands,list) or not 1 <= len(bands) <= 20:
            raise ValueError('Добавьте от 1 до 20 порогов.')
        previous = []
        for band in bands:
            kind = band.get('op')
            if kind not in {*COMPARISONS, 'range'}:
                raise ValueError('Неизвестное условие шкалы.')
            target, points = dec(band.get('target')), dec(band.get('points'))
            if not 0 <= points <= base:
                raise ValueError('Баллы в шкале должны быть от 0 до базового балла.')
            if kind == 'range' and dec(band.get('upper')) < target:
                raise ValueError('Верхняя граница диапазона ниже нижней.')
            for before in previous:
                earlier = before['op']
                bound = dec(before['target'])
                if (kind == earlier and ((kind in ('ge','gt') and bound <= target) or
                    (kind in ('le','lt') and bound >= target) or (kind == 'eq' and bound == target))):
                    raise ValueError('Предыдущий порог полностью перекрывает это условие.')
                if kind == earlier == 'range' and target <= dec(before['upper']) and bound <= dec(band['upper']):
                    raise ValueError('Диапазоны шкалы пересекаются.')
            previous.append(band)

    if rule.get('default') is not None and not 0 <= dec(rule['default']) <= base:
        raise ValueError('Баллы по умолчанию превышают базовый балл.')
    variants = rule.get('variants',[])
    if not variants or rule.get('bands'):
        validate_bands(rule.get('bands'))
    if not isinstance(variants,list) or len(variants) > 20:
        raise ValueError('Допустимо до 20 вариантов шкалы.')
    preceding = []
    for variant in variants:
        validate_bands(variant.get('bands'))
        if 'months' in variant and (not variant['months'] or not set(variant['months']) <= set(range(1,13))):
            raise ValueError('Укажите допустимые месяцы варианта.')
        if 'year' in variant and (type(variant['year']) is not int or not 2000 <= variant['year'] <= 2199):
            raise ValueError('Недопустимый год варианта.')
        if 'period_type' in variant and variant['period_type'] not in PERIODS:
            raise ValueError('Недопустимый тип периода.')
        if 'field' in variant:
            if variant['field'] not in keys or (variant.get('high') is not None and dec(variant['high']) < dec(variant.get('low'))):
                raise ValueError('Недопустимые диапазоны поля варианта.')
            dec(variant.get('low'))
        if not {'months','year','period_type','field'}.intersection(variant):
            raise ValueError('Задайте условие выбора варианта шкалы.')
        if any(variant_overlap(variant, earlier) for earlier in preceding):
            raise ValueError('Условия выбора вариантов шкалы пересекаются.')
        preceding.append(variant)


def variant_overlap(first, second):
    if any(key in first and key in second and first[key]!=second[key] for key in ('year','period_type')):
        return False
    if 'months' in first and 'months' in second and not set(first['months']).intersection(second['months']):
        return False
    if first.get('field') and first['field']==second.get('field'):
        lo_a,lo_b = dec(first['low']),dec(second['low'])
        hi_a = dec(first['high']) if first.get('high') is not None else Decimal('Infinity')
        hi_b = dec(second['high']) if second.get('high') is not None else Decimal('Infinity')
        return lo_a<=hi_b and lo_b<=hi_a
    return True


def input_values(rule, supplied):
    fields = rule['fields'] if rule else [{'key':'A','label':'Фактическое значение'}]
    if not isinstance(supplied,dict) or set(supplied) - {f['key'] for f in fields}:
        raise ValueError('Неизвестные поля фактических данных.')
    values = {}
    for field in fields:
        key = field['key']
        if supplied.get(key) in ('',None):
            continue
        value = dec(supplied[key])
        if field.get('min') is not None and value < dec(field['min']):
            raise ValueError(f'Поле {key} меньше допустимого значения.')
        values[key] = str(value)
    return values


def applicable(entry, region, period, kind):
    applies = entry['applicability']
    if entry.get('inactive') or applies.get('kind','dgd') != region['kind']:
        return False
    if applies.get('regions') and region['id'] not in applies['regions']:
        return False
    month = int(period[-2:])
    cadence = entry['cadence']
    if cadence=='control':
        return month in {int(day[:2]) for day in entry.get('control_dates',('09-15','12-31'))}
    return (cadence in ('month','multi') or cadence == 'quarter' and kind in ('quarter','year') or
            cadence == 'year' and kind == 'year')


def variant_matches(variant, data, period, kind):
    year,month = map(int,period.split('-'))
    if 'year' in variant and year != variant['year']:
        return False
    if 'months' in variant and month not in variant['months']:
        return False
    if 'period_type' in variant and kind != variant['period_type']:
        return False
    if 'field' in variant:
        value = data[variant['field']]
        if value < dec(variant['low']) or (variant.get('high') is not None and value > dec(variant['high'])):
            return False
    return True


def calculate(entry, supplied, period, kind, signed=False, preview=False):
    base = entry_base(entry)
    result = {'base': float(base), 'actual':None, 'points':None}
    rule = entry.get('rule')
    if entry.get('blockers') or not rule:
        return dict(result,status='blocked')
    data = input_values(rule, supplied)
    if len(data) != len(rule['fields']):
        return dict(result,status='missing')
    if not signed and not preview:
        return dict(result,status='unconfirmed')
    try:
        data = {key: dec(value) for key,value in data.items()}
        actual = evaluate(parse(rule['expression'], data.keys()), data)
        dec(actual)
    except (ValueError, DecimalException, ZeroDivisionError):
        return dict(result,status='impossible')
    result['actual'] = float(actual)
    variants = rule.get('variants',[])
    matching = [v for v in variants if variant_matches(v,data,period,kind)]
    if len(matching)>1 or (variants and not matching and not rule['bands']):
        return dict(result,status='blocked')
    bands = matching[0]['bands'] if matching else rule['bands']
    points = rule.get('default')
    for band in bands:
        target = dec(band['target'])
        match = (target <= actual <= dec(band['upper']) if band['op']=='range'
                 else COMPARISONS[band['op']](actual,target))
        if match:
            points = band['points']
            break
    if points is None:
        return dict(result,status='blocked')
    return dict(result,points=float(dec(points)),status='ok' if signed else 'preview')


def aggregate(rows, subject, denominator=None, blocks=False):
    """Appendix 1: p. 24 by indicators, p. 25 with approved denominator, p. 26 by base points."""
    applicable_rows = [row for row in rows if row['status'] != 'na']
    groups = {}
    for column in ('metric','indicator','block'):
        groups[column] = {}
        for row in applicable_rows:
            group = groups[column].setdefault(row[column],{'base':Decimal(0),'points':Decimal(0),'complete':True})
            group['base'] += dec(row['base'])
            if row['points'] is None:
                group['complete'] = False
            else:
                group['points'] += dec(row['points'])
    points = sum((dec(row['points']) for row in applicable_rows if row['points'] is not None),Decimal(0))
    base = sum((dec(row['base']) for row in applicable_rows),Decimal(0))
    statuses = {row['status'] for row in applicable_rows}
    status = next((s for s in ('blocked','impossible','missing','unconfirmed','preview') if s in statuses),'ok')
    total = None
    if not applicable_rows:
        status = 'na'
    elif blocks or subject=='ctl' and denominator is None:
        status = 'blocked'
    elif status in ('ok','preview'):
        if subject=='dgd':
            total = points / len(groups['indicator'])
        elif subject=='ctl' and dec(denominator)>0:
            total = points / dec(denominator) * 100
        elif subject=='deputy' and base:
            total = points / base * 100
        else:
            status = 'impossible'
    display_groups = {key:{code:{'base':float(g['base']),'points':float(g['points']) if g['complete'] else None}
                           for code,g in values.items()} for key,values in groups.items()}
    return {'status':status,'total':float(total) if total is not None else None,
            'groups':display_groups,'base':float(base),'reported':sum(r['points'] is not None for r in applicable_rows),
            'required':len(applicable_rows)}



def rating_grade(total, demo=False):
    if total is None or not 0<=dec(total)<=100:
        return None
    for lower,upper,code,label in ((90,100,'A','Отлично'),(75,89,'B','Хорошо'),
                                  (60,74,'C','Удовлетворительно'),(40,59,'D','Ниже ожиданий'),
                                  (0,None,'F','Неудовлетворительно')):
        if dec(total)>=lower and (demo or (dec(total)<40 if upper is None else dec(total)<=upper)):
            return {'code':code,'label':label}
    return None
