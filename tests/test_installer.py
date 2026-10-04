import hashlib,json,sqlite3,sys
from types import SimpleNamespace
import pytest
from scripts import install_release as installer


def fixture_release(tmp_path,monkeypatch):
    source=tmp_path/'release';source.mkdir()
    (source/'bot.py').write_text('new application\n')
    manifest={'version':'3.0.0','files':{'bot.py':hashlib.sha256((source/'bot.py').read_bytes()).hexdigest()}}
    (source/'release-manifest.json').write_text(json.dumps(manifest))
    app=tmp_path/'application';app.mkdir()
    (app/'.env').write_text('DISCORD_TOKEN=test-placeholder\nDATABASE_PATH=bot.db\n')
    (app/'bot.py').write_text('old application\n')
    conn=sqlite3.connect(app/'bot.db');conn.execute('CREATE TABLE money(amount REAL)');conn.execute('INSERT INTO money VALUES (10)');conn.commit();conn.close()
    monkeypatch.setattr(installer,'SOURCE',source)
    return source,app,manifest


def test_manifest_tamper_and_path_escape_rejected(tmp_path,monkeypatch):
    source,app,manifest=fixture_release(tmp_path,monkeypatch)
    assert installer.verify_source()['version']=='3.0.0'
    (source/'bot.py').write_text('tampered\n')
    with pytest.raises(RuntimeError,match='checksum'):
        installer.verify_source()
    manifest['files']={'../outside.py':'bad'}
    (source/'release-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError,match='forbidden'):
        installer.verify_source()
    manifest['files']={'.env':'bad'}
    (source/'release-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError,match='forbidden'):
        installer.verify_source()
    manifest['files']={'sub/.env':'bad'}
    (source/'release-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError,match='forbidden'):
        installer.verify_source()


def test_dry_run_leaves_database_env_and_code_untouched(tmp_path,monkeypatch):
    source,app,manifest=fixture_release(tmp_path,monkeypatch)
    before={p.name:p.read_bytes() for p in app.iterdir()}
    monkeypatch.setattr(sys,'argv',['install_release.py','--app-dir',str(app),'--dry-run'])
    monkeypatch.setattr(installer,'run',lambda *a,**k:pytest.fail('Dry run must not run installation commands.'))
    installer.main()
    assert {p.name:p.read_bytes() for p in app.iterdir()}==before


def install_simulation(tmp_path,monkeypatch,*,failure):
    source,app,manifest=fixture_release(tmp_path,monkeypatch)
    units=tmp_path/'units';units.mkdir();(units/'melee-zone.service').write_text('old service\n')
    monkeypatch.setattr(installer,'UNIT_DIR',units)
    monkeypatch.setattr(installer,'env_value',lambda python,key,default:str(app/'bot.db') if key=='DATABASE_PATH' else default)
    monkeypatch.setattr(installer,'stop_legacy_watchdogs',lambda path:None)
    monkeypatch.setattr(installer.os,'geteuid',lambda:0)
    monkeypatch.setattr(installer.os,'chown',lambda *args:None)
    monkeypatch.setattr(installer.subprocess,'check_output',lambda *a,**k:'root\n')
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys,'argv',['install_release.py','--app-dir',str(app)])
    calls=[]
    def run(command,**kwargs):
        args=[str(v) for v in command];calls.append(args)
        if failure=='preflight' and any(v.endswith('preflight.py') for v in args):
            raise RuntimeError('Injected migration failure')
        if failure=='start' and args[1:2]==['start']:
            conn=sqlite3.connect(app/'bot.db');conn.execute('INSERT INTO money VALUES (4)');conn.commit();conn.close()
            raise RuntimeError('Injected partial service-start failure')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer,'run',run)
    return app,units,calls


def test_preflight_failure_never_stops_existing_service(tmp_path,monkeypatch):
    app,units,calls=install_simulation(tmp_path,monkeypatch,failure='preflight')
    env=(app/'.env').read_bytes()
    with pytest.raises(RuntimeError,match='migration'):
        installer.main()
    assert not any(c[1:2]==['stop'] for c in calls)
    assert (app/'bot.py').read_text()=='old application\n'
    assert (app/'.env').read_bytes()==env


def test_partial_start_failure_rollback_preserves_new_mc(tmp_path,monkeypatch):
    app,units,calls=install_simulation(tmp_path,monkeypatch,failure='start')
    env=(app/'.env').read_bytes()
    with pytest.raises(RuntimeError,match='service-start'):
        installer.main()
    assert (app/'bot.py').read_text()=='old application\n'
    assert (app/'.env').read_bytes()==env
    conn=sqlite3.connect(app/'bot.db')
    assert conn.execute('SELECT SUM(amount) FROM money').fetchone()[0]==14
    conn.close()
    assert (units/'melee-zone.service').read_text()=='old service\n'
