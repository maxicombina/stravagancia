# Pruebas locales aisladas

La suite requiere PostgreSQL real y un rol local dedicado con permiso `CREATEDB`.
No utiliza SQLite ni importa `strava_app.settings`. No necesita `.env`: no se lee
ni se escribe durante las pruebas. No arrancar el servicio Django de Docker,
que tiene configuración de producción.

Con Docker disponible, se puede crear exclusivamente PostgreSQL:

```bash
docker run --name stravagancia-test-postgres --rm \
  -e POSTGRES_DB=stravagancia_test \
  -e POSTGRES_USER=stravagancia_test \
  -e POSTGRES_PASSWORD=stravagancia_test \
  -p 127.0.0.1:55432:5432 -d postgres:17
```

Esperar a que `docker exec stravagancia-test-postgres pg_isready -U
stravagancia_test -d stravagancia_test` responda correctamente. Estas credenciales
son exclusivamente sintéticas para el contenedor local. Un PostgreSQL local ya
instalado también sirve si tiene el rol, la base dedicada y permiso `CREATEDB`.

Desde la raíz del repositorio, con las dependencias de desarrollo instaladas:

```bash
uv sync --group dev
uv run python -m pytest
uv run python -m pytest --collect-only -q
```

Usar la invocación `python -m pytest` indicada arriba: el proyecto no está
empaquetado y el ejecutable de consola `pytest` no garantiza que su raíz esté
en `sys.path` cuando se carga el plugin temprano. La invocación como módulo sí
incluye el directorio actual desde el arranque.

Los valores predeterminados son `TEST_DB_HOST=127.0.0.1`, `TEST_DB_PORT=55432`,
`TEST_DB_NAME=stravagancia_test`, `TEST_DB_USER=stravagancia_test` y
`TEST_DB_PASSWORD=stravagancia_test`. Se pueden establecer estas cinco variables
en el comando, sin usar `.env`. El host acepta únicamente `127.0.0.1` o `::1`;
el nombre debe ser `stravagancia_test` con sufijos opcionales de letras minúsculas
y números separados por `_`. Django crea y destruye `test_<TEST_DB_NAME>`.
El rol debe tener acceso a la base administrativa `postgres` para crear esa base.
No configurar este puerto mediante túneles o proxies hacia una base remota.

`DATABASE_URL`, `DB_*`, `PG*` y credenciales Strava heredadas se descartan antes
de importar la aplicación. Las credenciales Strava se sustituyen por valores
sintéticos. Settings alternativos mediante `DJANGO_SETTINGS_MODULE`, `--ds`,
`PYTEST_ADDOPTS` o `-o DJANGO_SETTINGS_MODULE=...` se rechazan. El plugin se carga
antes de pytest-django, también durante `--collect-only`. Mantener el `addopts`
del proyecto: no desactivar el plugin ni reemplazar la configuración pytest.

Se bloquean las solicitudes HTTP reales, las conexiones socket Python fuera del
endpoint PostgreSQL configurado y las conexiones libpq que cambien host, puerto,
base, rol o introduzcan opciones de destino. Simular HTTP en el punto de llamada
con `unittest.mock.patch`, como hacen las pruebas existentes. El bloqueo de `.env`
sigue activo aunque una respuesta HTTP esté simulada.

`uv run python manage.py test` también instala las protecciones antes de importar
settings. El runner Django recoge clases unittest, pero las pruebas actuales son
funciones pytest: ese comando no sustituye a `uv run python -m pytest` para ejecutar esta
suite. `--settings` de producción se rechaza. Otros comandos de gestión mantienen
su comportamiento habitual y quedan fuera del entorno de pruebas.

`test_strava_connection.py` es un script manual que llama a Strava al importarlo;
no forma parte de la suite y su colección explícita se rechaza. No usarlo para
verificar este entorno.

Estas protecciones evitan escapes accidentales en la suite; no son un sandbox
para código hostil, programas externos, UDP o cambios deliberados de los guards.
La suite usa configuración independiente sin WhiteNoise, validadores de contraseña
ni configuración de logging de producción. No verifica despliegue, integración
real de Strava/Neon, almacenamiento externo ni todos los controles de producción.
Para retirar el contenedor dedicado: `docker stop stravagancia-test-postgres`.

## Cobertura

Para un informe adicional reproducible sin añadir dependencias de runtime:

```bash
uv run --with pytest-cov==7.1.0 python -m pytest \
  --cov=test_support --cov=strava_app.settings_test --cov-branch --cov-report=term-missing
```

La medición de bootstrap se ejecuta en procesos hijos; el informe del proceso
principal por sí solo no representa todas esas ramas. Los tests de subprocess
comprueban sus resultados explícitamente. Si el entorno impide arrancar PostgreSQL,
`python -m pytest tests_test_environment.py -k 'not real_postgresql_database'` verifica el
bootstrap sin crear bases, pero no satisface la ejecución completa de la suite.

Los settings independientes conservan apps, autenticación Axes, middleware de
seguridad/sesiones/CSRF, templates, URLs y zona horaria del proyecto. Evitan importar
settings de producción porque ese import carga dotenv y evalúa `DATABASE_URL` antes
de que las fixtures puedan actuar. Un guard mínimo en `settings.py` rechaza su
import desde pytest incluso si se desactiva el plugin de aislamiento.

## Validación de garage-001 — 4 de octubre de 2026

- Colección: 144 casos, de los cuales 95 ya existían y 49 son nuevos.
- Suite completa: **144 pasaron, sin fallos, errores ni tests omitidos**, sobre
  PostgreSQL 18.6 local en `127.0.0.1:55432`. El entorno contenía `DATABASE_URL`,
  `DB_HOST` y `PGHOSTADDR` remotos sintéticos para comprobar su aislamiento.
- Se creó un clúster desechable con rol dedicado `LOGIN CREATEDB`, sin superusuario
  para la aplicación. Django creó y destruyó `test_stravagancia_test`; una consulta
  posterior confirmó cero bases de pruebas restantes. El servidor se detuvo y sus
  datos temporales se eliminaron al terminar.
- Dos revisores Sol adversariales comprobaron las protecciones y los tests; los
  fallos encontrados se corrigieron y tienen pruebas de regresión.
- Cobertura combinada de proceso principal e hijos: 95,74% de sentencias y 85% de
  ramas (93,37% conjunto) sobre
  `test_support`, `settings_test.py` y `manage.py`. Es una medición de estos archivos,
  no de toda la aplicación; las comprobaciones del audit hook de `.env` se ejecutan
  pero no quedan trazadas por coverage en este intérprete.
- Los 32 casos que requieren PostgreSQL están verificados. El bloqueo inicial del
  sandbox se resolvió habilitando ejecución autorizada. La comprobación de dirección
  usa `host(inet_server_addr())` para quitar el prefijo CIDR que devuelve PostgreSQL;
  se conserva la validación exacta de `127.0.0.1` o `::1`.

Para repetir la validación, arrancar el PostgreSQL dedicado indicado arriba y
ejecutar `uv run python -m pytest` desde un entorno que permita esa conexión local.

Si `uv` no está disponible, con un entorno virtual del proyecto ya preparado se
puede ejecutar `.venv/bin/python -m pytest`. Para cobertura, instalar únicamente
la herramienta de desarrollo en ese entorno con
`.venv/bin/python -m pip install 'pytest-cov==7.1.0'` y añadir los argumentos
`--cov` anteriores. Esta instalación opcional no cambia las dependencias de
runtime ni el lock del proyecto.

## Validación de garage-004 y tablero inicial

El inventario inicial pasó la suite completa de **305 pruebas** en PostgreSQL
18.6 local desechable: modelos, restricciones SQL, acceso privado, administración
y pruebas anteriores. `check` y `makemigrations --check --dry-run` no detectaron
problemas. El rol de aplicación no era superusuario; se comprobó que podía instalar
`btree_gist` en la base desechable para la siguiente entrega de montajes.

El tablero base pasó además 41 pruebas aisladas, sin base ni servidor HTTP; se
verificó en Chrome su renderizado, filtros y actualización automática. La ampliación
con detalle de tareas requiere su propia validación antes de darse por terminada.

## Validación de garage-005

Tras corregir los fallos encontrados, **478 pruebas de aplicación pasan** con
PostgreSQL 18.6 local desechable y sin tests omitidos. Esta ejecución excluyó
`tests_progress.py` porque el tablero estaba ampliándose en paralelo; no es una
medición de todo el código que se está escribiendo en este momento.

Se verificaron permisos por usuario en servicios, formularios y administración,
UUID ajenos e inválidos, propietarios falsificados, conflictos de categorías,
rollback, dos escrituras concurrentes reales y fechas UTC. Los tests también
cubren la corrección de una colisión entre el parámetro del servicio y el campo
comercial `model`, y el rechazo de fechas civiles donde se exige un instante.
La revisión adversarial aprobó el resultado. `check` y `makemigrations --check`
pasaron; no quedó ninguna base de pruebas y el servidor temporal se detuvo.

El tablero ampliado (`garage-028`) pasó **58 pruebas** sin base de datos, incluida
la proyección de detalles, sanitización, orden topológico, ciclos y dependencias
ausentes. Se comprobó en Chrome lista→detalle→dependencia, apertura desde nodos,
cierre con Escape y retorno del foco, motivo del cierre y 28 nodos del gráfico.
Estas 58 pruebas se ejecutaron separadamente de las 478 de aplicación mientras
se desarrollaban nuevas migraciones; no se presentan como una suite conjunta.

## Suite conjunta después de garage-006 y garage-009

**700 pruebas pasan, sin fallos ni omisiones**, en PostgreSQL 18.6 local
desechable. Incluye toda la aplicación, el procesador de fotos y el tablero.
`check` y `makemigrations --check --dry-run` no detectaron problemas.
La migración de montajes instala `btree_gist` con el rol sin superusuario.
Se comprobó que no quedan bases de pruebas, se detuvo PostgreSQL y se eliminó
su directorio de datos temporal. No se accedió a Neon.

Las carreras de servicios usan dos conexiones reales y el bloqueo del propietario:
se verifica un único ganador para posiciones, objetos, ciclos y sustituciones.
Al saltarse deliberadamente los servicios, dos INSERT concurrentes contra una
exclusión GiST pueden provocar que PostgreSQL aborte uno por deadlock (`40P01`).
El test acepta únicamente ese aborto o la exclusión concreta, exige una sola fila
y reintenta la operación perdedora después de cerrar ambas conexiones: ese
reintento debe fallar por la exclusión nombrada. No se añadieron reintentos ni
capturas genéricas a la aplicación. La explicación está en el
[código oficial de PostgreSQL](https://doxygen.postgresql.org/execIndexing_8c_source.html).

Cobertura de líneas y ramas conjunta: aproximadamente 95% sobre Garage, servicios,
tablero y protecciones de pruebas; no representa toda la aplicación antigua.
Formularios 100%, administración 99%, instalaciones 98%, propiedad 96%, fotos 94%
y tablero 91% en esa medición. Las líneas de arranque HTTP se comprobaron también
en Chrome; no se presentan como trazadas por pytest.

Fotos: Pillow 12.3.0 y codificador WebP reales verificados en el entorno local.
47 casos comprueban formatos, límites (15 MiB y 25 MP), orientaciones EXIF 1–8,
reescalado sin recortar/ampliar, transparencias, PNG de paleta, metadatos y errores.
La imagen del servidor Linux/Docker se comprobará en garage-023 antes del despliegue;
esta ejecución local no sustituye esa comprobación.

Corrección posterior del tablero: **61 pruebas aisladas pasan**. Se verificó en
la pestaña real del usuario que el HTML anterior era la causa de no ver enlaces
ni DAG. Tras añadir detección de revisión, un cambio temporal e inocuo del HTML
provocó recarga automática, mantuvo `garage-006` abierto y conservó la vista DAG
al cerrar. Se restauró el archivo original y se comprobó una segunda recarga.
El enlace superior Ver DAG lleva al gráfico; identificadores y títulos abren
los detalles. Esta corrección posterior a la suite conjunta de 700 pruebas
quedó integrada en la ejecución completa de 806 pruebas descrita abajo.


## Suite conjunta después de garage-007

**806 pruebas pasan, sin fallos, errores ni omisiones**, con PostgreSQL 18.6
local desechable. Incluye las 61 pruebas actuales del tablero, los montajes,
las fotos, las lecturas previas y toda la suite existente. `check` y
`makemigrations --check --dry-run` pasan; no quedan bases de prueba y el servidor
fue detenido y sus datos temporales eliminados. No se accedió a Neon.

Las lecturas se prueban por métrica y ámbito, con cortes independientes,
precisión decimal y correcciones que conservan UUID. Se verifican el intervalo
[C,T), la lectura exacta en C, el histórico anterior sin doble conteo, lecturas
futuras, desconocidos, cobertura parcial y estimaciones. Hay pruebas SQL,
aislamiento entre usuarios, dos carreras reales de escrituras y correcciones
del ancla de adquisición sin modificar compra, vida ni montajes.

Formularios y admin cubren medianoche en zona IANA explícita, cambios DST,
horas ambiguas o inexistentes y conversión UTC fuera de rango. El formulario
exige edición explícita para corregir una clave existente; el servicio conserva
su operación de crear o corregir. Revisión adversarial Sol aprobada.

Cobertura combinada de sentencias y ramas: aproximadamente 94% sobre Garage,
servicios, tablero y protecciones de pruebas; no equivale a toda la aplicación
antigua ni a cobertura completa. Servicios de lecturas 96%, instalaciones 98%,
formularios 88%, modelos 96% y tablero 92%. Los cálculos usan observaciones
sintéticas normalizadas: la conexión con ItemUsage e importaciones corresponde
a garage-016 y todavía no está implementada.


## Suite conjunta después de garage-008 y garage-011

**1002 pruebas y 12 subcasos pasan**, sin fallos ni omisiones, en PostgreSQL
18.6 local desechable. La migración 0004 es aditiva; `check` y comprobación de
migraciones pasan. No quedan bases de pruebas y el clúster de validación fue
detenido y eliminado. La demo de navegador usa otro clúster temporal independiente.

Ride, ActivitySource e ImportRun cubren propietario, identidad por hash/sesión,
precisión decimal, campos desconocidos, precedencia manual/FIT, retirada,
reactivación explícita e idempotencia que no modifica la prioridad de fuentes.
El progreso de importación cuenta sesiones intentadas, incluidos rechazos;
el cursor señala el prefijo contiguo confirmado y no supera processed. Hay
checks SQL y carreras reales con dos conexiones. Parser y uso por salida
permanecen en sus tareas siguientes; estos tests usan fuentes sintéticas.

La interfaz cubre acceso privado, CSRF, referencias ajenas, XSS, validación,
rollback de altas con lecturas, paginación, remontajes, sustitución, transferencia,
retiro/reactivación y DST. Los campos de fecha local usan texto ISO y conservan
microsegundos tanto al renderizar como al guardar.

Chrome verificó login/logout, creación de zapatillas usadas con 1000 km,
compra independiente, conversión Madrid→UTC, edición sin perder .123456,
reemplazo de sillín conservando A→B→A y un nuevo período B, y disposición
móvil sin desbordamiento horizontal (354 píxeles CSS medidos). Son datos
ficticios en la demo local, sin copiar actividades personales.

Cobertura combinada aproximada del alcance medido: 94%; servicios de salidas
97%, formularios web 95%, vistas 93%, modelos 92% y normalización de campos
de salidas 84%. No equivale a cobertura completa ni a la aplicación antigua.
Revisión adversarial aprobada. Se corrigió una colisión del parámetro owner
en un helper de pruebas para que el payload malicioso alcanzara la validación
real; no se ocultó ni eliminó el caso.

## Importación FIT y perfiles — 4 de octubre de 2026

Suite conjunta final: **1158 pruebas y 12 subcasos pasan** en 37,03 s, con
PostgreSQL 18.6 local desechable, rol sin superusuario, migraciones hasta 0005,
`check` sin incidencias y ninguna migración pendiente ni base de pruebas residual.
Artefactos: `/private/tmp/stravagancia-001-validation-5y94hyno`.

Se corrigió el error encontrado en un FIT truncado internamente con CRC válido:
la biblioteca lanzaba AssertionError. La frontera del decoder lo traduce y
comprueba los límites incluso con Python optimizado, sin ocultar errores propios.
La muestra original se validó en memoria con el código final; no se incorporó
al repositorio, a fixtures ni a la demo.

Cobertura de líneas y ramas del ámbito medido: 94% conjunto, parser FIT 99%,
servicios de perfiles 97%, vistas de perfiles 97%, formularios de perfiles 93%.
No equivale al 100% del producto ni incluye todo el código legado. Revisión Sol
adversarial de implementación y pruebas sin hallazgos pendientes.

Navegador con datos ficticios: perfil general de casco y zapatillas en dos bicis,
confirmación obligatoria para efectos históricos, exclusión individual por
salida, nueva versión desde ahora que conserva el material y la excepción del
pasado. La demo se migró conservando inventario y sesión mediante un respaldo
de su base PostgreSQL local independiente.

## Histórico, materialización y fotos privadas — 5 de octubre de 2026

La validación conjunta registrada en Beads y el tablero es de **1507 pruebas y
12 subcasos pasando**, con PostgreSQL 18.6 local desechable y migraciones hasta
0007. También constan `check`, comprobación de migraciones y `git diff --check`
sin incidencias. Las tareas 014 y 016 se cerraron tras revisión adversarial.

La integración local de fotos cubre almacenamiento simulado, propiedad, cuotas,
reemplazo, fallos y limpieza recuperable. Se conserva además el informe de
**267 pruebas enfocadas, sin fallos ni omisiones**, en
`/private/tmp/stravagancia-photo-validation-kui7tg7r/pytest.xml`. Este XML
corresponde solo a fotos: no es el artefacto de la suite conjunta. La comprobación
en un bucket privado real sigue pendiente y no está cubierta por estos resultados.

Los recuentos anteriores no acreditan cambios posteriores. La validación de
017 se recoge a continuación; consultar [el estado guardado](docs/garage-handoff.md)
para continuar con las dependencias disponibles.

## Intervenciones y reglas de mantenimiento — 6 de octubre de 2026

**1605 pruebas y 12 subcasos pasan**, sin fallos, errores ni omisiones, en
44,05 segundos con PostgreSQL 18.6 local desechable y migraciones hasta 0008.
Las 97 pruebas focales de mantenimiento y administración también pasan.
`check`, `makemigrations --check --dry-run` y `git diff --check` no detectaron
problemas. El rol de aplicación no era superusuario; no quedaron bases de
pruebas y el clúster se detuvo y sus datos se eliminaron.

Las pruebas verifican reglas independientes, importes y duraciones precisas,
lecturas desconocidas, referencias temporales y propiedad, incluido staff y
superuser. Compra y remontajes A → B → A conservan el uso desde la intervención.
La revisión adversarial Sol encontró un conflicto de borrado en administración:
una lectura o foto nueva después de comprobar referencias protegidas producía
un error 500. La corrección devuelve un mensaje controlado tras rollback;
el borrado masivo incluye en su transacción los logs de administración.
Ocho regresiones usan dos conexiones PostgreSQL reales y comprueban que la
referencia confirmada por la segunda conexión persiste, mientras se revierten
el primer borrado del lote y los logs de borrado. Revisión final aprobada.

Informes XML conservados en `/private/tmp/garage017-final-s0ln68yx/`:
`final-current.xml` (1617 casos contando subcasos) y `final-maintenance.xml`
(97 casos). El resumen duradero está en `docs/garage-validation.json`; las
rutas temporales pueden desaparecer al renovar el entorno.

No se midió cobertura instrumental de nuevo en esta ejecución; los porcentajes
anteriores siguen siendo evidencia de su propia versión, no del código final.
Las fotos usan almacenamiento simulado; la carrera del admin usa metadatos
sintéticos sin almacenamiento externo. No se probó el navegador en esta sesión,
ni Neon, bucket real o despliegue. Los avisos corresponden a `garage-018`.

## Avisos internos — 10 de octubre de 2026

Suite conjunta: **1640 pruebas y 12 subcasos pasan**, sin fallos ni omisiones,
en 87,93 segundos con PostgreSQL 18.6 local y rol sin superusuario. `check`,
comprobación de migraciones y diff pasan; no quedaron bases de pruebas.
018 no añade migración: el esquema sigue en 0008.

35 casos de avisos cubren umbrales exactos, referencias independientes, calendario
sin montaje, cobertura parcial, estimaciones, métricas desconocidas, lecturas por
evento y corte, valores máximos, DST, propiedad y GET sin escrituras. La prueba
con dos conexiones verifica con `pg_blocking_pids` que el lector está realmente
bloqueado por la mutación antes de liberarla y comprobar el snapshot final.

Revisión adversarial Sol aprobada. Chrome mostró con datos ficticios los estados
vencido, desconocido, próximo y vigente y referencias independientes de lubricación
y sustitución. La demo utiliza otra base en 55433; pytest solo accede a 55434.

Cobertura de sentencias y ramas del ámbito medido: aproximadamente 94%; servicio
de avisos 97%, admin 99%. No representa toda la aplicación antigua. Resumen
conservado en `docs/validation/garage-018.json`; XML y cobertura temporales en
`/private/tmp/garage018-validation-44qcqqna/full`.

## Validación garage-019 — 10 octubre 2026

32 pruebas focales de estadísticas y suite conjunta de **1672 pruebas + 12 subcasos**, todos aprobados, en 115,94 segundos. PostgreSQL 18.6 desechable en 55434, rol dedicado sin superusuario, configuración aislada y migración 0008. Django check, ausencia de migraciones pendientes, git diff --check y cero bases de pruebas residuales comprobados. Revisión adversarial Sol readonly aprobada.

XML conjuntos y cobertura: `/private/tmp/garage018-validation-44qcqqna/full-019/`; focales: `statistics.xml` en su directorio padre. Resumen duradero en `docs/validation/garage-019.json`. Cobertura del ámbito medido aproximada 94%, servicio estadísticas 98%; excluye pruebas, migraciones y buena parte del legado. Se verificaron en Chrome filtros de material compartido y ausencia de desbordamiento móvil; no son pruebas instrumentales de rendimiento.

Datos sintéticos, HTTP/almacenamiento simulados. No se acredita persistencia de fotos en un bucket real ni histórico real completo. Ratios costes/km requieren denominador completo y positivo, sin estimación y costes declarados conocidos; los subtotales por moneda son independientes. No se modificaron Neon, .env ni modelos/migraciones.

## Validación garage-020 — 11 octubre 2026

58 pruebas focales de exportación y suite conjunta de **1730 pruebas + 12 subcasos**, todos aprobados, en 78,54 segundos. PostgreSQL 18.6 desechable en 55434, rol dedicado sin superusuario, configuración aislada y migración 0008. Django check, ausencia de migraciones pendientes y cero bases de pruebas residuales comprobados (helper `tools/handoff/garage_test_pg.py coverage`). Revisión independiente con un subagente Claude de sólo lectura, aprobada tras corregir sus hallazgos de pruebas y documentación.

Casos de corrupción verificados por mutación: al quitar cada comprobación del servicio, su caso aislado falla. Cobertura del ámbito medido 94%; `garage/services/export.py` 99% (la única línea sin cubrir es una defensa que la restricción CHECK de la base de datos hace inalcanzable). XML y cobertura: `/private/tmp/garage018-validation-44qcqqna/full-020/`; focales en `export-final.xml` de su directorio padre. Resumen duradero en `docs/validation/garage-020.json`.

En la demo (8766) se comprobaron por HTTP la redirección sin sesión, la página, el JSON con remontaje A→B→A y lectura con valor, y el ZIP coherente con el manifiesto; no se repitió la comprobación visual en navegador. Datos sintéticos; no se modificaron Neon, .env ni modelos/migraciones.

## Validación garage-031 — 16 octubre 2026

Entorno nuevo tras el reinicio del equipo: `.venv` contiene ruedas Linux (lo
reconstruyó el contenedor Docker); en macOS se usa un entorno aparte creado con
`UV_PROJECT_ENVIRONMENT=~/.cache/stravagancia/venv-macos uv sync --frozen` y
`GARAGE_TEST_PYTHON` para los helpers. Clústeres PostgreSQL 18.6 recreados
(55434 pruebas, 55433 demo con `tools/garage_demo_seed.py`).

- Nuevas: `garage/tests_mobile_shell.py`, `tests_mobile_home.py`,
  `tests_mobile_item.py`, `tests_mobile_review.py` (90 casos).
- Suite completa: 1820 pruebas y 45 subcasos pasan (71 s); check, makemigrations y cero bases residuales.
- Dos revisiones independientes del código (031.1–.2 y 031.3–.4) con hallazgos corregidos y probados; JavaScript de la revisión de salidas comprobado en Chrome real.
- Mutaciones comprobadas en la revisión de salidas («Sin bici» explícito y
  candidatos montados): cada una hace fallar una prueba; archivo restaurado
  con hash idéntico.
- Capturas en Chrome sin interfaz a 390 px (iframes), claro/iPhone y
  oscuro/Android, de Inicio, Más, Añadir, Material, Taller, ficha, revisión y
  Salidas. Sin prueba en teléfono real (requiere HTTPS, garage-023).

## Validación garage-032 y garage-033 — 17 octubre 2026

Mismo entorno que 031 (`GARAGE_TEST_PYTHON` con el entorno macOS; PostgreSQL
18.6 en 55434 para pruebas y 55433 para la demo).

- Nuevas:
  - `garage/tests_mobile_workshop.py`: hora local, reglas en km/h, coma
    decimal, moneda, Taller, intervención.
  - `tests_mobile_bike.py`: ficha de bici y `?bike=`.
  - `tests_mobile_stats.py`: períodos, bordes de cambio de hora y de año,
    gráfico igual a las cifras, gasto, presupuesto.
  - `tests_mobile_lists.py`: listas, fechas locales, desbordamiento.
  - `tests_lifespan.py`: vida útil.
- Ajustes intencionados:
  - `tests_views.py`: cookie de zona UTC explícita.
  - `tests_maintenance.py`: «12,34» y «EUR».
  - `tests_mobile_item.py`: la bici ya tiene ficha propia.
- Suite completa: 1959 pruebas y 45 subcasos pasan (96 s). check y
  makemigrations limpios; `node --check` del JS.
- Revisiones independientes:
  - especificación de 032;
  - código de 032.1–.2;
  - código de 032.3–.4 con verificación de las correcciones anteriores.

  - código de 033 con verificación de la segunda ronda;
  - re-verificación final de 033: un 500 con zona horaria inválida y un aviso
    que faltaba.

  Todos los hallazgos se corrigieron con pruebas.
- Mutaciones: redondeo silencioso de km, reasignación de errores del modelo
  a km/h, moneda propuesta sin importe. Cada una hace fallar una prueba. El
  archivo se restauró con hash idéntico usando `/bin/cp -f`, porque el alias
  `cp -i` dejó un intento esperando confirmación.
- Capturas a 390 px en Chrome sin interfaz: Taller, formularios, intervención,
  ficha de bici, Salidas filtradas, Estadísticas (12 meses, este año, año
  pasado), listas, perfiles, histórico, exportar y vida útil, en claro/iPhone
  y oscuro/Android. Sin teléfono real.


## garage-034 a garage-038: ideas de ProBikeGarage (17–18 oct 2026)

Mismo entorno (`GARAGE_TEST_PYTHON` con el entorno macOS; PostgreSQL 18.6
desechable en 55434; demo en 55433). **Migración nueva 0009 (aditiva)**: aplicada
sólo en las bases locales de prueba (se crean en cada ejecución) y en la demo;
nunca en Neon.

- Pruebas nuevas:
  - `tests_snoozes.py` (034): modelo y restricciones, servicio (referencia
    guardada, sin solapes, doble toque, regla movida), cálculo (activo, agotado,
    lo primero que llega, uso desconocido, mínimo, otra referencia, bici),
    presentación, formulario y atajos sin JavaScript, pantallas, CSRF/405,
    exportación JSON y ZIP.
  - `tests_parts.py` (035): alcance por fecha y profundidad, registro conjunto
    atómico, lista que cambia con la fecha, destino fijo, ajenos e inválidos,
    añadir pieza con errores en español, consultas constantes.
  - `tests_service_usage.py` (036): antes/después por tipo, lecturas, uso
    desconocido, bici, intervenciones futuras, empates, comparar por categoría
    (marcas ≈/≥, días montado o desde la compra), textos y presupuestos.
  - `tests_retire_parts.py` (038): retirar con y sin lo montado (anidado), todo
    o nada, reemplazar retirando la que sale.
- Ajustes intencionados: presupuesto de consultas de la ficha de bici (34) y de
  componente (46); exportación con la tabla `snoozes`; «Cuánto dura cada uno» en
  la ficha de categoría.
- Suite completa tras 038: 2058 pruebas y 45 subcasos pasan (109 s); check y
  makemigrations limpios; `node --check` del JS.
- Revisiones independientes: especificación, código y re-verificación de 034 y
  035; especificación y código de 036 juntos; re-verificación de 036 con la
  revisión de 038. Hallazgos corregidos con pruebas (ver cada especificación).
- Capturas a 390 px (claro/iPhone y oscuro/Android): página de aviso y posponer,
  ficha con «Pospuesto», Inicio y Taller con pospuestos, ficha de rueda con
  piezas, casete anidado, añadir pieza, «También en esta visita», uso de una
  intervención, «Cuánto dura cada uno» y retirar con lo montado. Sin teléfono real.

## garage-030 fases 1–2: Strava en «modo token» (18 oct, con su revisión de código)

- Pruebas de Strava (HTTP simulado con cuerpos JSON en texto, datos sintéticos,
  PostgreSQL local): `garage/tests_strava_client.py` (19), `tests_strava_sources.py`
  (42), `tests_strava_sync.py` (36), `tests_strava_views.py` (20) y
  `tests_strava_migration.py` (1): 118 casos, 25 añadidos en la revisión.
- Lo que añadió la revisión: ajustes de producción leídos como código
  (`settings.py` no se importa bajo pytest); presupuesto de consultas por
  actividad en una página de 20 (≤ 15 nueva o unida a un FIT, ≤ 4 sin cambios;
  medido ≈ 12); «Sincronizar ahora» acotado (≤ 14 peticiones, ninguna tras el
  límite de tiempo); un 429/401 de los avisos falla la sincronización; avisos
  inservibles cerrados al quinto intento; 404 sin `activity:read_all` no borra;
  actividad de un aviso sin atleta o de otro; errores del trabajo acumulados;
  un trabajador por atleta con ronda extra; ninguna llamada a Strava con
  `connection.in_atomic_block` (prueba transaccional); «Quitar lo
  sincronizado» con un aviso en vuelo en otra conexión real (orden de
  bloqueos); FIT duplicado marcado; «Unir con…» conserva notas y excepciones
  y avisa antes; formularios de bicis sin N+1 y con etiqueta propia; estados
  y modalidades en español.
- Pruebas del legado: `strava_integration/tests.py`, 42 casos, pasan.
- Suite completa: **2201 pruebas y 45 subcasos pasan** (127 s, última ejecución); `check`,
  `makemigrations --check --dry-run` («No changes detected») y `inspect`
  (0 bases residuales).

## garage-041: categorías iniciales con icono (18 oct 2026)

- **Migración nueva `garage.0011_category_icon`** (aditiva: `Category.icon` y su
  CHECK de forma): sólo en las bases de prueba que se crean en cada ejecución;
  ni en la demo (55433) ni en Neon.
- `garage/tests_categories.py` (77 casos tras la revisión; eran 52): catálogo de iconos (cada clave tiene
  símbolo en el sprite), sugerencia por nombre (sin acentos ni mayúsculas, la
  palabra más específica gana), precedencia de `item_icon` (icono de la
  categoría → nombre del objeto → nombre de la categoría → «pieza»), validación
  del modelo y CHECK de la base, servicio idempotente sin distinguir mayúsculas
  (no toca las existentes ni a otros usuarios; bloqueo del propietario antes del
  único INSERT), mensajes, botón en Categorías, en Material vacío y en el
  formulario de objeto sin categorías (POST, CSRF, `next` en lista blanca),
  rejilla de iconos sin JavaScript, admin, exportación JSON/CSV, GET sin
  escrituras, presupuestos de las listas (constantes con 3 o 18 filas, ≤ 10
  consultas) y migración sobre filas existentes (reversible).
- Mutaciones comprobadas: comparar nombres distinguiendo mayúsculas y no dar
  prioridad al icono de la categoría hacen fallar 4 pruebas; archivos
  restaurados con hash idéntico.
- Primera entrega: 2253 pruebas y 45 subcasos (126 s).
- Revisión de código (spec §7), 25 casos nuevos:
  - «Según el nombre» guarda siempre `''`. Al editar sólo las notas de una
    categoría antigua no cambian ni el icono ni la vida útil orientativa de sus
    objetos.
  - «Te falta 1».
  - Cada radio de la rejilla sobre su casilla, y `<h2>`.
  - Alta o edición por `_resource_id`.
  - Una clave retirada de la lista no bloquea la edición, y el error del modelo
    sale en español.
  - Dos hilos pulsando el juego inicial a la vez. Juego inicial frente a
    «CADENA» manual, con espera comprobada en `pg_stat_activity`.
  - Empates por posición de la palabra.
  - Cambio visible respecto a la deducción anterior, y vida útil por icono (la
    llanta conserva la de la rueda).

  Mutaciones (congelar la sugerencia, quitar el bloqueo, desempatar por
  catálogo, usar `instance.pk`, conservar la clave omitida, quitar la
  traducción): cada una hace fallar pruebas nuevas. Los archivos se
  restauraron con hash idéntico.
- Tras la revisión: 2278 pruebas y 45 subcasos (125 s).
- Re-verificación (spec §8), 14 casos nuevos en `TestSuggestion` (91 en el
  archivo): la palabra escrita antes gana a la más larga («Llave de cadena» es
  herramienta, «Bolsa de sillín» bolsa, «Luz de casco» luz) y las claves casan
  como palabra completa con plural («Recambios», «Chubasquero», «Escalador» y
  «Discreto» no sugieren nada; «Discos 160», «discs» y «Neumáticos 28» sí).
- Suite completa: **2292 pruebas y 45 subcasos pasan** (124 s, última ejecución, 18 oct).
- `check`: sin problemas. `makemigrations --check --dry-run`: «No changes
  detected». `inspect`: 0 bases residuales.
- Capturas a 390 px (claro y oscuro) renderizadas con el cliente de pruebas, sin
  servidor ni base de demo; después, en la demo 8766 migrada a 0011.

## Validación garage-030 fase 3, mitad de pantallas (desnivel y potencia) — 18 octubre 2026

Mismo entorno (`GARAGE_TEST_PYTHON` macOS, PostgreSQL desechable en 55434; la
demo 55433/8766 no se tocó ni se migró). Sin migración nueva: la 0012 es de la
mitad de datos.

- Nuevas: `garage/tests_elevation_screens.py` (42 casos). Reglas por desnivel
  (primero alcanzado, 90 % ⇒ «Revisar» con histórico parcial y «próximo» sólo
  completo, referencia de la última intervención del mismo tipo, objeto con su
  `ItemUsage`); aplazamientos (activo, alcanzado con su texto exacto,
  desconocido cuando una salida no tiene desnivel y su explicación, distinta del
  uso sin calcular); formularios en metros enteros (regla, vida útil, posponer,
  atajo «10 %», valor con decimales conservado); estadísticas por bici, objeto y
  mes y la página con `?chart=elevation` (mismas consultas); pantallas
  (desnivel en Salidas, Histórico, Inicio, bici, objeto, intervención y efecto de
  la revisión; potencia sólo en revisión y detalle; nada si es nulo; sin
  `<script>` ni `style=`); presupuestos de consultas constantes al añadir salidas
  con desnivel; los cuatro menores de fases 1–2 (última ronda, lote lleno,
  tiempo máximo con el timeout recortado, `sport_label` en perfiles) y un lote
  lleno que no confirma ninguno no se repite en el acto.
- Ajustadas: `tests_mobile_stats` (cuatro métricas), `tests_snoozes` y
  `tests_lifespan` (clave `elevation_gain_m`), `tests_mobile_workshop` y
  `tests_lifespan` (mensajes que nombran el desnivel).
- Mutaciones (cada una hace fallar pruebas nuevas; archivos restaurados con
  hash idéntico): consumir la petición de otra ronda en la última, lote nunca
  lleno, no recortar el timeout, aceptar un mínimo de desnivel en aplazamientos,
  quitar `sport_label`, no pausar la importación cortada, repetir un lote lleno
  sin progreso.
- Presupuestos de consultas existentes: sin cambios (los `.only()` y agregados
  incluyen el desnivel; ninguna consulta nueva).
- Suite completa: **2429 pruebas y 45 subcasos pasan** (153 s, 18 oct; antes
  de esta mitad, 2387). `check`: sin problemas. `makemigrations --check
  --dry-run`: «No changes detected». `inspect`: 0 bases residuales.
- Capturas a 390 px (claro y oscuro) renderizadas con el cliente de pruebas en
  iframes de 390 px y Chrome sin interfaz, sin servidor ni base de demo:
  revisión con potencia, Salidas, bici, objeto, Estadísticas (km y desnivel),
  posponer, vida útil, regla, Inicio e intervención.

## Validación garage-030 fase 3, revisión de código — 18 octubre 2026

Mismo entorno (`GARAGE_TEST_PYTHON` macOS, PostgreSQL desechable en 55434; la
demo 55433/8766 no se tocó ni se migró). Ninguna migración nueva ni editada: la
0012 sigue igual.

- Nuevas: `garage/tests_elevation_review.py` (39 casos): «1.000», «20.000»,
  «1.000.000», «20 000» (espacio, duro y fino) son metros en regla, posponer y
  vida útil; «1.5», «1,5», «2,000», «1.000,0», «0.500», «1.0», «1e3»… se
  rechazan sin truncar; salidas, días y tiempo leen también los miles; los
  campos son texto con teclado numérico (no `type="number"`) y el admin no
  cambia; el timeout de conexión + lectura nunca supera lo que queda (9 valores)
  y sin prisa sigue siendo `(5, 20)`; un intervalo sin ninguna salida con
  desnivel es «Sin datos» (no 0) con su motivo en el Taller y su nota en
  Posponer, un intervalo vacío sigue siendo 0, la distancia no cambia, un
  intervalo parcial dice «N sin desnivel» en la fila, el objeto y Posponer, y
  Estadísticas (filas y gráfico) e Inicio marcan el mínimo «↑ ≥».
- En `tests_elevation_power.py`: un campo opcional FIT repetido, en coma
  flotante o en lista queda desconocido y el archivo se importa (sustituye a la
  prueba que esperaba `fit_duplicate_field`); un campo original repetido sigue
  rechazándolo.
- Ajustadas en `tests_elevation_screens.py`: mensaje «sin decimales (1500 o
  1.500)», clase `WholeNumberInput`, «1.500» ya no se rechaza (7 casos de
  rechazo), timeout `(1,75, 1,75)` para 3,5 s y suma ≤ 10 s, regla de gravel
  sin desnivel ⇒ «Sin datos», «↑ ≥» en Estadísticas e Inicio.
- Mutaciones (cada una hace fallar pruebas; archivos restaurados con hash
  idéntico): sin leer miles (9 fallos), FIT opcional estricto (2) y repetido
  rechazado (2), timeouts recortados por separado (10), sin `unrecorded` (3),
  sin «≥» en Inicio (2), sin nota en la fila (1), sin motivo en el Taller (1),
  sin recuento en el gráfico (1).
- Presupuestos de consultas: sin cambios (el recuento de Inicio va en el mismo
  agregado; el del gráfico sale de los meses ya leídos).
- Suite completa: **2473 pruebas y 45 subcasos pasan** (168 s, 18 oct; antes de
  la revisión, 2429). `check`: sin problemas. `makemigrations --check
  --dry-run`: «No changes detected». `inspect`: 0 bases residuales.

## Validación garage-030 fase 3, re-verificación — 18 octubre 2026

Mismo entorno; ninguna migración nueva ni editada. La re-verificación
independiente (Opus) confirmó los cuatro arreglos de código de la revisión y
dejó dos hallazgos nuevos menores, corregidos por el orquestador:

- `garage/tests_elevation_review.py` (+1, 40 casos): una regla cuyo desnivel
  tiene decimales (puesto desde el admin) muestra en el teléfono «1.234,5» en
  un `DecimalInput` con teclado decimal; «2.000» se rechaza como ambiguo (antes
  el `DecimalField` del modelo lo leía como 2 m); «1.234,5», «1234.5» y
  «2.000,0» se leen bien; «1,2345» da «Como máximo 3 decimales.»; guardar un
  valor entero vuelve al campo de metros enteros.
- Suite completa: **2474 pruebas y 45 subcasos pasan** (18 oct; antes de la
  re-verificación, 2473). `check`: sin problemas. `makemigrations --check
  --dry-run`: «No changes detected». `inspect`: 0 bases residuales.
- Demo 55433 migrada a `0012_elevation_power` y servidor 8766 reiniciado con el
  código final; las fichas de las dos bicis, Salidas, Estadísticas y el
  formulario de regla responden 200.

## Validación garage-030 fase 4, operación diaria — 18 octubre 2026

Mismo entorno (`GARAGE_TEST_PYTHON` macOS, PostgreSQL desechable en 55434; la
demo 55433/8766 no se tocó ni se migró: sigue en `0012_elevation_power`).
Ninguna migración nueva: la siguiente sigue siendo la 0013.

El Worker de Cloudflare se prueba con Node (v24), sin red ni Cloudflare:

```bash
node --check keepalive/cloudflare-worker.js
node --test keepalive/worker.test.mjs
```

`worker.test.mjs` sustituye `fetch`, `Date`, `setTimeout` (inmediato, anota el
retardo) y `AbortSignal.timeout` (anota el plazo) y captura `console.log`; la URL
y el token son sintéticos. Nunca usar wrangler ni desplegar desde aquí.

- Mitad de servicio: `garage/tests_strava_operation.py` (45 casos en la entrega: endpoint
  404/403/405/200, `sync_all`, ausencia, revocación y purga a 29/30/31 días,
  comandos, registro sin token).
- Worker, `keepalive/worker.test.mjs` (34 casos en la entrega; 39 tras la revisión, abajo): el cron de keep-alive sigue
  igual (GET a `/healthz/`, UA curl, 4 intentos a 20 s, 120 s, «skip» antes de
  las 09) y nunca llama a la sincronización; un cron desconocido hace el
  keep-alive; el handler `fetch` sólo hace ping; el cron `5 7,8 * * *` sólo
  actúa a las 09 de Madrid en verano, en invierno y los dos días de cambio de
  hora, y exactamente una de las dos horas UTC actúa cada día de 2026; cada
  llamada es un POST sin cuerpo con `X-Sync-Token`, UA `curl/8.7.1` y 45 s;
  2 s entre llamadas; para en `pending 0`, en `error`, en respuestas no 200
  (403, 404, 405, 500, 502, 201), en una llamada agotada o fallida, en un JSON
  inesperado (7 formas) y a las 6 llamadas; sin `SYNC_URL`/`SYNC_TOKEN` (o
  vacíos, o sin `env`) no llama y sólo nombra lo que falta; ningún registro
  contiene el token ni la URL; el Worker y su README no contienen nada con
  forma de token ni una URL real de Render.
- Pantalla, `garage/tests_strava_views.py` (+9): «Sincronización automática:
  configurada…» con 32 o más caracteres y «no configurada (falta
  GARAGE_SYNC_TOKEN).» vacío o con 31, nunca el valor; sin cuenta, «a partir de
  la primera sincronización manual»; nada para otro usuario o sin
  `GARAGE_STRAVA_USER`; el aviso de revocación con las dos fechas en la zona de
  quien mira (23:30 UTC del 28 feb ⇒ «1 mar»), en lugar del texto genérico de
  `unauthorized` y junto a otro error (429); sin aviso de purga sin revocación
  ni para una cuenta que no es del propietario configurado; un 401 persistente
  desde el botón lo muestra; mismas consultas (≤ 20) con y sin aviso, sin
  escrituras ni HTTP, sin `<script>`, `style=` ni `onclick=`.
- Mutaciones (cada una hace fallar pruebas; archivos restaurados con hash
  idéntico). Worker: sin la puerta de las 09 (5 fallos), K = 7 (1), sin pausa
  (3), ignorar `error` (1), aceptar 4xx (4), timeout de 120 s (2), sincronizar
  con cualquier cron (3), registrar el mensaje del error (2), sin comprobar
  `env` (5). Pantalla: sin sustituir el texto genérico (1), aviso para cualquier
  propietario (1), purga a 29 días (1), «configurada» siempre (2), fecha en UTC
  (1).
- Suite completa de la entrega (antes de la revisión, abajo): **2528 pruebas y 45 subcasos pasan** (166 s, 18 oct; antes de
  esta mitad, 2519). `check`: sin problemas. `makemigrations --check
  --dry-run`: «No changes detected». `inspect`: 0 bases residuales.
- Capturas a 390 px (claro y oscuro) de Más → Strava renderizadas con el
  cliente de pruebas en iframes de 390 px y Chrome sin interfaz, sin servidor ni
  base de demo: sincronización automática configurada, y cuenta revocada con la
  sincronización automática sin configurar.

### Revisión de código de la fase 4 (18 oct)

Correcciones de los 9 hallazgos (spec §5), cada uno con pruebas:

- `garage/tests_strava_operation.py`: 64 casos (antes 45; se sustituyen los 3
  de 29/30/31 días y se añaden 22). Purga sólo si Strava sigue rechazando el
  token en esa ejecución (renovación y dos `GET /athlete`), en la fecha de
  Madrid mostrada (primavera, otoño, revocación tras medianoche, días después,
  31 días) y nunca el día anterior (incluido uno con más de 30 días exactos);
  token que vuelve a valer ⇒ sin purga y marca anulada; red, 429 o 5xx ⇒ sin
  purga ese día y marca intacta; un `network`, `rate_limited` o
  `invalid_response` no reinicia ni anula la marca; un 403 en un aviso o un 401
  en las actividades tras aceptar el token no marcan la cuenta (con y sin
  revocación previa de 31 días); «Quitar lo sincronizado» antes de la
  ejecución, durante `GET /athlete` o durante la página ⇒ `idle` sin escribir
  nada ni volver a crear la cuenta; página 500 con DEBUG sin el token; el
  bloque «Despliegue» de docs/garage-handoff.md pide comprobar
  `activity:read_all`, restaurar `TARGET` y un `SYNC_URL` https con barra.
- `garage/tests_strava_views.py`: +5 (34 en el archivo): fecha de borrado =
  `purge_date` (11 oct ⇒ 10 nov, no 9 nov; 10 oct ⇒ 9 nov; 20 mar ⇒ 19 abr) y,
  sin `GARAGE_SYNC_TOKEN` (vacío o de 31), el aviso no promete un borrado
  automático.
- `keepalive/worker.test.mjs`: 39 casos (+5): `redirect: "manual"` en cada
  llamada; un 301, 302, 307 o 308 para con su código tras una sola llamada; el
  README pide sustituir `TARGET` antes de Deploy y un `SYNC_URL` https con
  barra final.
- Mutaciones (todas hacen fallar pruebas; archivos restaurados con hash
  idéntico): purgar antes de comprobar el token (11 fallos), anular la marca en
  cualquier final (5), ignorar si el token se aceptó (4), regla `≥ 30 días`
  (2), fecha de borrado UTC + 30 días (4), la ejecución diaria puede crear la
  cuenta (3), el token como variable local de la vista (1), «automáticamente»
  siempre (2), el Worker sigue redirecciones (5).
- Suite completa: **2552 pruebas y 45 subcasos pasan** (176 s). `node --check`
  correcto, `node --test` 39/39. `check`: sin problemas. `makemigrations
  --check --dry-run`: «No changes detected» (12 migraciones). `inspect`: 0
  bases residuales.

### Re-verificación de la fase 4 (18 oct)

Verificador Opus independiente (sólo lectura y pruebas): los 9 arreglos de la
revisión, verificados uno a uno contra el código y sus pruebas; `ready`. Hallazgo
nuevo: `garage/tests_elevation_screens.py` afirmaba `"kJ" not in html` sobre la
página entera, y el token CSRF (64 caracteres aleatorios) contiene «kJ» en un
pequeño porcentaje de ejecuciones (una suite completa falló así: 1 fallo, 2551
aprobadas; la siguiente, limpia). Las dos aserciones pasan a `<span>kJ</span>`.
Nimiedad documentada, sin cambio: con sincronización automática y la fecha de
purga ya pasada sin ejecución, el aviso sigue diciendo «automáticamente el
<fecha>».

Suite completa final (orquestador, una sola ejecución, 55434): **2552 pruebas y
45 subcasos pasan** (169,63 s). `check`: sin problemas. `makemigrations --check
--dry-run`: «No changes detected». `inspect`: 0 bases residuales. `node --check`
correcto; `node --test keepalive/worker.test.mjs` 39/39. Demo 8766 reiniciada
con el código final (118 páginas 200; Más → Strava capturada en claro y oscuro).

Arreglos de herramientas del mismo día (agentes Opus), con su suite completa:
el tablero `tools/garage_progress.py` acepta los ids jerárquicos de las
subtareas de Beads (`garage-NNN.N`; antes `/state.json` respondía 503) con
`tests_progress.py` ampliado (85 casos en el archivo); el helper de la demo deja
pasar `GARAGE_STRAVA_USER`, `strava_app/settings_test.py` la lee y, bajo pytest,
`test_support/isolation.py::install()` la vacía junto con `GARAGE_SYNC_TOKEN`
(`tests_test_environment.py` +2). Suite completa: **2578 pruebas y 45 subcasos
pasan** (179,19 s). `check`, `makemigrations --check --dry-run` e `inspect`
limpios. Demo 8766 reiniciada con `GARAGE_STRAVA_USER=demo`: Más → Strava
muestra el panel Estado, «Sincronizar ahora» y el histórico.

## garage-042: ciclo de vida del material visible — 18–19 octubre 2026

Flujo de agentes Opus (Fable orquesta, sin tocar código): implementación →
revisión independiente → corrección → verificación. Spec
`.claude/specs/2026-10-18-garage-ciclo-vida-material-spec.md` (§6 decisiones,
§7 revisión, §8 re-verificación); informe `docs/validation/garage-042.json`.

- Nuevo `garage/tests_lifecycle.py`: derivación de cada estado (retirada futura,
  montaje terminado en `at`, perfil terminado o aún no empezado, pieza anidada
  con y sin bici raíz, «Sin estrenar» frente a «Disponible» tras desmontar, tras
  una lectura previa, tras un perfil pasado y tras una inclusión por excepción);
  filtro en base de datos comparado con el servicio en 8 instantes; filas de otro
  propietario nunca cuentan; textos de fila y chips; `active` y valores
  inválidos; paginación que conserva el filtro; presupuestos de consultas
  (Material ≤ 7; ficha suelta ≤ 44 sin crecer con 10 piezas, perfiles o
  lecturas más; categoría ≤ 28).
- Actualizadas `tests_mobile_home.py`, `tests_mobile_lists.py`,
  `tests_mobile_item.py` (ficha montada ≤ 47) y `tests_parts.py` («Sobre …»).
- Revisión: 8 hallazgos, 7 corregidos con prueba, 1 rechazado con motivo.

Suite completa (verificador, 55434): **2618 pruebas y 45 subcasos pasan**
(183,91 s; el implementador 2605 y el corrector 2618). `check`: sin problemas.
`makemigrations --check --dry-run`: «No changes detected»; migraciones 0001–0012,
ninguna nueva. `inspect`: 0 bases residuales. Nada en staging.

## garage-043: importar el estado de ProBikeGarage — 25 octubre 2026

Implementación (agente Opus; Fable orquesta). Spec
`.claude/specs/2026-10-25-garage-probikegarage-import-spec.md` (§9: decisiones
de la implementación). Sin migración: siguen 0001–0012 y la 0013 queda reservada.

- Nuevo `garage/tests_probikegarage_import.py` (65 pruebas). Todos los volcados
  se construyen en la propia prueba (`synthetic_dump()`): una bici con su bici de
  Strava, componentes activos, retirados y anidados (calas en pedales,
  rodamientos en un buje), un montaje «desde siempre», uso inicial (con desnivel,
  que se avisa), intervalos de los cinco tipos con y sin repetición, tres «Max
  life» combinados en una vida útil, una intervención con tres intervalos y dos
  componentes, otra sin intervalo, nombres duplicados y salidas para verificar.
  El volcado real del usuario **no** se lee en la suite ni se copia a fixtures.
- Cubre: mapeo de tipos a categorías (incluido «other» por nombre y tipos
  desconocidos → «Otros»), coherencia con los iconos del juego inicial de
  garage-041; días enteros de `elapsed-time`; 22 rechazos de validación (versión,
  formato, referencias rotas, también con valores que no son texto, solapes,
  fin ≤ inicio, instante sin zona, `value` ≤ 0, tipo desconocido, títulos
  repetidos, nombre vacío, montaje posterior a la retirada, ciclo de anidados,
  id repetido, fecha nula en una intervención, bici de una salida ambigua,
  «desde siempre» sin referencia) siempre sin escribir y con tabla, id y nombre; Garage no vacío; `--dry-run` sin
  INSERT/UPDATE/DELETE (`CaptureQueriesContext`) y con un número **constante**
  de lecturas (≤ 6) sea cual sea el tamaño del volcado; coste de la aplicación
  lineal y constante por fila (cada escritura es una llamada de servicio, ≤ 130
  consultas por componente con su montaje, regla, intervención y lectura);
  atomicidad (fallo tardío simulado y una fila rechazada por un servicio ⇒ cero
  filas, con la fila nombrada); filas creadas (marca/modelo, `StravaGear`
  vinculado, notas, sin posiciones, anidados, nota «desde siempre», retiradas
  después de sus montajes y montajes abiertos cerrados al retirar); reglas,
  vida útil combinada y heredable (`inherit_lifespan`); intervenciones
  conjuntas, prefijo del título en las notas y tipos únicos sin mayúsculas;
  lecturas estimadas con su fuente y corte; reutilización de categorías y tipos
  existentes y separación entre propietarios; un solo uso; el logger `garage`
  sólo recibe recuentos; totales de uso con `create_manual_ride` +
  `rebuild_usage`; `maintenance_due` ve la referencia de las intervenciones
  importadas; la verificación sin escrituras («0 de N salidas…» antes de Strava,
  «Sin diferencias.» tras el histórico de Strava, con y sin mapa, también si el
  histórico de Strava se importó antes que el volcado, y las diferencias
  previstas); el mapa se guarda fuera del repositorio, nunca sobrescribe, con
  permisos 0600 y sin nombres ni notas.
- Comandos: `manage.py garage_import_probikegarage <volcado> --owner <id>
  [--dry-run] [--mapping <archivo nuevo fuera del repo>] [--zone <IANA>]` y
  `manage.py garage_probikegarage_verify <volcado> --owner <id> [--mapping
  <archivo>] [--zone <IANA>]`.
- Previsualización del volcado real (sólo `--dry-run`, base local
  `stravagancia_test_018` del clúster 55434): 0 errores y 6 avisos (el montaje
  «desde siempre», dos intervenciones sin intervalo que en Garage reinician la
  regla de su mismo tipo, dos piezas retiradas con uso inicial y vida útil —tras
  la revisión, R043-6— y un desnivel inicial que no se guarda); 0 filas
  escritas. Una importación sintética del mismo tamaño, medida por el revisor
  con `connection.execute_wrapper`: 6.145 consultas (0,8 s) en un Garage vacío y
  18.065 (~3,5 s) con 300 salidas de Strava ya importadas, porque cada montaje y
  cada retirada reconstruyen todas las salidas (la cifra «~9.000» de antes era el
  tope `queries_limit` de `CaptureQueriesContext`, no una medida).
- Revisión independiente (spec §10): 7 pruebas nuevas en
  `garage/tests_probikegarage_review.py` (`test_r043_1`…`test_r043_7`), una por
  hallazgo; corregidas por el implementador (spec §11).
  `tests_probikegarage_import.py` + `tests_probikegarage_review.py`: **72 pasan**.

- Re-verificación (spec §12): cada `test_r043_n` falla si se quita su corrección
  (7/7, mutación temporal restaurada con SHA-256 idéntico); casos límite sondeados
  sin defectos de código; un texto de §13 del dominio precisado (R043-12).
  Informe `docs/validation/garage-043.json`.

Suite completa (re-verificador, 55434): **2690 pruebas y 45 subcasos pasan**
(219,22 s; el implementador 2683 antes de las 7 pruebas de revisión; antes de
garage-043, 2618). `check`: sin problemas. `makemigrations --check --dry-run`:
«No changes detected»; migraciones 0001–0012, ninguna nueva. `inspect`: 0 bases
residuales. Nada en staging.
