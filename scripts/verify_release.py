#!/usr/bin/env python3
"""Read-only source/archive integrity checks; never opens production state."""
import argparse
import hashlib
import io
import json
import stat
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def verify_manifest(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'release-manifest.json').read_text())
    required = {'bot.py', 'requirements.txt', 'database.py', 'access_policy.py', 'governance_db.py',
                'config_service.py', 'cogs/governance.py', 'README.md', 'install.sh'}
    if not required <= set(manifest['files']):
        raise ValueError('The release is missing required files.')
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or not name:
            raise ValueError('Unsafe manifest path.')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Unsafe release file.')
        if path.name == '.env' or path.suffix in {'.db', '.log'} or path.name.endswith(('.db-wal', '.db-shm')):
            raise ValueError('Private production state in release.')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {name}')
        if path.suffix in {'.xlsx', '.docx'}:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip():
                    raise ValueError(f'Invalid document archive: {name}')
    return manifest


def verify_archive(path, manifest):
    path = Path(path)
    content = {}
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            if archive.testzip():raise ValueError('Corrupt ZIP archive.')
            for item in archive.infolist():
                if item.is_dir():continue
                if stat.S_ISLNK(item.external_attr >> 16):raise ValueError('Release ZIP contains a symlink.')
                relative = PurePosixPath(item.filename)
                if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive path.')
                if item.filename in content:raise ValueError('Duplicate archive path.')
                if item.file_size > 100 * 1024 * 1024:raise ValueError('Oversized archive entry.')
                content[item.filename] = archive.read(item)
    else:
        with tarfile.open(path, 'r:gz') as archive:
            for item in archive.getmembers():
                if item.isdir():continue
                if not item.isfile():raise ValueError('Release tar contains a non-file.')
                if item.size > 100 * 1024 * 1024:raise ValueError('Oversized archive entry.')
                name = str(PurePosixPath(item.name).relative_to(f"melee-zone-v{manifest['version'].rsplit('.',1)[0]}"))
                if name in content:raise ValueError('Duplicate archive path.')
                content[name] = archive.extractfile(item).read()
    if set(content) != set(manifest['files']) | {'release-manifest.json'}:
        raise ValueError('Archive file list differs from the source manifest.')
    if json.loads(content['release-manifest.json']) != manifest:
        raise ValueError('Archive manifest differs from source.')
    for name, expected in manifest['files'].items():
        if hashlib.sha256(content[name]).hexdigest() != expected:
            raise ValueError(f'Archive checksum mismatch: {name}')
    return {'archive': path.name, 'files': len(content), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--archive', type=Path, action='append', default=[])
    args = parser.parse_args()
    manifest = verify_manifest(args.source)
    results = [verify_archive(path, manifest) for path in args.archive]
    print(json.dumps({'version': manifest['version'], 'source_files': len(manifest['files']), 'integrity': 'passed', 'archives': results}))


if __name__ == '__main__':main()
