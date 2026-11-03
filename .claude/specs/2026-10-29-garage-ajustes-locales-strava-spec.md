# garage-044: ajustes locales para probar Strava real contra PostgreSQL local

Fecha: 29 oct 2026. Autora del diseño: Claude Fable 5.1 (orquestación);
implementación por agente Opus 5.5. Bead `garage-044` (depende de 030 y 043).
Rama `garage`, sin commits, **sin migración** (la 0013 sigue reservada), nada en
Neon. El usuario no ha revisado aún estas decisiones: están escritas para que
las confirme o cambie (D1–D11); todo es aditivo y reversible.

## 0. Problema

El paso «el usuario arranca el servidor demo con `GARAGE_STRAVA_USER=maxi` y su
token de Strava» no tiene ajustes con los que ejecutarse:

- `strava_app.settings_test` (`test_support/isolation.py::install()`) elimina
  todas las variables `STRAVA_*`, pone valores sintéticos, bloquea `.env` y
  sustituye `requests.sessions.Session.send` por una función que prohíbe el
  HTTP real. El helper `tools/handoff/garage_demo_pg.py run` sólo deja pasar
  `GARAGE_STRAVA_USER`.
- `strava_app.settings` (producción) carga `.env` y apunta a Neon por
  `DATABASE_URL`: prohibido para esto.
- Garage obtiene el access token con
  `strava_integration.utils.refresh_access_token()` (lee `STRAVA_CLIENT_ID`,
  `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN` del entorno al importar el
  módulo y, si existe `.env`, reescribe en él el refresh/access token).

Objetivo: que el usuario pueda arrancar la demo local (PostgreSQL 55433, usuario
`maxi` con el inventario importado de ProBikeGarage) con sus credenciales reales
de Strava exportadas en **su** shell, pulsar Más → Strava → «Importar histórico»
desde 2012-01-01 y «Sincronizar ahora», y después ejecutar
`garage_probikegarage_verify`. La IA nunca ve, lee ni exporta esos valores.

## 1. Decisiones

- **D1. Módulos nuevos, sin tocar los existentes.** `strava_app/settings_local.py`
  (ajustes) y `test_support/local_strava.py` (bootstrap `install_local()` más
  funciones puras comprobables). **No se modifican** `test_support/isolation.py`,
  `strava_app/settings_test.py`, `strava_app/settings.py`, `manage.py`,
  `conftest.py` ni nada del legado (`strava_integration/*`). `install_local()`
  puede importar `database_config` de `isolation` (es pura) pero no `install()`.
- **D2. Base de datos: sólo PostgreSQL loopback.** `DATABASES["default"] =
  database_config()` tras `os.environ.setdefault` de `TEST_DB_PORT=55433` y
  `TEST_DB_NAME=stravagancia_test_demo` (el clúster demo). Así hereda las
  validaciones de `isolation` (host loopback numérico, nombre
  `stravagancia_test*`). Antes de calcularla se eliminan del entorno
  `DATABASE_URL` y toda clave `DB_*`/`PG*`, y se instala el mismo guardián de
  `psycopg2.connect` que `isolation` (host, puerto, base y rol exactos). Neon es
  inalcanzable por construcción.
- **D3. Variables Strava reales, sólo del entorno.** Obligatorias
  `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`: si falta
  alguna o está vacía, `django.core.exceptions.ImproperlyConfigured` con un
  mensaje que **sólo nombra** las variables ausentes (nunca valores, ni
  parciales). `STRAVA_ACCESS_TOKEN` se elimina (siempre se renueva);
  `STRAVA_WEBHOOK_VERIFY_TOKEN` toma un valor sintético si no viene (el webhook
  no se usa en local). `GARAGE_STRAVA_USER` se lee del entorno; vacío ⇒ aviso
  por el logger (`garage`) al arrancar y Garage muestra «no configurado».
  `GARAGE_SYNC_TOKEN` y `STRAVA_WEBHOOK_SUBSCRIPTION_ID` del entorno, por
  defecto "".
- **D4. `.env` intocable.** `PYTHON_DOTENV_DISABLED=1`, `dotenv.load_dotenv` y
  `dotenv.dotenv_values` neutralizados **antes** de importar nada que los use,
  y un `sys.addaudithook` que impide abrir (leer o escribir) cualquier archivo
  llamado `.env`, igual que `isolation`. Además `install_local()` apunta
  `strava_integration.utils._ENV_FILE` a una ruta que no existe (dentro del
  `TMPDIR` o `tempfile.gettempdir()`, nombre fijo p. ej. `garage-local-no-env`),
  de modo que `refresh_access_token()` **no persiste** los tokens renovados
  (`os.path.exists` da False; nunca llega al `open`). Es el mismo comportamiento
  que en Render, donde sólo existe `STRAVA_REFRESH_TOKEN` como secreto. Límite
  documentado: si Strava rotara el refresh token, el usuario tendría que
  renovarlo él; hasta hoy no ha pasado en producción.
- **D5. Red: sólo PostgreSQL local y `www.strava.com:443`.** Mismo patrón de
  `isolation` sobre `socket.getaddrinfo`, `socket.socket.connect` y
  `connect_ex`, con una lista de permitidos: la tupla del PostgreSQL configurado
  y `("www.strava.com", 443)`. Como `requests` resuelve el nombre y luego
  conecta a la IP, el envoltorio de `getaddrinfo` **añade a la lista** las
  direcciones que devuelva para un host permitido (sólo esas). Todo lo demás
  (Nominatim, Overpass, Neon, `api.probikegarage.com`, `www.api-v3.strava.com`
  —aún no existe—) lanza `RuntimeError("Network access is disabled except local
  PostgreSQL and www.strava.com")`. `Session.send` **no** se sustituye: el HTTP
  a Strava es real. La lista vive en una constante `ALLOWED_HTTP_HOSTS` para
  ampliarla cuando Strava cambie de dominio (2027-06-01). *(Cambiado en §6:
  la excepción es `NetworkDenied`, un `OSError`/`requests.ConnectionError`, y
  `Session.send` sí se envuelve para filtrar método y ruta, R2 y R4.)*
- **D6. Django como la demo.** *(Cambiado en §6, R2: `DEBUG = False` siempre,
  sin `GARAGE_LOCAL_DEBUG`; R3: logger `django.request`; R7: cookies propias.)*
  `DEBUG = os.environ.get("GARAGE_LOCAL_DEBUG") ==
  "1"` (por defecto False; la demo ya se sirve con `runserver --insecure`),
  `ALLOWED_HOSTS` loopback, `SECRET_KEY` constante sintética distinta de la de
  pruebas (las sesiones sobreviven a un reinicio), `INSTALLED_APPS`,
  `MIDDLEWARE`, `AUTHENTICATION_BACKENDS`, `AXES_*`, `TEMPLATES`, `TIME_ZONE`,
  `AUTH_PASSWORD_VALIDATORS = []`, `STATIC_URL`, `GRAFANA_URL` y
  `DEFAULT_AUTO_FIELD` idénticos a `settings_test`. `LOGGING` con los loggers
  `garage` y `strava_integration` en INFO a stderr (formato con hora), para ver
  la línea de cada sincronización. Sin `whitenoise`.
- **D7. Rechazos.** `settings_local` lanza `RuntimeError` si `"pytest" in
  sys.modules` o `PYTEST_VERSION` está en el entorno (como `settings.py`): la
  suite **nunca** corre con estos ajustes (`isolation.validate_settings_choice`
  ya los rechaza por su lado). También si `DJANGO_SETTINGS_MODULE` apunta a otro
  módulo distinto de `strava_app.settings_local`.
- **D8. Helper `tools/handoff/garage_local_strava.py`.** Mismo estilo que
  `garage_demo_pg.py` (`REPO`, `PYTHON` de `GARAGE_TEST_PYTHON`, `BASE` con
  `PATH/HOME/USER/LOGNAME/TMPDIR/LANG`, `LC_ALL=C`). Exige el fichero de estado
  de la demo `/private/tmp/garage_demo_pg_state.json` (si no existe: salir con
  «arranca la demo con garage_demo_pg.py start») y fija `TEST_DB_*` del clúster
  55433. **Deja pasar sólo**: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`,
  `STRAVA_REFRESH_TOKEN`, `GARAGE_STRAVA_USER`, y opcionales
  `GARAGE_SYNC_TOKEN`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID` *(sin
  `GARAGE_LOCAL_DEBUG` desde §6; el hijo recibe además
  `DJANGO_SETTINGS_MODULE=strava_app.settings_local`, R1)*.
  Acciones: `check` (lista cada variable obligatoria como «definida» /
  «FALTA», sin valores, y ejecuta `manage.py check
  --settings=strava_app.settings_local`; sale 2 si falta alguna), `serve`
  (`manage.py runserver 127.0.0.1:8767 --noreload --insecure
  --settings=strava_app.settings_local`; puerto opcional como segundo
  argumento) y `run <args de manage.py>` (añade `--settings=strava_app.settings_local`
  si no viene). Rechaza `test`, `-m pytest`, `pytest`, `shell`, `dbshell`,
  `migrate`/`makemigrations` **no**: `migrate` se permite (clúster local). Nunca
  imprime valores de entorno; `check` imprime sólo nombres.
- **D9. Receta del usuario** (documentarla en TESTING.md y en el handoff; la IA
  nunca la ejecuta con valores reales). En **su Terminal**, nunca con `!` dentro
  de Claude Code (quedaría en la transcripción); la línea de las credenciales
  va **sola** (tecleada o pegada sin otra línea) y empieza con **un espacio**
  para que `histignorespace` no la guarde en `~/.zsh_history` (R5; segunda
  revisión, 29 oct: un bloque pegado de varias líneas es un solo comando que
  empieza por `export` y sí se guardaría; comprobar con `fc -l -3`):

  ```bash
  export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
  export GARAGE_STRAVA_USER=maxi
  ```

  ```bash
   export STRAVA_CLIENT_ID=… STRAVA_CLIENT_SECRET=… STRAVA_REFRESH_TOKEN=…
  ```

  ```bash
  python3 tools/handoff/garage_local_strava.py check
  python3 tools/handoff/garage_local_strava.py serve        # http://127.0.0.1:8767/garage/ como maxi
  ```

  Después, en el navegador: Más → Strava → «Sincronizar ahora» (crea la
  `StravaAccount` y vincula las bicis) y, **una sola vez**, «Importar
  histórico» desde 2012-01-01; en la página del trabajo, «Continuar
  importación» hasta que diga completado (cada paso: hasta 4 páginas de 50
  actividades de cualquier deporte, con parada posible a los 25 s). No volver
  a pulsar «Importar histórico»: crearía otro trabajo desde la página 1
  (segunda revisión, 29 oct).
  Al terminar, con el mismo helper:
  `python3 tools/handoff/garage_local_strava.py run garage_probikegarage_verify
  ~/.cache/stravagancia/probikegarage/probikegarage-2026-10-25-compact.json
  --owner 2 --mapping ~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-25.json`.
- **D10. Sin cambios en el legado ni en Garage.** Nada de `strava_integration`,
  `garage/` ni migraciones. Si al implementar aparece algo que lo exija, parar
  y anotarlo en §4.
- **D11. Textos** en español para lo que vea el usuario (mensajes del helper);
  docstrings y mensajes de excepción en inglés como el resto de
  `test_support`.

## 2. Pruebas (pytest, `settings_test`, PostgreSQL 55434, como siempre)

Archivo nuevo en la raíz `tests_local_strava.py` (mismo patrón de subproceso que
`tests_test_environment.py::child`, construyendo el entorno del hijo
**explícitamente**: `PATH`, `HOME`, `TEST_DB_*` del proceso padre —el helper
de pruebas los deja en 55434—, variables Strava **sintéticas** y `GARAGE_STRAVA_USER=demo`;
sin heredar nada más). Deben cubrir al menos:

1. Importar `strava_app.settings_local` en el hijo con `DATABASE_URL`, `DB_*`,
   `PG*`, `SECRET_KEY` y `STRAVA_ACCESS_TOKEN` «de producción» sintéticos en el
   entorno ⇒ `DATABASES` loopback con el puerto de `TEST_DB_PORT`, esas claves
   ausentes de `os.environ`, `strava_integration.utils.STRAVA_CLIENT_SECRET`
   igual al valor sintético exportado (no al de `isolation`),
   `'strava_app.settings' not in sys.modules`.
2. Falta `STRAVA_REFRESH_TOKEN` (y, en otro caso, está vacía) ⇒ salida ≠ 0 y
   stderr nombra `STRAVA_REFRESH_TOKEN` sin el valor de ninguna otra variable.
3. `open(".env")` en el hijo ⇒ `RuntimeError`; `dotenv.load_dotenv()` ⇒ False;
   `os.path.exists(strava_integration.utils._ENV_FILE)` ⇒ False; con
   `requests.post` sustituido en el hijo por un doble que devuelve
   `{"access_token": "a", "refresh_token": "r"}`, `refresh_access_token()`
   devuelve `"a"` y no crea ningún archivo (comprobar el `.env.disabled`/ruta).
4. Red: `requests.get("https://example.com/", timeout=1)` ⇒ `RuntimeError`
   antes de abrir conexión; `local_strava.check_address(("www.strava.com",
   443))` no lanza; `("www.strava.com", 80)`, `("api.probikegarage.com", 443)`
   y `("203.0.113.1", 443)` lanzan. Con `socket.getaddrinfo` original sustituido
   por un doble que devuelve `("93.184.216.34", 443)` para `www.strava.com`, el
   envoltorio añade esa dirección y `check_address` la acepta; una IP devuelta
   para otro host no se añade (el otro host ya falla antes). Estas funciones
   puras se prueban en el propio proceso de pytest **sin** llamar a
   `install_local()` (el módulo no debe tener efectos al importarse).
5. `manage.py check --settings=strava_app.settings_local` en el hijo ⇒ 0.
   `manage.py check` con `PYTEST_VERSION=1` ⇒ ≠ 0 y «pytest» en stderr.
6. Helper: `check` sin `STRAVA_CLIENT_SECRET` ⇒ salida 2, stdout nombra la
   variable que falta y ninguna línea contiene los valores sintéticos; `run -m
   pytest` y `run test` ⇒ rechazo (salida 2); `serve`/`run` con
   `GARAGE_TEST_PYTHON` apuntando a un script de prueba que vuelque
   `sorted(os.environ)` ⇒ el hijo recibe exactamente las claves permitidas más
   `TEST_DB_*`, `BASE` y `LC_ALL`, y `--settings=strava_app.settings_local`;
   sin el fichero de estado de la demo (apuntar `STATE` a una ruta inexistente
   por variable de entorno o parámetro del módulo) ⇒ salida 2 con el mensaje.
7. `isolation.validate_settings_choice("strava_app.settings_local")` lanza
   (ya existe; una aserción de una línea documenta que la suite lo rechaza).

Ninguna prueba toca `.env` real, Strava real ni otro host; nada lee
`~/.cache/stravagancia`.

## 3. Entrega

- Código: `strava_app/settings_local.py`, `test_support/local_strava.py`,
  `tools/handoff/garage_local_strava.py`, `tests_local_strava.py`.
- Documentación (el agente): sección «garage-044» en `TESTING.md` (qué es, la
  receta D9, qué protege y el límite D4) y un párrafo en
  `docs/garage-data-sources.md` (Strava en local: con qué ajustes). El handoff,
  CLAUDE.md, Beads y el estado los actualiza Fable.
- Verificación: `tests_local_strava.py` y `tests_test_environment.py` en
  verde; la suite completa con `tools/handoff/garage_test_pg.py run -m pytest
  -q --tb=short -p no:cacheprovider` (antes: 2690 + 45 subcasos), `manage.py
  check` y `makemigrations --check --dry-run` con `settings_test`; informe
  `docs/validation/garage-044.json` con el mismo formato que `garage-043.json`.

## 4. Hallazgos de la implementación

Agente Opus 5.5, 29 oct 2026. Implementado tal como D1–D11 salvo lo que sigue;
nada de `strava_integration/`, `garage/`, `settings.py`, `settings_test.py`,
`isolation.py`, `manage.py` ni `conftest.py` ha cambiado (D10 no hizo falta
romperlo). Sin migración.

### 4.1 Desviaciones y precisiones

1. **`SECRET_KEY` también se quita del entorno** (D2 sólo nombraba
   `DATABASE_URL`, `DB_*` y `PG*`): la prueba §2.1 pide que «esas claves»,
   `SECRET_KEY` incluida, falten de `os.environ`. Los ajustes usan su constante
   sintética (D6); `STRAVA_ACCESS_TOKEN` se quita como dice D3.
2. **Guardián de `psycopg2.connect`: base exacta.** Igual que `isolation` en
   host, puerto, rol, claves admitidas y `PG*`, pero sólo admite
   `DATABASES["default"]["NAME"]`: no `postgres` ni `test_<nombre>`, que
   `isolation` necesita para crear la base de pruebas y aquí no hacen falta.
3. **Ruta de `_ENV_FILE`:** `<tempfile.gettempdir()>/garage-local-no-env/.env`.
   Dos defensas: no existe (`install_local()` se niega a arrancar si existe) y,
   como se llama `.env`, el gancho de auditoría impediría abrirla aunque
   alguien la creara después.
4. **Helper, más estricto que D8:**
   - además de `test`, `pytest`, `-m`, `shell` y `dbshell`, rechaza `-c`,
     `testserver` y **`runserver`** (para que el servidor sólo escuche en
     127.0.0.1, siempre con `serve`), y cualquier `--settings` que no sea
     exactamente `--settings=strava_app.settings_local` (también abreviaturas
     como `--sett=` y la forma con espacio), porque `manage.py` fija por
     defecto `strava_app.settings`;
   - acepta un `manage.py` inicial opcional (`run manage.py migrate` =
     `run migrate`), por costumbre con `garage_demo_pg.py run manage.py …`;
   - `serve` y `run` también comprueban las tres variables obligatorias antes
     de lanzar nada (salida 2 con el mismo listado que `check`);
   - el estado de la demo, además de existir, debe decir `"port": 55433`;
   - para probarlo, la ruta del estado se puede cambiar con la variable
     `GARAGE_DEMO_STATE` (sólo la lee el helper; no pasa al hijo). Se eligió la
     variable y no un parámetro del módulo porque `tools/handoff/README.md`
     pide no importar los helpers como librería;
   - `check` muestra también `GARAGE_STRAVA_USER` como «definida» o «vacía»
     (informativo: no hace salir con 2, como D3);
   - si `GARAGE_TEST_PYTHON` no se puede ejecutar (p. ej. el `.venv` de Linux),
     mensaje y salida 2 en vez de una traza.
5. **Aviso de `GARAGE_STRAVA_USER` vacío:** en inglés, como el resto de los
   mensajes del logger `garage`, y emitido al importar los ajustes; a esa hora
   Django aún no ha aplicado `LOGGING`, así que lo escribe el manejador de
   último recurso de Python en stderr (sin la hora del formato).
6. **D9, mapa:** el de `mapping-demo-maxi-2026-10-25.json` dejó de valer al
   recrear el clúster demo el 29 oct (los UUID cambiaron); la receta de
   TESTING.md usa `mapping-demo-maxi-2026-10-29.json`.
7. **Pruebas además de §2:** los ajustes coinciden con `settings_test` en las
   claves de D6 (comparando con el módulo, porque `django.conf.settings`
   antepone «/» a `STATIC_URL`); páginas sólo para hosts loopback (200 frente a
   400 con el cliente de Django); los parámetros reales de conexión de Django
   pasan el guardián y uno remoto, otra base u otro puerto no; marcador
   existente rechazado; base no local rechazada; `connect`/`connect_ex` al
   PostgreSQL y a la IP resuelta llegan al socket y nada más; la prueba de §2.3
   abre `.env` en un directorio temporal y nunca en la raíz del repositorio.
8. **Documentación además de §3:** una línea del helper nuevo en
   `tools/handoff/README.md`.

### 4.2 Límites

- Como `isolation`, protege de escapes accidentales; no es un sandbox para
  código hostil. `gethostbyname`/`gethostbyaddr` (resolución DNS, sin
  conexión) no pasan por el guardián; libpq sólo por el envoltorio de
  `psycopg2.connect`.
- D4 sin cambios: los tokens renovados no se guardan. Si Strava devolviera un
  refresh token distinto, el usuario tendría que exportar el nuevo a mano.
- Si las credenciales son las de la aplicación de Strava que usa Render, la
  cuota de la API (por aplicación) es compartida con producción; Garage para
  con un 429 y se retoma pulsando de nuevo (garage-030).
- `serve` usa 8766 por defecto, el puerto de la demo con `settings_test`: hay
  que pararla antes o elegir otro puerto.
- No se ha probado contra Strava real (prohibido para el agente): sólo
  `check` con valores sintéticos contra el clúster demo 55433 (sin servidor,
  migraciones ni sincronización) y las pruebas con dobles.

### 4.3 Para el usuario

- Confirmar D1–D11, en especial D4 (tokens renovados sin guardar) y D5 (sólo
  `www.strava.com:443`).
- Confirmar los rechazos añadidos al helper (§4.1.4), sobre todo `runserver`
  en `run`.
- Seguir la receta de TESTING.md («garage-044») con sus credenciales en su
  shell: `check`, `serve`, «Sincronizar ahora», «Importar histórico» desde
  2012-01-01 y `garage_probikegarage_verify`.

## 5. Revisión adversarial

Revisor independiente (agente Opus 5.5), 29 oct 2026. Sólo valores sintéticos,
nada contra Strava real ni `serve`, ni `.env` ni `~/.cache/stravagancia`. Sondas
en `tests_local_strava_review.py` (`test_r044_n`): los hijos llevan
`PYTHON_DOTENV_DISABLED=1` y sockets/resolución falsos instalados antes de los
ajustes, así que ninguna sonda puede salir a la red aunque un guardián fallara.
Ejecución (`garage_test_pg.py run -m pytest tests_local_strava_review.py
tests_local_strava.py -q --tb=short -p no:cacheprovider`, 55434): **8 fallan**
(r044_1 ×3, r044_2 a r044_6: defectos demostrados), **49 pasan** (r044_7, hueco
cubierto, y las 48 del implementador), 4,0 s.

| # | Hallazgo | Gravedad | Evidencia | Corrección propuesta | Prueba |
|---|----------|----------|-----------|----------------------|--------|
| 1 | Un `--` en `run` convierte el `--settings` que el helper añade al final en argumento posicional: el pre-análisis de Django no lo ve, el hijo no lleva `DJANGO_SETTINGS_MODULE` y `manage.py` carga `strava_app.settings` (lee `.env` con `load_dotenv()` y toma `DATABASE_URL` ⇒ Neon). `run migrate -- garage` conectaría a Neon con las credenciales reales en el entorno. | importante | `tools/handoff/garage_local_strava.py:22-24` (ENV sin `DJANGO_SETTINGS_MODULE`), `:78` (se añade al final); `manage.py:20`; `strava_app/settings.py:12`, `:102` | Poner `DJANGO_SETTINGS_MODULE=strava_app.settings_local` en `ENV` (red independiente del orden de argv) e insertar `SETTINGS` justo tras el subcomando (`[args[0], SETTINGS, *args[1:]]`), o rechazar `--`. Ajustar `BASE_KEYS` en `tests_local_strava.py`. | `test_r044_1` (3 casos; reproduce el pre-análisis de `ManagementUtility.execute`) |
| 2 | Si el guardián de red salta durante la renovación del token, su `RuntimeError` no es `RequestException`: atraviesa `StravaClient._renew` y la vista da 500. Con `GARAGE_LOCAL_DEBUG=1` la página técnica imprime las variables locales de cada marco (Django no filtra locales con DEBUG activo): `payload` de `refresh_access_token()` con `client_secret` y `refresh_token`, y en un GET la cabecera `Authorization: Bearer` de los marcos de requests/urllib3. Disparadores: proxy del sistema macOS (requests lo lee aunque el helper quite `HTTPS_PROXY`), una redirección a otro host (p. ej. la migración a `www.api-v3.strava.com`), cualquier host fuera de la lista. | importante | `strava_integration/utils.py:20-26`; `garage/services/strava_client.py:88-98`; `test_support/local_strava.py:67`; `strava_app/settings_local.py:24`; `django/views/debug.py:276-277` | `DEBUG = False` fijo en `settings_local` (quitar `GARAGE_LOCAL_DEBUG` de ajustes, helper, pruebas y doc; `--insecure` ya sirve los estáticos) más el hallazgo 3 para no perder la traza. Complemento opcional: que el guardián lance una subclase de `OSError` (urllib3 la convierte en `ConnectionError` y Garage muestra «error de red»), cambiando las pruebas que esperan `RuntimeError`. | `test_r044_2` |
| 3 | Con DEBUG desactivado (por defecto) un 500 no deja rastro en la terminal: `LOGGING` sólo configura `garage` y `strava_integration`; `django.request` cae en el `console` de Django, que exige DEBUG, y en `mail_admins` sin `ADMINS`. El usuario sólo ve «Server Error (500)» y la línea de acceso; lo natural es activar `GARAGE_LOCAL_DEBUG=1`, que lleva al hallazgo 2. | menor | `strava_app/settings_local.py:59-68`; `DEFAULT_LOGGING` de `django/utils/log.py` | Añadir `"django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False}` (traza sin variables locales). | `test_r044_3` |
| 4 | D5 filtra por host y puerto, no por método ni ruta: cualquier `PUT`/`POST`/`DELETE` a `www.strava.com` pasa. La única escritura del código (auto-renombrado del legado, `PUT /activities/{id}`, alcanzable desde el webhook `csrf_exempt` del legado —también con un POST «simple» entre sitios a 127.0.0.1— o desde la acción del admin) hoy no se ejecuta sólo por coincidencia: Overpass y Nominatim están bloqueados ⇒ `generate_name` devuelve "" ⇒ no hay PUT. | menor | `test_support/local_strava.py:59-67`, `:149`; `strava_integration/renaming.py:273-275`, `:294-307`; `strava_integration/views.py:159`, `:223-247`; `strava_integration/admin.py:10` | En `install_local()`, envolver `requests.adapters.HTTPAdapter.send` y admitir sólo `GET https://www.strava.com/api/v3/…` y `POST https://www.strava.com/oauth/token`; `RuntimeError` en lo demás. | `test_r044_4` |
| 5 | La receta deja las credenciales reales en disco: la línea `export STRAVA_CLIENT_ID=… STRAVA_CLIENT_SECRET=… STRAVA_REFRESH_TOKEN=…` tecleada tal cual queda en `~/.zsh_history` (aquí `histignorespace` está activo, pero la línea no empieza por espacio). Tampoco avisa de no ejecutarla con `!` dentro de Claude Code (quedaría en la transcripción). | menor | `TESTING.md:881`; spec D9 (línea 116) | En TESTING.md y el handoff: empezar esa línea con un espacio y explicar por qué, o `read -rs` por variable y `export`; «en tu Terminal, nunca con `!` en Claude Code». | sin prueba (documentación) |
| 6 | `run diffsettings` se admite e imprime en claro `GARAGE_SYNC_TOKEN` (que el helper reenvía) y el resto de ajustes, contra «nunca imprime valores de entorno» si el usuario exporta su token de sync real. | nit | `tools/handoff/garage_local_strava.py:19`, `:27`; `strava_app/settings_local.py:71` | Añadir `diffsettings` a `DENIED`. | `test_r044_5` |
| 7 | Si la demo de `settings_test` (8766) y `serve 8767` conviven, como sugiere TESTING.md, iniciar sesión en uno cierra la del otro: misma cookie `sessionid` en 127.0.0.1 (las cookies no distinguen puerto), misma tabla `django_session` (clúster 55433) y distinta `SECRET_KEY` ⇒ «Session data corrupted» y sesión anónima. | nit | `strava_app/settings_local.py:23` frente a `strava_app/settings_test.py:8`; `TESTING.md:876-877` | `SESSION_COOKIE_NAME = "garage_local_sessionid"` en `settings_local` (o la misma clave sintética que la demo). | `test_r044_6` |
| 8 | `serve` usa por defecto 8766, que hoy ocupa la demo con `settings_test`: la receta literal falla con «That port is already in use» (inocuo y documentado). | nit | `tools/handoff/garage_local_strava.py:105`; `TESTING.md:876-877` | Por defecto 8767 en el helper y en la receta. | sin prueba |
| 9 | Recuento: `tests_local_strava.py` tiene 26 funciones (48 casos), no 25. | nit | `TESTING.md:940`; `docs/validation/garage-044.json:13` | Corregir a 26. | sin prueba |
| 10 | Simplicidad: `settings_local.py:12-14` repite `reject_pytest()`, que `install_local()` ejecuta antes que nada (`local_strava.py:115`; lo importado antes no tiene efectos); `settings_local.py:49` recalcula `database_config()` en vez de usar lo que devuelve `install_local()`; el helper repite tres veces la lista de variables que faltan (`:51`, `:108`, `:116`) cuando `report()` ya la devuelve. | nit | las líneas citadas | `DATABASES = {"default": install_local()}`, quitar la comprobación duplicada y reutilizar `report()`. | sin prueba |
| 11 | Hueco de §2: nada fija que `strava_integration.utils` se importe después de neutralizar dotenv; si se reordenara `install_local()`, sólo §2.1 lo notaría, y leyendo el `.env` real. | hueco (no es defecto hoy) | `test_support/local_strava.py:141-147` | Mantener la prueba nueva. | `test_r044_7` (pasa) |

Corregir 1 y 2 obliga a tocar pruebas del implementador: `BASE_KEYS` de las del
helper (llevarán `DJANGO_SETTINGS_MODULE`), la aserción de `DEBUG` con
`GARAGE_LOCAL_DEBUG=1` y la lista `ALLOWED`.

Revisado sin hallazgo: Django usa `psycopg2` (psycopg 3 no está instalado), así
que el guardián de `psycopg2.connect` cubre libpq; `socket.create_connection`,
`http.client`/`urllib`, urllib3 y asyncio pasan por el `socket.getaddrinfo`
envuelto; IPv6 (se compara `address[:2]`); los proxys de entorno o del sistema
fallan cerrados (con los efectos de los hallazgos 2 y 3); `.env` tiene tres
capas (`PYTHON_DOTENV_DISABLED`, que python-dotenv 1.2.1 respeta, las funciones
neutralizadas y el gancho de auditoría) y `_ENV_FILE` no existe; `ImproperlyConfigured`
y `check` sólo nombran variables; el helper filtra el entorno por lista blanca y
no imprime valores; en la página técnica, `META` y los ajustes se ocultan por
nombre (salvo `STRAVA_CLIENT_ID`, que no es secreto); `garage_probikegarage_verify`
con `run` admite esos argumentos (volcado, `--owner`, `--mapping`; las `~` las expande el shell) y no usa red.

Veredicto: la receta de TESTING.md es segura tal cual **si** el usuario no
activa `GARAGE_LOCAL_DEBUG`, no usa `--` con `run`, teclea el `export` con un
espacio delante en su Terminal (no en Claude Code) y usa `serve 8767` o para
antes el `runserver` de la demo. Conviene corregir 1–3 antes: son cambios de
pocas líneas.

## 6. Correcciones y re-verificación

Agente Opus 5.5 (implementador), 29 oct 2026, con las decisiones de Fable sobre
§5. Mismos límites: nada real de Strava, sin `.env` ni `~/.cache/stravagancia`,
sin commits, sin tocar `strava_integration/`, `garage/`, `settings.py`,
`settings_test.py`, `isolation.py`, `manage.py` ni `conftest.py`. Sin migración.

| # | Estado | Qué cambió |
|---|--------|------------|
| R1 | corregido | El helper pone `DJANGO_SETTINGS_MODULE=strava_app.settings_local` en el entorno del hijo (`ENV`) **y** coloca `--settings=strava_app.settings_local` justo detrás del subcomando (`manage.py <cmd> --settings=… <resto>`), así que un `--` del usuario no lo deja suelto; quita las apariciones exactas que traiga el usuario y mantiene el rechazo de cualquier otro `--settings`. Pruebas: `BASE_KEYS` lleva `DJANGO_SETTINGS_MODULE`, el Python falso vuelca su valor, nuevos órdenes de argv y un caso `run migrate -- garage`. |
| R2 | corregido | `GARAGE_LOCAL_DEBUG` eliminado de los ajustes, del helper (`ALLOWED`), de las pruebas y de la documentación: `DEBUG = False` siempre (una prueba fija que ni `DEBUG=true` ni `GARAGE_LOCAL_DEBUG=1` lo activan, y que el helper ya no reenvía esa variable). Los guardianes de red (`getaddrinfo`, `connect`, `connect_ex` y el filtro de R4) lanzan `NetworkDenied`, subclase de `requests.exceptions.ConnectionError` —por tanto `OSError` y `RequestException`— con el mismo mensaje: urllib3 convierte el de los sockets en su `ConnectionError` y el del filtro ya lo es, así que el cliente de Garage lo muestra como «network» en vez de un 500 (prueba nueva `test_a_guard_trip_is_a_network_error_for_garage_not_a_500`, con un proxy como disparador). Se eligió esa base, y no `OSError` a secas, para que también el rechazo de `Session.send` (que urllib3 no envuelve) sea «network». Las pruebas que esperaban `RuntimeError` de la red esperan ahora `NetworkDenied` (urllib: `URLError` con `NetworkDenied` como `reason`). El guardián de `psycopg2.connect`, el de `.env` y los rechazos de pytest/ajustes siguen con `RuntimeError`. |
| R3 | corregido | `LOGGING` añade `django.request` → `console`, nivel ERROR, `propagate: False`: un 500 deja su traza (sin variables locales) en la terminal. |
| R4 | corregido | `install_local()` envuelve `requests.sessions.Session.send` (también lo usan las redirecciones) con la función pura `check_request(method, url)`: sólo `GET https://<host permitido>/api/v3/…` (consulta admitida) y `POST https://<host permitido>/oauth/token` (sin consulta), puerto 443 o ninguno, sin usuario/contraseña ni fragmento; lo demás lanza `NetworkDenied` antes de enviar. Pruebas puras: GET api/v3 pasa, POST oauth/token pasa, PUT/DELETE api/v3, POST api/v3/uploads, GET oauth/token, POST oauth/deauthorize, `http://`, otro puerto, otro host, `api/v2`, HEAD, método en minúsculas, URL o puerto inválidos fallan; y en el hijo, las peticiones rechazadas no llegan al resolvedor ni al socket. |
| R5 | corregido (doc) | Receta de TESTING.md y D9: la línea de las credenciales empieza con un espacio (`histignorespace`) y se avisa de ejecutarla en su Terminal, nunca con `!` en Claude Code. También en `tools/handoff/README.md`. |
| R6 | corregido | `diffsettings` en `DENIED` del helper (casos `run diffsettings` y `run diffsettings --all` en las pruebas de rechazo). |
| R7 | corregido | `SESSION_COOKIE_NAME = "garage_local_sessionid"` y `CSRF_COOKIE_NAME = "garage_local_csrftoken"`: el servidor local y la demo con `settings_test` pueden convivir en 127.0.0.1. |
| R8 | corregido | `serve` usa 8767 por defecto (constante `PORT`); mensaje, pruebas, receta (TESTING.md, D8, D9) y README actualizados. |
| R9 | corregido | Recuentos: `tests_local_strava.py` tiene ahora 28 funciones (las 26 de la implementación más `test_check_request_allows_only_api_reads_and_the_token_renewal` y `test_a_guard_trip_is_a_network_error_for_garage_not_a_500`), 53 casos; TESTING.md y `docs/validation/garage-044.json` corregidos. |
| R10 | corregido | `settings_local` ya no repite la comprobación de pytest: su primera línea útil es `_DATABASE = install_local()` (que rechaza pytest y otro `DJANGO_SETTINGS_MODULE` antes que nada) y `DATABASES = {"default": _DATABASE}`, sin recalcular `database_config()`. El helper calcula una sola vez la lista de variables que faltan (`MISSING`) y `report()` la reutiliza; `main()` valida primero los argumentos de cada acción y después, en un único sitio, informa y sale con 2 si falta alguna. |
| R11 | sin cambios | Hueco cubierto por `test_r044_7`, que sigue pasando (`strava_integration.utils` se importa después de neutralizar dotenv). |

**Prueba del revisor adaptada.** Sólo `test_r044_4`, mínimamente: capturaba
`RuntimeError` para «blocked»; como `NetworkDenied` ya no es `RuntimeError`
sino `RequestException` (decisión R2), con el código corregido el `PUT` caía en
`except requests.RequestException` y la prueba lo leía como «connect
attempted» aunque no abría ninguna conexión (su aserción sobre `connected`
pasaba). Ahora importa `NetworkDenied` de `test_support.local_strava` y la
captura en lugar de `RuntimeError` (antes de `RequestException`); el resto de la
prueba, y las otras seis, sin cambios. Las demás pasan tal cual: `test_r044_1`
(los dos arreglos de R1, cada uno basta), `test_r044_2` («HANDLED network»: ni
DEBUG ni 500), `test_r044_3`, `test_r044_5` (rechazo), `test_r044_6` y
`test_r044_7`.

**Mutaciones de las correcciones** (cada una quitada por separado, restaurada
con `/bin/cp -f` y SHA-256 idéntico): sin el envoltorio de `Session.send`
fallan `test_r044_4` y la prueba de red del hijo; con `NetworkDenied` derivada
de `RuntimeError`, la prueba del cliente de Garage y la de red; sin
`django.request`, `test_r044_3` y la de ajustes; sin la cookie propia,
`test_r044_6` y la de ajustes; sin `DJANGO_SETTINGS_MODULE` en el helper, la de
claves reenviadas; con `--settings` al final, las de argv; sin `diffsettings`
en `DENIED`, `test_r044_5` y los rechazos.

**Re-verificación** (helper de pruebas, 55434, en este orden): (1)
`tests_local_strava_review.py` + `tests_local_strava.py` +
`tests_test_environment.py`: 113 pasan (9 + 53 + 51, 8,04 s); (2) `manage.py
check --settings=strava_app.settings_test`: «System check identified no issues
(0 silenced).»; (3) `makemigrations --check --dry-run`: «No changes detected»;
(4) suite completa: **2752 pasan + 45 subcasos, 189,08 s**; (5) `inspect`: 0
bases residuales; (6) con valores sintéticos contra la demo 55433, sólo
`check`: las cuatro variables «definida» y «System check identified no issues
(0 silenced).», salida 0; `run diffsettings`: rechazo y salida 2. Nada
contra Strava real; `serve` no se ejecutó.

## 7. Cambio del 1 nov 2026: el helper lee las credenciales de `.env` (garage-048)

**Petición del usuario** (1 nov, al explicarle que con D4 tendría que pegar las
claves en la Terminal cada vez): «usa .env, sin miedo». Sustituye a D4 **sólo
en el helper**; el proceso hijo (`settings_local` + `install_local()`) no cambia.

- **D4'.1 Sólo el helper lee `.env`.** `tools/handoff/garage_local_strava.py`
  lee `<repo>/.env` (ruta cambiable sólo para pruebas con la variable
  `GARAGE_LOCAL_ENV_FILE`, como `GARAGE_DEMO_STATE`; no pasa al hijo) y toma
  **únicamente** `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` y
  `STRAVA_REFRESH_TOKEN`. Todo lo demás del archivo (hoy `DB_*`,
  `NEON_PASSWORD`, `CRONJOB_API_KEY`, `STRAVA_ACCESS_TOKEN`) se ignora y nunca
  llega al hijo (la lista de permitidos `ALLOWED` del helper no cambia).
- **D4'.2 Precedencia.** Una variable exportada y no vacía gana; si no, la de
  `.env` no vacía; si no, falta (salida 2 como hoy, sólo nombres).
- **D4'.3 El hijo sigue igual.** El gancho de auditoría sigue impidiendo abrir
  cualquier `.env`, `dotenv` sigue neutralizado y los tokens renovados **no** se
  escriben en `.env` (`utils._ENV_FILE` apunta a una ruta inexistente). Motivo:
  el escritor del legado reescribe el archivo entero, que contiene las
  credenciales de Neon; el refresh token es estable en la práctica (Render usa
  uno fijo desde junio).
- **D4'.4 Formato.** Líneas `CLAVE=valor`, con `export ` opcional, comillas
  simples o dobles emparejadas opcionales, CRLF tolerado, comentarios `#` y
  líneas vacías ignorados, comentario en línea ` #` en valores sin comillas (como
  python-dotenv), clave repetida ⇒ gana la última; líneas mal formadas se
  ignoran sin mostrarlas. Sin importar `dotenv` (el helper corre con el
  `python3` del sistema).
- **D4'.5 `.env` ausente o ilegible** ⇒ como si no tuviera valores (se usan las
  exportadas); `check` lo dice en una línea, sin traza.
- **D4'.6 Nunca valores en pantalla.** `check` muestra cada una como «definida
  (exportada)», «definida (de .env)» o «FALTA». Los mensajes dejan de decir
  «nunca desde .env».
- **D4'.7 Pruebas.** Ninguna prueba lee el `.env` real: las del helper usan
  siempre un archivo sintético o inexistente vía `GARAGE_LOCAL_ENV_FILE`, y una
  prueba lo garantiza.
- **Sin cambios:** la sincronización real la sigue lanzando el usuario (no la
  IA); `DENIED`, red, base de datos y `DEBUG = False` intactos.

## 8. Resultado de garage-048 (1 nov 2026; workflow `wf_0b9b17bf-945`, 4 agentes Opus)

**Implementación** (pruebas primero: 40 fallaban antes del cambio) en
`tools/handoff/garage_local_strava.py` (`env_file_values()`, `strava_values()`,
`report()` con el origen de cada clave; `.env` sólo se abre después de validar
acción, argumentos y estado de la demo, así que una orden rechazada nunca lo lee).
`test_support/local_strava.py` y `strava_app/settings_local.py`: sólo textos
(mensaje y docstrings); el hijo no cambia de comportamiento.

**Precisiones de formato (D4'.4):** un CR suelto también separa líneas (como
python-dotenv); BOM tolerado; bytes no UTF-8 sustituidos; sin expansión
`${VAR}`, sin escapes en comillas dobles ni valores multilínea; comilla sin
pareja ⇒ línea mal formada (vale la anterior de esa clave); sin comillas el
valor se recorta y « #» empieza comentario (`KEY= #c` ⇒ vacía); un valor con NUL
⇒ línea mal formada. Ruta que existe pero no es archivo normal (directorio,
FIFO, dispositivo) ⇒ «no se pudo leer», sin traza.

**D4'.7:** las fixtures `helper` y `review_helper` fijan `GARAGE_LOCAL_ENV_FILE`
a un archivo inexistente de `tmp_path` y se niegan a lanzar si falta o sale de
`tmp_path`; además `install_helper_launch_guard()` (gancho de auditoría sobre
`subprocess.Popen`, `os.system`, `os.exec*`, `os.posix_spawn`, `os.spawn`)
exige en cualquier lanzamiento del helper desde las pruebas una ruta absoluta
dentro del temporal, y un escaneo exige ese guardián en todo módulo de pruebas
que mencione el helper.

**Revisión adversarial** (dos revisores independientes: secretos y casos límite):
ninguna fuga de valores ni lectura del `.env` real encontrada. Hallazgos, todos
de severidad baja: FIFO como archivo ⇒ cuelgue (corregido); NUL en un valor ⇒
traza `ValueError` sin el valor (corregido, encontrado por los dos); faltaban
pruebas de valores entre comillas (añadidas, con mutaciones); D4'.7 sólo por
fixture y por texto (corregido con el guardián). **Pendiente de decidir por el
usuario (no corregido, anterior a 048):** el gancho que impide abrir `.env` en
el hijo (y el mismo patrón en `test_support/isolation.py`) compara el nombre
distinguiendo mayúsculas, y APFS no las distingue: `.ENV` abriría el `.env`.
Ninguna ruta actual usa esa variante. Propuesta: comparar con
`Path(...).name.casefold() == ".env"` en los dos módulos.

**Verificación** (re-ejecutada por la sesión principal): `tests_local_strava.py`
+ `tests_local_strava_review.py` + `tests_test_environment.py` 162 passed;
suite completa **2801 passed + 45 subtests** (198,6 s); `manage.py check` sin
problemas; `makemigrations --check` sin cambios. Informe:
docs/validation/garage-048.json. **Sin probar:** la ruta por defecto
`<repo>/.env` (ninguna prueba ni agente puede leer el `.env` real; lo comprueba
el usuario con `check`, que debe decir «definida (de .env)» en las tres) y
Strava real.
