# Helpers conservados para el relevo

Copias exactas de los helpers temporales ya usados el 10 octubre 2026, salvo
el helper de la demo (18 oct: deja pasar `GARAGE_STRAVA_USER`).
No son configuración de producción ni un nuevo servicio. Leen/guardan estado
en /private/tmp, usan PostgreSQL Homebrew 18 y rutas absolutas de este equipo.
No importarlos como librería: son scripts ejecutables con acción requerida.

- garage_test_pg.py: pruebas en 55434, base stravagancia_test_018.
- garage_demo_pg.py: demo en 55433, base stravagancia_test_demo.
- garage_local_strava.py (garage-044): demo 55433 con Strava **real** y
  `strava_app.settings_local`. Deja pasar sólo las 3 variables Strava: las
  exportadas o, si no, las de `.env` (garage-048: sólo esas tres claves del
  archivo; nunca imprime sus valores; las pruebas usan `GARAGE_LOCAL_ENV_FILE`).
  Acciones `check`, `serve [puerto]` (127.0.0.1:8767 por defecto; la demo con
  settings_test sigue en 8766) y `run <comando de manage.py>`; nunca pruebas,
  shell, dbshell ni diffsettings. Receta en TESTING.md, «garage-044»: el export
  de credenciales **solo** (sin pegarlo en un bloque con otras líneas), con un
  espacio delante y en su Terminal, nunca con `!` en Claude Code; al terminar,
  `unset STRAVA_CLIENT_ID STRAVA_CLIENT_SECRET STRAVA_REFRESH_TOKEN`.
- garage_bucket_check.py: prueba real de garage-010 contra un bucket privado ya
  autorizado. Sin Django, DB ni .env; lee sólo `~/.config/garage-s3-test.env`
  (chmod 600) e imprime OK/FALLO por paso. Ver docs/garage-photo-bucket-proposal.md.

Antes de usar: leer docs/garage-handoff.md y TESTING.md; comprobar archivos
de estado, directorios, procesos, puertos y rama. No llamar start si ya existe
estado, ni borrar un estado para forzar un inicio. Si los temporales faltan,
preparar un clúster nuevo y verificar su identidad.

El usuario/contraseña stravagancia_test son ficticios de estos clústeres.
El helper limpia el entorno heredado (salvo `GARAGE_STRAVA_USER`, que el de la demo
deja pasar a Django), fija credenciales sintéticas y usa settings_test
para acciones Django cuando se indica. No conectar con Neon ni leer/modificar .env.

Acciones:

- start: crea un clúster dedicado local y estado; necesita PostgreSQL instalado
  y puerto libre. No ejecutar sobre un clúster existente.
- run: ejecuta el Python de `GARAGE_TEST_PYTHON` (en macOS,
  ~/.cache/stravagancia/venv-macos/bin/python; el `.venv` del repo es de Linux
  desde el 16 oct y no se toca) con entorno local explícito. Usar python -m pytest
  en el helper de pruebas. Para gestionar Django indicar --settings=strava_app.settings_test.
  (Estas acciones son las de garage_test_pg.py y garage_demo_pg.py; las de
  garage_local_strava.py son check/serve/run.)
- inspect: muestra bases pytest residuales en el clúster exacto.
- coverage: **sólo helper de pruebas**. Hace check/migrations, suite completa y cobertura
  combinada de procesos; necesita coverage cached en la ruta que declara el script.
  Output actual full-020; elegir otro directorio antes de repetir para conservar evidencia.
- stop: comprueba bases residuales, detiene y **elimina sus datos temporales**.
  No usar en la demo: borra también el inventario real de `maxi` (id 2,
  importado de ProBikeGarage el 29 oct) y deja inválido su mapa
  mapping-demo-maxi-2026-10-29.json.
  Para sólo detener, usar pg_ctl con el directorio exacto tras verificarlo.

No ejecutar suites simultáneas en la misma base, pytest/coverage en la demo,
Docker Django ni gestión Django con settings de producción.
La opción coverage heredada del helper de demo no es autorización para usarla.

garage_test_pg.py y garage_demo_pg.py no son portables sin ajustar rutas de repo,
PostgreSQL y coverage. garage_local_strava.py deduce su repo de la ubicación del
propio archivo (no fijar REPO a mano); su estado por defecto sigue siendo una ruta
fija de macOS, así que en otro sistema no encuentra la demo sin `GARAGE_DEMO_STATE`.
Los comandos generales alternativos están en TESTING.md. No añadir credenciales
reales aquí.
