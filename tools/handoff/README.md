# Helpers conservados para el relevo

Copias exactas de los helpers temporales ya usados el 10 octubre 2026, salvo
el helper de la demo (18 oct: deja pasar `GARAGE_STRAVA_USER`).
No son configuración de producción ni un nuevo servicio. Leen/guardan estado
en /private/tmp, usan PostgreSQL Homebrew 18 y rutas absolutas de este equipo.
No importarlos como librería: son scripts ejecutables con acción requerida.

- garage_test_pg.py: pruebas en 55434, base stravagancia_test_018.
- garage_demo_pg.py: demo en 55433, base stravagancia_test_demo.
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
- run: ejecuta Python de .venv con entorno local explícito. Usar python -m pytest
  en el helper de pruebas. Para gestionar Django indicar --settings=strava_app.settings_test.
- inspect: muestra bases pytest residuales en el clúster exacto.
- coverage: **sólo helper de pruebas**. Hace check/migrations, suite completa y cobertura
  combinada de procesos; necesita coverage cached en la ruta que declara el script.
  Output actual full-020; elegir otro directorio antes de repetir para conservar evidencia.
- stop: comprueba bases residuales, detiene y **elimina sus datos temporales**.
  No usar en la demo si se quiere conservar el inventario ficticio.
  Para sólo detener, usar pg_ctl con el directorio exacto tras verificarlo.

No ejecutar suites simultáneas en la misma base, pytest/coverage en la demo,
Docker Django ni gestión Django con settings de producción.
La opción coverage heredada del helper de demo no es autorización para usarla.

No son portables sin ajustar rutas de repo, PostgreSQL y coverage; los comandos
generales alternativos están en TESTING.md. No añadir credenciales reales aquí.
