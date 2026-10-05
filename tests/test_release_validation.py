import hashlib
import json
from pathlib import Path
import tarfile
import zipfile
import pytest
from scripts.verify_release import verify_manifest, verify_archive


def release_fixture(tmp_path):
    root=tmp_path/'release';root.mkdir()
    required=['bot.py','requirements.txt','database.py','access_policy.py','governance_db.py',
              'config_service.py','cogs/governance.py','README.md','install.sh']
    files={}
    for name in required:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Synthetic release fixture\n')
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'version':'3.2.0','files':files}
    (root/'release-manifest.json').write_text(json.dumps(manifest))
    return root,manifest


def test_source_and_both_archives_exact_manifest(tmp_path):
    root,manifest=release_fixture(tmp_path)
    assert verify_manifest(root)==manifest
    zip_path=tmp_path/'release.zip';tar_path=tmp_path/'release.tar.gz'
    with zipfile.ZipFile(zip_path,'w') as archive:
        for name in [*manifest['files'],'release-manifest.json']:archive.write(root/name,name)
    with tarfile.open(tar_path,'w:gz') as archive:
        for name in [*manifest['files'],'release-manifest.json']:archive.add(root/name,'melee-zone-v3.2/'+name)
    assert verify_archive(zip_path,manifest)['files']==10
    assert verify_archive(tar_path,manifest)['files']==10


@pytest.mark.parametrize('fault',['tamper','missing','unsafe','private','symlink'])
def test_release_corruption_and_private_paths_refused(tmp_path,fault):
    root,manifest=release_fixture(tmp_path)
    if fault=='tamper':(root/'bot.py').write_text('Tampered')
    elif fault=='missing':del manifest['files']['config_service.py']
    elif fault=='unsafe':manifest['files']['../outside']='bad'
    elif fault=='private':manifest['files']['.env']='bad'
    else:
        original=root/'bot.py';original.unlink();original.symlink_to(root/'database.py')
    (root/'release-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):verify_manifest(root)


def test_duplicate_and_missing_zip_entries_refused(tmp_path):
    root,manifest=release_fixture(tmp_path)
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:archive.writestr('bot.py','Missing all other files')
    with pytest.raises(ValueError):verify_archive(path,manifest)


def test_approved_handbooks_preserved_byte_for_byte():
    docs=Path(__file__).resolve().parents[1]/'docs'
    expected={'Melee-Zone-Moderator-Manual.html':'3d82a84c722a13a33d4994f40575c7a5ad24ca21dfec35699a2661d4bd5e1bf1',
              'Melee-Zone-Moderator-Handbook.docx':'ea675996416b8d4a125447d026ef192a74382fab841dbec7558f1c249beb8488'}
    for name,digest in expected.items():assert hashlib.sha256((docs/name).read_bytes()).hexdigest()==digest
    html=(docs/'Melee-Zone-Moderator-Manual.html').read_text()
    assert 'github.com' not in html.lower() and 'roadmap' not in html.lower()
    with zipfile.ZipFile(docs/'Melee-Zone-Moderator-Handbook.docx') as archive:
        assert archive.testzip() is None and 'word/document.xml' in archive.namelist()
