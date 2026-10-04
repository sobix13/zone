#!/usr/bin/env python3
"""Build a standalone moderator reference from the checked-in Markdown sources."""
import argparse,html
from pathlib import Path
import markdown

ROOT=Path(__file__).resolve().parents[1]
PAGES=['MODERATOR_MANUAL.md','USER_GUIDE.md','OPERATIONS.md','ROOT_CAUSES.md','COMMANDS.md','LIVE_ACCEPTANCE.md','ROADMAP.md']
STYLE='''
:root{--ink:#29343b;--brand:#79323d;--muted:#647179;--paper:#fff;--line:#e7dddd}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:#f8f5f5;font:16px/1.65 system-ui,-apple-system,Segoe UI,Arial,sans-serif}
header{background:var(--brand);color:white;padding:30px 40px}header h1{font-size:29px;line-height:1.25;margin:0 0 10px}header p{margin:0;color:#f5e8ea}
.layout{max-width:1490px;margin:auto;display:grid;grid-template-columns:280px minmax(0,1fr);gap:26px;padding:28px 30px}
nav{position:sticky;top:18px;height:calc(100vh - 36px);overflow:auto;font-size:13px;padding:12px 15px;background:#fff;border:1px solid var(--line);border-radius:10px}
nav ul{list-style:none;padding-left:10px}nav>ul{padding-left:0}nav a{color:var(--brand);text-decoration:none}nav li{margin:6px 0}
main{background:var(--paper);padding:28px 42px;border:1px solid var(--line);border-radius:10px;min-width:0}
h1{font-size:28px;line-height:1.25;color:var(--brand);margin:48px 0 16px;border-top:3px solid var(--line);padding-top:26px}main>h1:first-child{margin-top:0;border:0;padding:0}
h2{font-size:22px;line-height:1.35;color:var(--brand);margin:34px 0 12px}h3{font-size:18px;line-height:1.35;margin:25px 0 9px}
p{margin:10px 0 17px}a{color:var(--brand);overflow-wrap:anywhere}strong{font-weight:650}code{font-size:.88em;background:#f5f0f1;padding:2px 5px;border-radius:3px}
pre{background:#f5f0f1;border-left:3px solid var(--brand);padding:15px;overflow:auto;border-radius:3px;white-space:pre-wrap;overflow-wrap:anywhere}pre code{padding:0;background:transparent}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.5;margin:18px 0 24px}th{text-align:left;background:#f2e8ea;color:var(--brand)}th,td{padding:10px 12px;border:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
li{margin:6px 0}hr{border:0;border-top:1px solid var(--line);margin:30px 0}footer{text-align:center;color:var(--muted);font-size:13px;padding:20px}
@media(max-width:900px){.layout{display:block;padding:15px}nav{position:static;height:auto;max-height:280px;margin-bottom:18px}main{padding:22px}header{padding:25px}table{display:block;overflow-x:auto}}
@media print{@page{size:A4;margin:15mm}body{background:white;font-size:10pt}header{background:white;color:var(--brand);padding:0}header p{color:var(--muted)}.layout{display:block;padding:0}nav{display:none}main{padding:0;border:0;border-radius:0}h1{break-before:page}main>h1:first-child{break-before:auto}h1,h2,h3{break-after:avoid}thead{display:table-header-group}tr{break-inside:avoid}pre{font-size:9pt}footer{display:none}}
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'docs'/'Melee-Zone-Moderator-Manual.html')
    args=parser.parse_args()
    text='\n\n---\n\n'.join((ROOT/'docs'/name).read_text() for name in PAGES)
    renderer=markdown.Markdown(extensions=['tables','fenced_code','toc'],extension_configs={'toc':{'toc_depth':'1-2'}})
    body=renderer.convert(text)
    result=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Melee Zone V3 moderator reference</title><style>{STYLE}</style></head><body><header><h1>Melee Zone V3</h1><p>Moderator reference, member training, operations and recovery | Version 3.0.0</p></header><div class="layout"><nav aria-label="Contents"><strong>Contents</strong>{renderer.toc}</nav><main>{body}</main></div><footer>Melee Zone 3.0.0 | Use the current server configuration for amounts, roles and deadlines. Print this page to retain an offline reference.</footer></body></html>'''
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(result)
    print('Standalone reference built:',args.output.name)


if __name__=='__main__':
    main()
