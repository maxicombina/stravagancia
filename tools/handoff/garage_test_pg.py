"""Disposable local test database: synthetic credentials, no production settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO=Path('/Users/maxicombina/src/learning/django/stravagancia')
PG=Path('/opt/homebrew/opt/postgresql@18/bin')
PYTHON=Path(os.environ.get('GARAGE_TEST_PYTHON', REPO/'.venv/bin/python'))  # override when .venv belongs to the Docker image
STATE=Path('/private/tmp/garage018_pg_state.json')
BASE={k:v for k,v in os.environ.items() if k in {'PATH','HOME','USER','LOGNAME','TMPDIR','LANG'}}
BASE['LC_ALL']='C'
ENV=dict(BASE,TEST_DB_HOST='127.0.0.1',TEST_DB_PORT='55434',TEST_DB_NAME='stravagancia_test_018',
         TEST_DB_USER='stravagancia_test',TEST_DB_PASSWORD='stravagancia_test',
         DATABASE_URL='postgresql://synthetic:fake@production.invalid/production',
         DB_HOST='production.invalid',PGHOSTADDR='203.0.113.1',STRAVA_CLIENT_SECRET='synthetic-production-secret')

def run(args,env=None):
    return subprocess.run([str(x) for x in args],cwd=REPO,env=env or BASE,check=True,timeout=600)

def psql(sql):
    return run([PG/'psql','-X','-h','127.0.0.1','-p','55434','-U','garage_test_admin','-d','postgres',
                '-v','ON_ERROR_STOP=1','-c',sql],dict(BASE,PGPASSWORD='stravagancia_test'))

if sys.argv[1]=='start':
    if STATE.exists(): raise SystemExit('Inspect existing state before reusing.')
    root=Path(tempfile.mkdtemp(prefix='garage018-validation-',dir='/private/tmp'))
    password=root/'synthetic-password';password.write_text('stravagancia_test\n');password.chmod(0o600)
    STATE.write_text(json.dumps({'root':str(root),'port':55434})+'\n')
    run([PG/'initdb','-D',root/'data','-U','garage_test_admin','--auth-local=trust','--auth-host=scram-sha-256',
         '--pwfile='+str(password),'--encoding=UTF8','--locale=C'])
    run([PG/'pg_ctl','-D',root/'data','-l',root/'postgres.log','-w','-o',
         '-h 127.0.0.1 -p 55434 -k '+str(root)+' -c max_connections=30 -c shared_buffers=32MB','start'])
    psql("CREATE ROLE stravagancia_test LOGIN CREATEDB PASSWORD 'stravagancia_test'")
    psql('CREATE DATABASE stravagancia_test_018 OWNER stravagancia_test')
    psql('SELECT version(), inet_server_addr(), inet_server_port()')
    password.unlink();print('VALIDATION_DIR='+str(root),flush=True)
elif sys.argv[1]=='run':
    run([PYTHON,*sys.argv[2:]],ENV)
elif sys.argv[1]=='coverage':
    root=Path(json.loads(STATE.read_text())['root']);report=root/'full-020';report.mkdir(exist_ok=True)
    package=Path('/Users/maxicombina/.cache/uv/archive-v0/IGYhTYoYbsSw2laj')
    assert (package/'coverage/__main__.py').exists()
    (report/'sitecustomize.py').write_text('import coverage\ncoverage.process_startup()\n')
    config=report/'coverage.ini'
    config.write_text('[run]\nbranch = true\npatch = subprocess\nparallel = true\ndata_file = '+str(report/'.coverage')+
        '\ninclude =\n    '+'\n    '.join(str(REPO/p) for p in ['test_support/*','strava_app/settings_test.py','manage.py',
        'garage/*.py','garage/services/*.py','garage/importers/*.py','garage/management/commands/*.py','tools/garage_progress.py'])+
        '\nomit =\n    '+str(REPO/'garage/tests*')+'\n    '+str(REPO/'garage/migrations/*')+'\n[report]\nshow_missing = true\n')
    env=dict(ENV,PYTHONPATH=str(report)+':'+str(package))
    run([PYTHON,'manage.py','check','--settings=strava_app.settings_test'],env)
    run([PYTHON,'manage.py','makemigrations','--check','--dry-run','--settings=strava_app.settings_test'],env)
    run([PYTHON,'-m','coverage','erase','--rcfile='+str(config)],env)
    run([PYTHON,'-m','coverage','run','--rcfile='+str(config),'-m','pytest','-q','--tb=short',
         '--junitxml='+str(report/'pytest.xml'),*sys.argv[2:]],env)
    for args in [['combine'],['report'],['json','-o',str(report/'coverage.json')]]:
        run([PYTHON,'-m','coverage',args[0],'--rcfile='+str(config),*args[1:]],env)
    psql("SELECT count(*) AS leftover_test_databases FROM pg_database WHERE datname LIKE 'test_stravagancia_test%'")
    print('REPORT_DIR='+str(report),flush=True)
elif sys.argv[1]=='inspect':
    psql("SELECT datname FROM pg_database WHERE datname LIKE 'test_stravagancia_test%'")
elif sys.argv[1]=='stop':
    root=Path(json.loads(STATE.read_text())['root'])
    assert root.parent==Path('/private/tmp') and root.name.startswith('garage018-validation-')
    psql("SELECT count(*) AS leftover_test_databases FROM pg_database WHERE datname LIKE 'test_stravagancia_test%'")
    run([PG/'pg_ctl','-D',root/'data','-m','fast','-w','stop'])
    shutil.rmtree(root/'data');STATE.unlink();print('POSTGRES_STOPPED=True\nVALIDATION_DIR='+str(root))
else:
    raise SystemExit('Unknown action')
