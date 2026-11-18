"""Spreadsheet exchange and a downloadable, Cyrillic PDF report."""
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.sax.saxutils import escape

from .rules import STATUS, input_values
from .security import require
from .workflow import dashboard, package_detail, result_card, update_package


def spreadsheet(sheets):
    """Write a minimal OOXML workbook with text cells and numeric result cells."""
    def column(n):
        if n<26:
            return chr(65+n)
        return column(n//26-1)+chr(65+n%26)

    def row_xml(row,number):
        cells = []
        for index,value in enumerate(row):
            if value is None:
                continue
            ref = f'{column(index)}{number}'
            style = ' s="1"' if number==1 else ''
            if isinstance(value,(int,float)):
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                content = escape(str(value))
                cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{content}</t></is></c>')
        return f'<row r="{number}">{"".join(cells)}</row>'

    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    pack = 'http://schemas.openxmlformats.org/package/2006/relationships'
    output = BytesIO()
    with ZipFile(output,'w') as z:
        types = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))
        z.writestr('[Content_Types].xml',f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{types}</Types>')
        z.writestr('_rels/.rels',f'<Relationships xmlns="{pack}"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        workbook_items,relationships = [],[]
        for i,(name,widths,rows) in enumerate(sheets,1):
            workbook_items.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
            relationships.append(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>')
            columns = ''.join(f'<col min="{j}" max="{j}" width="{w}" customWidth="1"/>' for j,w in enumerate(widths,1))
            xml = ''.join(row_xml(row,number) for number,row in enumerate(rows,1))
            filt = f'<autoFilter ref="A1:{column(len(rows[0])-1)}{len(rows)}"/>' if len(rows)>1 else ''
            z.writestr(f'xl/worksheets/sheet{i}.xml',f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>{xml}</sheetData>{filt}</worksheet>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>{"".join(workbook_items)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="{pack}">{"".join(relationships)}<Relationship Id="styles" Type="{rel}/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml',f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF18375C"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf xfId="0" fontId="1" fillId="2" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    return output.getvalue()


def safe_workbook(data):
    from openpyxl import load_workbook
    require(0<len(data)<=5*1024*1024,422,'Книга должна быть не больше 5 МБ.')
    try:
        with ZipFile(BytesIO(data)) as z:
            require(len(z.infolist())<=150 and sum(i.file_size for i in z.infolist())<=20*1024*1024
                    and not any('vbaproject' in i.filename.lower() for i in z.infolist()),422,'Книга слишком велика или содержит макросы.')
        return load_workbook(BytesIO(data),read_only=True,data_only=False,keep_links=False)
    except (BadZipFile,KeyError,ValueError,OSError):
        require(False,422,'Файл не является поддерживаемой книгой XLSX.')


def package_template(tx,user,id):
    package = package_detail(tx,user,id)
    rows = [('Код субкомпонента','Код поля','Поле','Значение')]
    for entry in package['entries']:
        code = entry['code']
        fields = (entry.get('rule') or {}).get('fields',[])
        for field in fields:
            value = package['facts'].get(code,{}).get(field['key'])
            rows.append((code,field['key'],field['label'],float(value) if value is not None else None))
    metadata = [('Реквизит','Значение'),('Пакет',id),('Период',package['period']),('Контур',package['track']),
                ('Данные','Синтетические сведения')]
    return spreadsheet([('Ввод',[23,18,55,20],rows),('Реквизиты',[21,55],metadata)])


def package_import(tx,user,id,data,generation,apply):
    package = package_detail(tx,user,id)
    require(user['role']=='reporter',403,'Импорт доступен сотруднику ДГД или ЦТЛ.')
    require(package['status'] in ('draft','returned'),409,'Импорт возможен в черновик или возвращённые строки.')
    by_code = {e['code']:e for e in package['entries']}
    editable = {code for code,entry in by_code.items() if entry.get('rule')}
    if package['status']=='returned':
        editable &= package['notes'].keys()
    workbook = safe_workbook(data)
    incoming,issues = {},[]
    try:
        if 'Ввод' in workbook.sheetnames:
            if 'Реквизиты' in workbook.sheetnames:
                require(workbook['Реквизиты']['B2'].value==id,422,'Шаблон относится к другому пакету.')
            sheet = workbook['Ввод']
            require(sheet.max_row is None or sheet.max_row<=3000,422,'Книга содержит слишком много строк.')
            for index,row in enumerate(sheet.iter_rows(min_row=2,max_row=3001,max_col=4),2):
                code,key,_,cell = row
                if cell.value is None:
                    continue
                if code.value in by_code and code.value not in editable:
                    continue
                if cell.data_type=='f' or code.value not in editable or not isinstance(key.value,str):
                    issues.append(f'Строка {index}: формула или неизвестный код.')
                    continue
                fields = incoming.setdefault(code.value,{})
                if key.value in fields:
                    issues.append(f'Строка {index}: поле повторяется.')
                fields[key.value] = cell.value
        else:
            sheet_name = next((s for s in ('Расчеты KPI','Абай') if s in workbook.sheetnames),None)
            require(sheet_name,422,'Ожидается лист «Ввод» или знакомая расчётная форма.')
            require(package['track']=='source',422,'Историческая форма сопоставляется только с исходной методикой.')
            rows = workbook[sheet_name].iter_rows(min_row=3,max_row=90,min_col=8,max_col=13)
            for number,row in enumerate(rows,1):
                code = f'S{number:03}'
                key,actual = row[0],row[-1]
                if code not in editable or actual.value is None:
                    continue
                if key.value!=number or actual.data_type=='f':
                    issues.append(f'{sheet_name}!M{number+2}: формула или неверный номер.')
                    continue
                fields = (by_code[code].get('rule') or {}).get('fields',[])
                if len(fields)==1:
                    incoming[code]={fields[0]['key']:actual.value}
                else:
                    issues.append(f'{sheet_name}!M{number+2}: агрегат Excel не заменяет исходные поля.')
        valid = {}
        for code,values in incoming.items():
            try:
                valid[code] = input_values(by_code[code].get('rule'),values)
            except ValueError as error:
                issues.append(f'{code}: {error}')
    finally:
        workbook.close()
    if apply:
        require(not issues and valid,422,'Примените исправленную книгу без ошибок импорта.')
        combined = {code:dict(package['facts'].get(code,{}),**values) for code,values in valid.items()}
        update_package(tx,user,id,'save',{'generation':generation,'facts':combined})
    return {'ready':len(valid),'issues':issues,'applied':apply}


def report_workbook(tx,user,track,period,kind,region_id=None):
    data = dashboard(tx,user,track,period,kind)
    meta = [('Реквизит','Значение'),('Отчётный период',period),('Тип',kind),('Версия',data['method']),
            ('Контур','Демонстрационный' if track=='demo' else 'По исходным документам'),
            ('Данные','Синтетические сведения')]
    rank = [('Организация','Фактический KPI','Изменение','Статус','Подписано пакетов','Ожидается')]
    detail = [('№ индикатора','Индикатор','№ показателя','Показатель','Вес показателя','Код','Субкомпонент',
               'Вес субкомпонента','Плановое целевое значение','Фактическое значение','Базовый балл','Фактический балл','Балл показателя',
               'Балл индикатора','Ответственное подразделение','Организация','Статус')]
    for record in data['records']:
        if region_id and record['id']!=region_id:
            continue
        rank.append((record['name'],record['total'],record['delta'],STATUS[record['status']],record['received'],record['expected']))
        card = result_card(tx,user,track,period,kind,record['id'])
        result = card['official'] or card['working']
        groups = result['groups']
        for r in result['rows']:
            detail.append((r['indicator'],r['indicator_name'],r['metric'],r['metric_name'],r['metric_weight'],
                           r['code'],r['name'],r['weight'],r.get('target'),r['actual'],r['base'],r['points'],
                           groups['metric'].get(r['metric'],{}).get('points'),
                           groups['indicator'].get(r['indicator'],{}).get('points'),
                           r['department'],record['name'],STATUS[r['status']]))
    deputy = [('Заместитель','Организация','Должность','Направления','KPI','Изменение','Статус')]
    for d in data['deputies']:
        if not region_id or d['region_id']==region_id:
            deputy.append((d['name'],d['region'],d['title'],', '.join(d['blocks']),d['total'],d['delta'],STATUS[d['status']]))
    return spreadsheet([('Свод',[41,18,16,34,18,18],rank),
                        ('Расчет KPI',[15,50,16,50,18,12,64,18,24,18,16,16,16,16,26,39,38],detail),
                        ('Заместители',[36,38,39,49,16,16,37],deputy),('Реквизиты',[22,55],meta)])


def report_pdf(tx,user,track,period,kind,region_id=None,deputy_id=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    paths = [Path('C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    font = next((p for p in paths if p.is_file()),None)
    require(font,503,'Для PDF требуется шрифт Arial или DejaVu Sans.')
    if 'KPIrus' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('KPIrus',str(font)))
    data = dashboard(tx,user,track,period,kind)
    output = BytesIO()
    para = ParagraphStyle('kpi',fontName='KPIrus',fontSize=9,leading=13,textColor=colors.HexColor('#162c49'))
    heading = ParagraphStyle('title',parent=para,fontSize=19,leading=24)
    info = ParagraphStyle('info',parent=para,fontSize=10,textColor=colors.HexColor('#53708F'))
    document = SimpleDocTemplate(output,pagesize=A4,title=f'КPI КГД {period}',leftMargin=36,rightMargin=36)
    subject = 'Сводный отчёт' if not region_id else 'Карточка организации'
    if deputy_id:
        subject = 'Карточка заместителя'
    story = [Paragraph(f'КPI КГД · {subject}',heading),Spacer(1,8),
             Paragraph(escape(f'{period} · {data["method"]} · Синтетические сведения'),info),Spacer(1,18)]
    rows = [['Организация','KPI','Статус']]
    if deputy_id:
        selected = next((x for x in data['deputies'] if x['id']==deputy_id and x['region_id']==region_id),None)
        require(selected,404,'Заместитель не найден в периоде.')
        name = f'{selected["name"]}, {selected["region"]}'
        score = selected['total']
        rows.append([name,'—' if score is None else f'{score:.2f}',STATUS[selected['status']]])
        story.extend([Paragraph(escape(', '.join(selected['blocks'])),info),Spacer(1,9)])
    else:
        if region_id:
            require(any(r['id']==region_id for r in data['records']),404,'Организация не найдена в периоде.')
        for r in data['records']:
            if not region_id or r['id']==region_id:
                rows.append([r['name'],'—' if r['total'] is None else f'{r["total"]:.2f}',STATUS[r['status']]])
    table = Table([[Paragraph(escape(cell),para) for cell in row] for row in rows],colWidths=[254,56,196],repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E0EAF5')),
                               ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F5F8FC')]),
                               ('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),8),
                               ('TOPPADDING',(0,0),(-1,-1),7)]))
    document.build(story+[table])
    return output.getvalue()
