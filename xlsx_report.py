"""Fill an Artifact Tool-authored XLSX template without extra VPS dependencies."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
from runtime_utils import parse_time

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL='http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('',NS)
ET.register_namespace('r',REL)
TAG=lambda name:f'{{{NS}}}{name}'
TEMPLATE=Path(__file__).parent/'assets'/'role-report-template.xlsx'


def column_name(index):
    text=''
    while index:
        index,remainder=divmod(index-1,26)
        text=chr(65+remainder)+text
    return text


def clean_text(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(value))[:32700]


def date_serial(value):
    dt=parse_time(value)
    return (dt-datetime(1899,12,30,tzinfo=timezone.utc)).total_seconds()/86400


def cell(address,value,style=None,*,date=False,formula=None,cached=None):
    result=ET.Element(TAG('c'),{'r':address})
    if style is not None:
        result.set('s',style)
    if formula:
        ET.SubElement(result,TAG('f')).text=formula
        ET.SubElement(result,TAG('v')).text=str(cached)
    elif value is None or value=='':
        pass
    elif date:
        ET.SubElement(result,TAG('v')).text=str(date_serial(value))
    elif isinstance(value,(int,float)) and not isinstance(value,bool):
        ET.SubElement(result,TAG('v')).text=str(value)
    else:
        result.set('t','inlineStr')
        text=ET.SubElement(ET.SubElement(result,TAG('is')),TAG('t'))
        text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
        text.text=clean_text(value)
    return result


def fill_sheet(xml,rows,*,width,date_columns=(),total_column=None,metadata='',link_column=None):
    root=ET.fromstring(xml)
    data=root.find(TAG('sheetData'))
    sample=next((r for r in data if r.attrib.get('r')=='6'),None)
    styles={re.sub(r'\d+','',c.attrib['r']):c.attrib.get('s') for c in sample} if sample is not None else {}
    for row in list(data):
        if int(row.attrib['r'])>=6:
            data.remove(row)
        elif row.attrib['r']=='2':
            for c in list(row):
                if c.attrib.get('r')=='A2':
                    style=c.attrib.get('s');row.remove(c);row.insert(0,cell('A2',metadata,style))
    if not rows:
        rows=[['No records found']+[None]*(width-1)]
    for row_number,values in enumerate(rows,6):
        row=ET.SubElement(data,TAG('row'),{'r':str(row_number),'ht':'42' if width==6 else '28','customHeight':'1'})
        for index,value in enumerate(values,1):
            column=column_name(index)
            formula=cached=None
            if total_column==index and values[0]!='No records found':
                formula=f'SUM(K{row_number}:M{row_number})';cached=sum(float(n or 0) for n in values[10:13])
            row.append(cell(f'{column}{row_number}',value,styles.get(column),date=index in date_columns,formula=formula,cached=cached))
    end=max(6,5+len(rows))
    dimension=root.find(TAG('dimension'))
    if dimension is not None:
        dimension.set('ref',f'A1:{column_name(width)}{end}')
    auto_filter=root.find(TAG('autoFilter'))
    if auto_filter is None:
        auto_filter=ET.Element(TAG('autoFilter'))
        # autoFilter precedes mergeCells in SpreadsheetML order.
        index=next((i for i,c in enumerate(root) if c.tag in (TAG('mergeCells'),TAG('pageMargins'),TAG('pageSetup'))),len(root))
        root.insert(index,auto_filter)
    auto_filter.set('ref',f'A5:{column_name(width)}{end}')
    if link_column:
        links=[]
        for number,values in enumerate(rows,6):
            value=values[link_column-1]
            if value and re.fullmatch(r'https://discord\.com/channels/\d+/\d+(?:/\d+)?',str(value)):
                links.append((number,str(value)))
        if links:
            element=ET.Element(TAG('hyperlinks'))
            for number,_ in links:
                ET.SubElement(element,TAG('hyperlink'),{'ref':f'{column_name(link_column)}{number}',f'{{{REL}}}id':f'link{number}'})
            index=next((i for i,c in enumerate(root) if c.tag in (TAG('pageMargins'),TAG('pageSetup'))),len(root))
            root.insert(index,element)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def export_role_report(payload,output,template=TEMPLATE):
    output=Path(output)
    metadata=f"Role: {payload['role_name']} | State: {payload['state']} | Window: {payload.get('cutoff') or 'all accessible history'} to {payload['upper_at']} | Scanned: {payload['scanned']:,}"
    with zipfile.ZipFile(template) as source,zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            raw=source.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':
                raw=fill_sheet(raw,payload['members'],width=16,date_columns=(5,6,8),total_column=14,metadata=metadata,link_column=16)
            elif item.filename=='xl/worksheets/sheet2.xml':
                raw=fill_sheet(raw,payload['recent'],width=6,date_columns=(3,),metadata='Last five indexed, retained messages per member. Deleted message text is cleared.',link_column=6)
            elif item.filename=='xl/worksheets/sheet3.xml':
                raw=fill_sheet(raw,payload['coverage'],width=5,metadata='Complete = requested history exhausted. Pending or skipped = partial coverage. Counts exclude messages deleted before indexing.')
            elif item.filename=='xl/worksheets/sheet4.xml':
                raw=fill_sheet(raw,payload.get('events',[]),width=6,date_columns=(3,),metadata='Five recent reactions or bot actions observed while tracking. Historical reactions have no retrievable creation timestamp.',link_column=6)
            target.writestr(item,raw)
        for sheet,rows,column in [(1,payload['members'],16),(2,payload['recent'],6),(4,payload.get('events',[]),6)]:
            relationships=ET.Element(f'{{{PACKAGE_REL}}}Relationships')
            for number,values in enumerate(rows,6):
                value=values[column-1]
                if value and re.fullmatch(r'https://discord\.com/channels/\d+/\d+(?:/\d+)?',str(value)):
                    ET.SubElement(relationships,f'{{{PACKAGE_REL}}}Relationship',{'Id':f'link{number}','Type':REL+'/hyperlink','Target':str(value),'TargetMode':'External'})
            if len(relationships):
                target.writestr(f'xl/worksheets/_rels/sheet{sheet}.xml.rels',ET.tostring(relationships,encoding='utf-8',xml_declaration=True))
    return output
