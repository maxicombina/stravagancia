"""Garage local con Strava real (garage-044, garage-048): clúster demo 55433 y las credenciales Strava del usuario.

Acciones: check | serve [puerto] | run <args de manage.py>. Siempre con
strava_app.settings_local (nunca producción): en DJANGO_SETTINGS_MODULE del
hijo y como --settings justo detrás del subcomando, así que un «--» no lo deja suelto.
STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET y STRAVA_REFRESH_TOKEN: gana la exportada no
vacía; si no, la de <repo>/.env. Del archivo sólo se toman esas tres claves (el resto,
p. ej. DB_* o NEON_PASSWORD, se descarta); el hijo sigue sin leer ni escribir .env.
Sólo deja pasar al hijo PATH/HOME/USER/LOGNAME/TMPDIR/LANG, LC_ALL, TEST_DB_* del
clúster demo y las variables de ALLOWED. Nunca imprime valores: sólo nombres y su origen.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPO=Path('/Users/maxicombina/src/learning/django/stravagancia')
PYTHON=Path(os.environ.get('GARAGE_TEST_PYTHON', REPO/'.venv/bin/python'))  # override when .venv belongs to the Docker image
STATE=Path(os.environ.get('GARAGE_DEMO_STATE', '/private/tmp/garage_demo_pg_state.json'))  # override only to test this helper
ENV_FILE=Path(os.environ.get('GARAGE_LOCAL_ENV_FILE', REPO/'.env'))  # override only to test this helper; not for the child
MODULE='strava_app.settings_local'
SETTINGS='--settings='+MODULE
PORT='8767'  # the settings_test demo uses 8766
REQUIRED=('STRAVA_CLIENT_ID','STRAVA_CLIENT_SECRET','STRAVA_REFRESH_TOKEN')
ALLOWED=REQUIRED+('GARAGE_STRAVA_USER','GARAGE_SYNC_TOKEN','STRAVA_WEBHOOK_SUBSCRIPTION_ID')
BASE={k:v for k,v in os.environ.items() if k in {'PATH','HOME','USER','LOGNAME','TMPDIR','LANG'}}
BASE['LC_ALL']='C'
# REQUIRED are added at launch by strava_values(): the exported one or that of ENV_FILE.
ENV=dict(BASE,DJANGO_SETTINGS_MODULE=MODULE,TEST_DB_HOST='127.0.0.1',TEST_DB_PORT='55433',
         TEST_DB_NAME='stravagancia_test_demo',TEST_DB_USER='stravagancia_test',TEST_DB_PASSWORD='stravagancia_test',
         **{k:os.environ[k] for k in ALLOWED if k in os.environ and k not in REQUIRED})
# .env lines as python-dotenv reads them: KEY=value with an optional «export »; the value in paired
# quotes, or bare (stripped, a « #» starts a comment). Anything else is skipped, never shown.
# Unlike python-dotenv: no ${VAR} expansion, no escapes in double quotes, no multi-line values.
ENV_LINE=re.compile(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)')
QUOTED=re.compile(r'''\s*(?:'([^']*)'|"([^"]*)")\s*(?:#.*)?''')
# Never with real credentials loaded: the suite (garage_test_pg.py), interactive shells, a dump of the
# settings (diffsettings prints GARAGE_SYNC_TOKEN) and a server that could bind outside 127.0.0.1 (use serve).
DENIED={'test','testserver','pytest','-m','-c','shell','dbshell','diffsettings','runserver'}
USAGE='Uso: garage_local_strava.py check | serve [puerto] | run <comando de manage.py> [args]'


def fail(message):
    print(message,file=sys.stderr)
    return 2


def demo_ready():
    if not STATE.exists():
        return fail(f'No hay demo en marcha (falta {STATE}): arranca la demo con garage_demo_pg.py start.')
    try:
        port=json.loads(STATE.read_text()).get('port')
    except (OSError,ValueError,AttributeError):
        port=None
    if port!=55433:
        return fail(f'{STATE} no es el estado del clúster demo 55433.')
    return 0


def env_file_values():
    """The non-empty REQUIRED values of ENV_FILE, plus a one-line note when it cannot be read.

    Only the REQUIRED keys are kept: the rest of the file (production database, Neon, other
    tokens) is discarded here. A repeated key keeps its last value; bad lines are skipped.
    """
    unreadable=f'.env: no se pudo leer {ENV_FILE}; sólo cuentan las variables exportadas.'
    try:
        if not ENV_FILE.exists():
            return {},f'.env: no existe {ENV_FILE}; sólo cuentan las variables exportadas.'
        if not ENV_FILE.is_file():  # a directory, a FIFO (would block), a device (/dev/zero never ends)
            return {},unreadable
        text=ENV_FILE.read_bytes().decode('utf-8-sig','replace')
    except OSError:  # no permission...: one line, no traceback
        return {},unreadable
    values={}
    for line in re.split(r'\r\n|\r|\n',text):
        match=ENV_LINE.fullmatch(line)
        if not match or match[1] not in REQUIRED:
            continue
        quoted=QUOTED.fullmatch(match[2])
        if quoted:
            value=quoted[1] if quoted[1] is not None else quoted[2]
        elif match[2].lstrip()[:1] not in {'"',"'"}:  # an unpaired quote is a bad line
            value=re.sub(r'\s+#.*','',match[2]).strip()
        else:
            continue
        if '\0' not in value:  # no process environment holds a NUL (the launch would fail): a bad line too
            values[match[1]]=value
    return {k:v for k,v in values.items() if v.strip()},None


def strava_values():
    """REQUIRED for the child (exported and not empty, else from ENV_FILE), where each comes from, and the note."""
    from_file,note=env_file_values()
    values,sources={},{}
    for k in REQUIRED:
        if os.environ.get(k,'').strip():
            values[k],sources[k]=os.environ[k],'exportada'
        elif k in from_file:
            values[k],sources[k]=from_file[k],'de .env'
    return values,sources,note


def report(sources,note):
    """Print only names and where each one comes from («definida (exportada)», «definida (de .env)», «FALTA»)."""
    print('Variables de Strava (sólo nombres, nunca valores):')
    for k in REQUIRED:
        print(f'  {k}: '+(f'definida ({sources[k]})' if k in sources else 'FALTA'))
    print('  GARAGE_STRAVA_USER: '+('definida' if os.environ.get('GARAGE_STRAVA_USER','').strip()
                                    else 'vacía (Garage mostrará Strava «no configurado» y no sincroniza)'))
    if note:
        print(note)
    if len(sources)<len(REQUIRED):
        print(f'Faltan variables obligatorias: añádelas a {ENV_FILE} o expórtalas en tu shell, y repite.')


def manage_args(args):
    """The manage.py subcommand and its arguments (without SETTINGS), or None when refused."""
    if args[:1]==['manage.py']:
        args=args[1:]
    args=[arg for arg in args if arg!=SETTINGS]
    if not args:
        fail('Falta el comando de manage.py. '+USAGE)
        return None
    if args[0] in DENIED or 'pytest' in args:
        fail(f'«{args[0]}» no se permite con Strava real: pruebas con garage_test_pg.py, servidor con «serve»; '
             'shell, dbshell y diffsettings, nunca.')
        return None
    for arg in args:
        flag=arg.split('=',1)[0]
        # argparse accepts abbreviations such as --sett; only the exact local settings are allowed.
        if flag.startswith('--') and len(flag)>2 and '--settings'.startswith(flag):
            fail('Sólo se admite '+SETTINGS+'.')
            return None
    return args


def launch(command,timeout,env):
    sys.stdout.flush()  # our lines before the child's
    # SETTINGS right after the subcommand: Django's pre-parse sees it even when the user adds «--».
    argv=[PYTHON,'manage.py',command[0],SETTINGS,*command[1:]]
    try:
        return subprocess.run([str(x) for x in argv],cwd=REPO,env=env,timeout=timeout).returncode
    except OSError:
        return fail(f'No se pudo ejecutar {PYTHON}: exporta GARAGE_TEST_PYTHON con el Python de macOS.')
    except KeyboardInterrupt:
        return 130


def main(argv):
    action,args=(argv[0],argv[1:]) if argv else ('',[])
    if action not in {'check','serve','run'}:
        return fail(USAGE)
    status=demo_ready()
    if status:
        return status
    if action=='check':
        if args:
            return fail(USAGE)
        command,timeout=['check'],600
    elif action=='serve':
        port=args[0] if args else PORT
        if len(args)>1 or not (port.isascii() and port.isdecimal() and 1024<=int(port)<=65535):
            return fail('Puerto no válido (1024–65535). '+USAGE)
        command,timeout=['runserver',f'127.0.0.1:{port}','--noreload','--insecure'],None
    else:
        command,timeout=manage_args(args),600
        if command is None:
            return 2
    values,sources,note=strava_values()  # only now: a refused command never reads .env
    missing=len(values)<len(REQUIRED)
    if action=='check' or missing:
        report(sources,note)
    if missing:
        return 2
    if action=='serve':
        print(f'Garage con Strava real en http://127.0.0.1:{port}/garage/ (Ctrl-C para parar).')
    return launch(command,timeout,dict(ENV,**values))


if __name__=='__main__':
    raise SystemExit(main(sys.argv[1:]))
