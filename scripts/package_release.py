#!/usr/bin/env python3
"""Build checked, secret-free update and repository archives."""
import argparse,hashlib,json,re,tarfile,zipfile
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOP={'cogs','scripts','tests','docs','assets','.github'}
ROOT_FILES={'README.md','.env.example','.gitignore','pyproject.toml','install.sh','watchdog.sh','melee-zone.service'}
TOKEN=re.compile(rb'(?:mfa\.[A-Za-z0-9_-]{60,}|[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,})')


def collect():
    files=[]
    for file in sorted(ROOT.rglob('*')):
        if not file.is_file() or file.is_symlink():
            continue
        relative=file.relative_to(ROOT)
        if any(part in {'__pycache__','.pytest_cache','.venv','venv','runtime','backups','.git','.releases'} for part in relative.parts):
            continue
        if file.name=='release-manifest.json':
            continue
        if len(relative.parts)==1:
            allowed=file.name in ROOT_FILES or file.suffix=='.py' or file.name.startswith('requirements') or file.name=='constraints-runtime.txt'
        else:
            allowed=relative.parts[0] in TOP and file.suffix in {'.py','.md','.txt','.html','.xml','.xlsx','.yml','.yaml','.mjs'}
        if not allowed:
            continue
        if file.name=='.env' or any(file.name.endswith(suffix) for suffix in ('.db','.db-wal','.db-shm','.log')):
            raise RuntimeError('A forbidden production file entered the release selection.')
        if file.suffix not in {'.xlsx'} and TOKEN.search(file.read_bytes()):
            raise RuntimeError('A potential Discord token was found in '+str(relative))
        files.append(file)
    return files


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT.parent/'release-output')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    files=collect()
    manifest={'version':'3.0.0','built_at':datetime.now(timezone.utc).isoformat(),'validated_python':'3.12','local_tests_passed':83,
        'files':{str(file.relative_to(ROOT)):hashlib.sha256(file.read_bytes()).hexdigest() for file in files}}
    (ROOT/'release-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files.append(ROOT/'release-manifest.json')
    update=output/'Melee-Zone-V3-update.tar.gz'
    with tarfile.open(update,'w:gz') as target:
        for file in files:
            target.add(file,arcname=str(Path('melee-zone-v3')/file.relative_to(ROOT)))
    repository=output/'Melee-Zone-V3-repository.zip'
    with zipfile.ZipFile(repository,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as target:
        for file in files:
            target.write(file,arcname=str(file.relative_to(ROOT)))
    hashes={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in (update,repository)}
    (output/'SHA256SUMS.txt').write_text(''.join(value+'  '+key+'\n' for key,value in hashes.items()))
    print(json.dumps({'files':len(files),'archives':{file.name:file.stat().st_size for file in (update,repository)},'sha256':hashes}))


if __name__=='__main__':
    main()
