"""Import the tables and formula evidence from the five supplied files."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

from docx import Document
from openpyxl import load_workbook

from source_rules import BLOCKS, GLOBAL_ISSUES, ISSUES, candidate


def clean(value):
    return ' '.join(str(value or '').split())


def number(value):
    match = re.fullmatch(r'(-?\d+(?:[.,]\d+)?)\s*\*?', clean(value))
    return float(match[1].replace(',', '.')) if match else None


def table(path, offset):
    return [[c.text.strip() for c in row.cells] for row in Document(path).tables[0].rows[offset:]]


def extract(directory):
    app2 = table(directory / 'Приложение 2 рус.docx', 2)
    app3 = table(directory / 'Приложение 3 рус.docx', 2)
    wb = load_workbook(directory / 'Отчет.xlsx')
    workbook_rows = wb['Перечень KPI']
    calculations = wb['Расчеты KPI']
    assert len(app2) == len(app3) == 88
    entries = []
    issues = list(GLOBAL_ISSUES)
    for n, (r, a3) in enumerate(zip(app2, app3), 1):
        row = n + 2
        indicator = int(r[0])
        metric = clean(r[2] or a3[3])
        parent = r if r[2] else app2[n-2]
        base = number(parent[4]) * number(r[8]) / 100
        assert workbook_rows[f'E{row}'].value == calculations[f'H{row}'].value == n
        assert clean(workbook_rows[f'F{row}'].value).rstrip('* ') == clean(calculations[f'I{row}'].value).rstrip('* '), n
        same_name = clean(r[6]).rstrip('* ') == clean(workbook_rows[f'F{row}'].value).rstrip('* ')
        formulae = {}
        for sheet in ('Расчеты KPI', 'Абай'):
            formulae[sheet] = {c.coordinate: c.value for c in wb[sheet][row] if c.data_type == 'f'}
        details = list(ISSUES.get(n, ()))
        if clean(r[6]).rstrip('* ') != clean(a3[7]).rstrip('* '):
            issues.append({'id': f'FORM-{n:03}', 'code': f'S{n:03}', 'blocking': False,
                           'source': f'Приложения 2–3, строка {row}',
                           'detail': 'Отличается подпись строки. Сопоставление подтверждено структурой показателя.'})
        if number(r[8]) != number(a3[8]):
            details.append(f'Вес субкомпонента {r[8]}% в приложении 2 и {a3[8]}% в приложении 3.')
        if number(a3[11]) != base:
            details.append(f'Базовый балл по весам приложения 2 равен {base:g}, в приложении 3 указан {a3[11]}.')
        if not same_name:
            issues.append({'id': f'XLS-{n:03}', 'code': f'S{n:03}', 'blocking': False,
                           'source': f'Приложение 2, строка {row}; Отчет.xlsx, Перечень KPI!F{row}',
                           'detail': 'Наименование или обозначение отличается. Связь по строкам проверяется по контексту показателя.'})
        rule, cadence, cumulative = candidate(n, r[7], base)
        if not rule and not details:
            details.append('Требуется формализация исходных параметров и правила начисления баллов.')
        if details:
            issues.append({'id': f'M-{n:03}', 'code': f'S{n:03}', 'blocking': True,
                           'source': f'Приложения 2–3, строка {row}; Отчет.xlsx, Расчеты KPI!O{row} и Абай!O{row}',
                           'detail': ' '.join(details)})
        applicability = {'kind': 'ctl'} if n in (39, 40, 41) else {'kind': 'dgd'}
        regions = {45: ['abai', 'jetisu', 'turkistan', 'almaty-obl'], 46: ['mangystau', 'east']}
        if n in regions:
            applicability['regions'] = regions[n]
        parts = re.split(r'\s*,\s*', r[11] or a3[15])
        entries.append({'code': f'S{n:03}', 'indicator': str(indicator), 'indicator_name': clean(r[1]),
                        'metric': metric, 'metric_name': clean(parent[3] or a3[4]), 'block': BLOCKS[indicator],
                        'metric_weight': number(parent[4]), 'weight': number(r[8]),
                        'name': clean(r[6]), 'department': parts[0] or 'Не назначено',
                        'co_departments': parts[1:], 'source': clean(r[10]), 'automation': clean(r[9]),
                        'instruction': r[7], 'document_row': row, 'excel_formulas': formulae,
                        'form_target': a3[9], 'form_base': number(a3[11]), 'form_weight': number(a3[8]),
                        'rule': rule, 'cadence': cadence, 'cumulative': cumulative,
                        'applicability': applicability, 'blockers': [f'M-{n:03}'] if details else [],
                        'inactive': False})
    assert len({e['metric'] for e in entries}) == 29
    assert len({e['indicator'] for e in entries}) == 14
    workbook = {}
    for sheet in wb:
        formulas = {c.coordinate: c.value for row in sheet for c in row if c.data_type == 'f'}
        workbook[sheet.title] = {'rows': sheet.max_row, 'columns': sheet.max_column, 'formulas': formulas,
                                'value_types': dict(Counter(c.data_type for row in sheet for c in row if c.value is not None))}
    files = ('Приказ рус.docx', 'Приложение 1 рус.docx', 'Приложение 2 рус.docx', 'Приложение 3 рус.docx', 'Отчет.xlsx')
    return {'files': {f: sha256((directory / f).read_bytes()).hexdigest() for f in files},
            'entries': entries, 'issues': issues, 'workbook': workbook}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    content = extract(args.sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', 'utf8')
    print(f'{len(content["entries"])} components, {len(content["issues"])} findings')


