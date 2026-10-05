"""Populate the checked-in Artifact-authored workbook; no Office runtime needed."""
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from config import Config
from runtime_utils import parse_time
from xlsx_report import TAG, cell, column_name

ASSETS = Path(__file__).parent / 'assets'
TEMPLATE = ASSETS / 'review-support-template.xlsx'
SCHEMA = ASSETS / 'review-report-columns.json'


def make_cell(address, value, style=None, *, kind=None, formula=None, cached=None):
    if isinstance(value, bool):
        value = int(value)
    result = cell(address, value, style, date=kind == 'date', formula=formula, cached=cached)
    if formula and cached is None:
        result.set('t', 'str')
        result.find(TAG('v')).text = ''
    return result


def replace(root, address, value=None, *, formula=None, cached=None, kind=None):
    data = root.find(TAG('sheetData'))
    number = int(re.search(r'\d+$', address)[0])
    row = next((r for r in data if int(r.attrib['r']) == number), None)
    if row is None:
        row = ET.SubElement(data, TAG('row'), {'r': str(number)})
    old = next((c for c in row if c.attrib['r'] == address), None)
    style = old.get('s') if old is not None else None
    if old is not None:
        row.remove(old)
    row.append(make_cell(address, value, style, kind=kind, formula=formula, cached=cached))


def normalize(root, end_col, end_row, *, filtering=False):
    data = root.find(TAG('sheetData'))
    data[:] = sorted(data, key=lambda r: int(r.attrib['r']))
    def key(c):
        result = 0
        for letter in re.sub(r'\d+', '', c.attrib['r']):
            result = result * 26 + ord(letter) - 64
        return result
    for row in data:
        row[:] = sorted(row, key=key)
    dimension = root.find(TAG('dimension'))
    if dimension is not None:
        dimension.set('ref', f'A1:{end_col}{end_row}')
    if filtering:
        element = root.find(TAG('autoFilter'))
        if element is None:
            element = ET.Element(TAG('autoFilter'))
            following = (TAG('mergeCells'), TAG('conditionalFormatting'), TAG('dataValidations'), TAG('pageMargins'), TAG('pageSetup'))
            index = next((i for i, child in enumerate(root) if child.tag in following), len(root))
            root.insert(index, element)
        element.set('ref', f'A5:{end_col}{end_row}')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def post_reward(post, cfg, *, scenario):
    needed = Config.get_min_reviews(cfg) if scenario else int(post.get('required_reviews') or Config.get_min_reviews(cfg))
    score = post['observed_mean_score']
    if post['reviews_before_cutoff'] < needed or score is None:
        return 0, 0
    return (Config.calculate_mc_from_score(score, cfg),
            Config.get_showcase_reward(cfg) if score >= Config.get_showcase_threshold(cfg) else 0)


def populate_detail(xml, name, columns, rows, payload, metadata):
    root = ET.fromstring(xml)
    data = root.find(TAG('sheetData'))
    sample = next(r for r in data if r.get('r') == '6')
    styles = {re.sub(r'\d+', '', c.get('r')): c.get('s') for c in sample}
    for row in list(data):
        if int(row.get('r')) >= 6:
            data.remove(row)
    replace(root, 'A3', metadata)
    for number, record in enumerate(rows or [{}], 6):
        height = 32
        if name in ('Reviews', 'Oversight'):
            text = str(record.get('feedback', record.get('summary')) or '')
            lines = sum(max(1, (len(line)+65)//66) for line in text.split('\n'))
            height = min(409, max(78, 16*lines+14))
        row = ET.SubElement(data, TAG('row'), {'r': str(number), 'ht': str(height), 'customHeight': '1'})
        for index, (_, key, kind) in enumerate(columns, 1):
            letter, value = column_name(index), record.get(key)
            formula, cached = None, None
            if name == 'Members' and letter == 'N' and record:
                formula, cached = f'SUM(K{number}:M{number})', record['total_mc']
            elif name == 'Reviewers' and letter == 'I' and record:
                formula, cached = f'IF(G{number}=0,"",H{number}/G{number})', record['opportunity_completion_rate']
            elif name == 'Posts' and letter in 'IJKL' and record:
                current = letter in 'KL'
                setting = 'B' if current else 'C'
                required = f'E{number}' if current else "'Calculator'!$C$8"
                regular, gold = post_reward(record, payload['baseline_estimate' if current else 'estimate']['config'], scenario=not current)
                if letter in 'IK':
                    formula = (f"IF(F{number}<{required},0,IF(G{number}>=8,'Calculator'!${setting}$12,"
                               f"IF(G{number}>=6,'Calculator'!${setting}$11,IF(G{number}>=4,'Calculator'!${setting}$10,0))))")
                    cached = regular
                else:
                    formula = f"IF(F{number}<{required},0,IF(G{number}>='Calculator'!${setting}$17,'Calculator'!${setting}$16,0))"
                    cached = gold
            row.append(make_cell(f'{letter}{number}', value, styles.get(letter), kind=kind, formula=formula, cached=cached))
    return normalize(root, column_name(len(columns)), max(6, len(rows) + 5), filtering=True)


SETTINGS = ['max_reviews_per_week', 'max_submits_per_week', 'min_reviews', 'total_review_days',
            'mc_score_low', 'mc_score_medium', 'mc_score_high', 'mc_review_reward', 'mc_comment_bonus',
            'mc_submit_completion', 'mc_showcase_reward', 'showcase_threshold']
DEFAULTS = [7, 5, 5, 7, 1, 3, 5, 2, 1, 2, 3, 8]
METRICS = ['posts', 'reviews', 'current_reviewers', 'current_members', 'active_reviewers', 'mature_opportunities',
           'completed_mature_opportunities', 'mature_completion_rate', 'theoretical_reviews_per_week',
           'observed_capacity_per_week', 'demand_reviews_per_week', 'p90_response_hours', 'current_reviewer_slots',
           'current_member_slots', 'regular_mc_paid', 'golden_mc_paid', 'assignment_mc_paid',
           'moderator_evaluations', 'full_evidence_evaluations']


def populate_calculator(xml, payload, metadata):
    root = ET.fromstring(xml)
    replace(root, 'A3', metadata)
    summary = payload['summary']
    weeks = (parse_time(payload['end']) - parse_time(payload['start'])).total_seconds() / 604800
    rate = summary['current_role_completion_rate']
    for column, estimate in [('B', payload['baseline_estimate']), ('C', payload['estimate'])]:
        cfg = estimate['config']
        for row, key, default in zip(range(6, 18), SETTINGS, DEFAULTS):
            replace(root, f'{column}{row}', Config.g(cfg, key, default))
        for row, value in zip(range(18, 22), [summary['current_reviewers'], summary['active_reviewers'], rate, weeks]):
            replace(root, f'{column}{row}', value)
        measured = summary['active_reviewers'] * Config.get_max_reviews(cfg) * rate if rate is not None else None
        demand = len(payload['posts']) / weeks * Config.get_min_reviews(cfg)
        results = [estimate[k] for k in ('score_regular_mc', 'review_goal_mc', 'comment_bonus_mc', 'submission_goal_mc',
                                         'estimated_regular_mc', 'showcase_golden_mc', 'estimated_total_mc')]
        results += [demand, summary['current_reviewers'] * Config.get_max_reviews(cfg), measured,
                    max(0, demand - measured) if measured is not None else None]
        for row, value in zip(range(24, 35), results):
            old = root.find(f".//{TAG('c')}[@r='{column}{row}']")
            formula = old.find(TAG('f')).text
            end = max(6, len(payload['posts' if 'Posts' in formula else 'weekly_goals']) + 5)
            formula = re.sub(r'(\$[A-Z]+\$6:\$[A-Z]+\$)6\b', lambda m: m[1] + str(end), formula)
            replace(root, f'{column}{row}', formula=formula, cached=value)
    data = root.find(TAG('sheetData'))
    sample = next(r for r in data if r.get('r') == '6')
    styles = {re.sub(r'\d+', '', c.get('r')): c.get('s') for c in sample}
    for row in data:
        if int(row.get('r')) >= 6:
            for c in list(row):
                if re.sub(r'\d+', '', c.get('r')) in 'FGHIJ':
                    row.remove(c)
    for number, goal in enumerate(payload['weekly_goals'] or [{}], 6):
        for column, key in zip('FGHIJ', ('discord_id', 'week_id', 'completed_assignments', 'all_comment_links', 'submitted_posts')):
            replace(root, f'{column}{number}', goal.get(key))
            element = root.find(f".//{TAG('c')}[@r='{column}{number}']")
            if styles.get(column):
                element.set('s', styles[column])
    return normalize(root, 'J', max(37, len(payload['weekly_goals']) + 5))


def populate_overview(xml, payload, metadata):
    root = ET.fromstring(xml)
    replace(root, 'A3', metadata)
    for row, key in enumerate(METRICS, 6):
        replace(root, f'B{row}', payload['summary'][key])
    replace(root, 'C6', payload['summary']['previous_posts'])
    replace(root, 'C7', payload['summary']['previous_reviews'])
    replace(root, 'A29', f"Balances at capture. Complete role inventory: {payload['summary'].get('roster_refreshed_at') or 'unknown'}.")
    for number, recommendation in enumerate(payload['recommendations'], 33):
        for column, key in zip('ABCD', ('setting', 'current', 'suggested', 'reason')):
            replace(root, f'{column}{number}', recommendation[key])
    return normalize(root, 'D', 44)


def export_support_report(payload, output, template=TEMPLATE):
    """Atomic private file. External names/feedback are strings, never formulas."""
    output = Path(output)
    schema = json.loads(SCHEMA.read_text())
    metadata = f"UTC: {payload['start'][:16]} to {payload['end'][:16]} (end exclusive). Capture: {payload['captured_at'][:16]}."
    names = ['Overview', 'Calculator', *schema]
    datasets = {'Members': 'members', 'Reviewers': 'reviewers', 'Moderators': 'moderators',
                'Posts': 'posts', 'Reviews': 'reviews', 'Oversight': 'evaluations'}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='review-export-', suffix='.xlsx', dir=output.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(template) as source, zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                raw = source.read(item.filename)
                match = re.fullmatch(r'xl/worksheets/sheet([1-8])\.xml', item.filename)
                if match:
                    name = names[int(match[1]) - 1]
                    if name == 'Overview':
                        raw = populate_overview(raw, payload, metadata)
                    elif name == 'Calculator':
                        raw = populate_calculator(raw, payload, metadata)
                    else:
                        raw = populate_detail(raw, name, schema[name], payload[datasets[name]], payload, metadata)
                elif item.filename == 'xl/workbook.xml':
                    root = ET.fromstring(raw)
                    calc = root.find(TAG('calcPr'))
                    if calc is None:
                        calc = ET.SubElement(root, TAG('calcPr'))
                    calc.attrib.update(calcMode='auto', fullCalcOnLoad='1', forceFullCalc='1')
                    raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                target.writestr(item, raw)
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output
