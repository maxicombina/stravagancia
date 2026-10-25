# Estado de Garage para Claude u otra IA

Actualización: 25 de octubre de 2026, Claude. Empezar por CLAUDE.md y
garage-context.md; no rediseñar el proyecto ni ignorar cambios locales. Rama
codex/garage-plan: desde el 25 oct, **un commit sobre main** (`5e422c8`, todo el
trabajo de Garage, pedido por el usuario); sin push. Fuera del commit, a
propósito: `metabase-data/metabase.db/metabase.db.mv.db` (base binaria
modificada por Metabase, ya ignorada pero rastreada) y `.serena/` (caché de
herramienta). Los dos commits del legado en `main` (`dd607f6`, `45a7cf6`)
siguen sin integrar (sección «Siguiente paso», punto 7).

## Aviso importante: migraciones de Garage aplicadas en producción (Neon)

El 12 oct a las 16:15 (hora de Madrid) se creó el contenedor Docker
`stravagancia_django` junto con el de Grafana (`docker compose up`). Su
entrypoint ejecuta `migrate` contra la base de producción (DATABASE_URL de Neon
en docker-compose.yml) y, al montar el repositorio con Garage, aplicó
`garage.0001`–`0008` en Neon. Lo muestran los registros locales de Docker. No
lo hizo ninguna IA, y nadie consultó ni escribió en Neon para verificarlo.
Consecuencias:

- Las migraciones `garage.0001`–`0008` **no se pueden editar ni reordenar**; las
  nuevas deben ser aditivas.
- No volver a levantar el servicio `web` de docker compose (sólo `grafana` si
  hace falta): ejecutaría `migrate` en producción con lo que haya en el repo.
  **Desde el 18 oct hay cuatro migraciones locales que no están en Neon**:
  `garage.0009_maintenancesnooze` (garage-034), `garage.0010_strava_source`
  (garage-030 fases 1–2), `garage.0011_category_icon` (garage-041) y
  `garage.0012_elevation_power` (garage-030 fase 3). Levantar `web` las
  aplicaría allí. `CLAUDE.md` («Retomar ahora») las nombra y dice que la
  siguiente es la 0013.
- La 0012 **no es sólo aditiva**: sustituye los CHECK
  `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` por
  versiones que aceptan el desnivel (las filas actuales los cumplen). Hay que
  decírselo al usuario explícitamente y que lo apruebe antes de desplegarla
  (garage-023).
- Pendiente del usuario: decidir si deja esas tablas (vacías, inofensivas para
  la app antigua) o si autoriza revertirlas, y si cambia docker-compose para que
  `web` no migre contra Neon.

El mismo contenedor reconstruyó `.venv` el 13 oct con paquetes **Linux**
(`/usr/local/bin/python3.11`, `*.cpython-311-aarch64-linux-gnu.so`). Ese `.venv`
pertenece ahora a la imagen Docker: no tocarlo. Para trabajar en macOS hay un
entorno aparte creado con `uv sync --frozen`:

```bash
export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
```

Los helpers `tools/handoff/garage_{test,demo}_pg.py` usan esa variable si existe.

## Última entrega: garage-043, importar ProBikeGarage (25 oct, en curso)

El usuario quiere **migrar sus datos de ProBikeGarage** a Garage y replicar el
estado (material con fecha de instalación, km, horas, desnivel, intervalos,
intervenciones, salidas); «si hay que re-bajar de Strava, se re-baja».
Especificación con el mapeo y las decisiones D1–D12:
`.claude/specs/2026-10-25-garage-probikegarage-import-spec.md`. Bead
`garage-043` (depende de 030). **Sin migración** (la 0013 sigue reservada).

- **Volcado hecho el 25 oct** desde el Chrome del usuario con su sesión
  (extensión Claude in Chrome; sólo `GET` a `api.probikegarage.com`; no se
  cambió nada en ProBikeGarage; la pestaña se cerró al terminar). Archivos en
  `~/.cache/stravagancia/probikegarage/` (**fuera del repo; datos personales:
  nunca a fixtures, docs ni demo**): `probikegarage-2026-10-25-compact.json`
  (formato v2 que lee el importador; 2 bicis, 50 componentes —19 retirados,
  que la API oculta salvo con `filter=all`—, 62 montajes, 59 intervalos, 177
  intervenciones, 350 salidas) y `probikegarage-2026-10-25-raw.json`
  (respuestas crudas por ruta). Técnica que funcionó para sacar 3 MB del
  navegador: el token de la API queda en la página (`window.__pbgHeaders`,
  capturado parcheando `fetch`; nunca se mostró), las respuestas se juntan en
  un `<textarea>` y se copian con teclas reales (`cmd+a`, `cmd+c` del tool
  `computer`) → `pbpaste` en el Mac. No sirvieron: `javascript_tool` (trunca a
  ~1 KB), `navigator.clipboard`/`execCommand('copy')` (sin gesto), `fetch` a
  `127.0.0.1` (Chrome lo bloquea: Local Network Access) ni descargas (piden
  permiso). REA no hizo falta (el análisis del 17 oct ya daba la API). El
  puerto CDP 9222 no estaba abierto.
- **Plan**: importador de un solo uso sobre un Garage vacío
  (`garage_import_probikegarage`, `--dry-run`, `--mapping`) + verificación
  (`garage_probikegarage_verify`) que compara bicis, componentes, reglas y
  salidas con el volcado. Las salidas vienen de Strava (garage-030, «Importar
  histórico» desde 2012-01-01) con `StravaGear` ya vinculado; las del volcado
  sólo verifican. Intervalos `repeat=false` («Max life») → vida útil;
  `elapsed-time` → días; uso inicial → lecturas de vida estimadas; horquilla
  «desde siempre» → desde el montaje más antiguo de su bici; desnivel del uso
  inicial omitido (sin migración).
- **Estado (25 oct, 18:50 UTC): implementada, revisada, corregida y
  re-verificada** por agentes Opus (spec §9 implementación, §10 revisión con
  11 hallazgos minor/nit, §11 correcciones, §12 re-verificación; informe
  `docs/validation/garage-043.json`). Código nuevo:
  `garage/importers/probikegarage.py`, `garage/services/probikegarage_import.py`,
  comandos `garage_import_probikegarage` (`--owner`, `--dry-run`, `--mapping`,
  `--zone`) y `garage_probikegarage_verify`, pruebas
  `garage/tests_probikegarage_import.py` (65) y `tests_probikegarage_review.py`
  (7). Suite completa **2690 + 45 subcasos** (219 s); `check`,
  `makemigrations --check` e `inspect` limpios. `--dry-run` del volcado real
  (Fable y los tres agentes): 0 errores, 6 avisos; crearía 17 categorías, 2
  bicis vinculadas a Strava, 50 objetos (19 retirados), 62 montajes (23
  anidados), 30 tipos, 38 reglas, 21 vidas útiles, 184 intervenciones y 8
  lecturas iniciales.
- **Importación real hecha por el usuario (25 oct, ~19:00 UTC)** en el clúster
  demo 55433, usuario `maxi` (id 2; contraseña fuera del repo, en
  `~/.cache/stravagancia/garage-demo-users.json`): 0 errores, 6 avisos; en la
  base: 2 bicis, 50 objetos (19 retirados), 62 montajes (26 abiertos), 59
  reglas (38 + 21 vidas útiles), 184 intervenciones, 8 lecturas, 2 `StravaGear`
  vinculados, 17 categorías, **0 salidas** (hasta el histórico de Strava). Mapa
  en `~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-25.json`.
  (El clasificador de permisos de Claude Code había bloqueado a Fable la
  aplicación real por datos personales; el comando fue:)

  ```bash
  export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
  python3 tools/handoff/garage_demo_pg.py run manage.py garage_import_probikegarage \
    ~/.cache/stravagancia/probikegarage/probikegarage-2026-10-25-compact.json \
    --owner 2 --mapping ~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-25.json \
    --settings=strava_app.settings_test
  ```

  Después, en la demo 8766 como `maxi`: Más → Strava → «Importar histórico»
  desde 2012-01-01 (necesita arrancar el servidor con `GARAGE_STRAVA_USER=maxi`
  y su token de Strava en el entorno; nunca leer `.env`) y, al terminar,
  `garage_probikegarage_verify <volcado> --owner 2 --mapping <mapa>` con el
  helper de la demo. La verificación compara en `exported_at` del volcado;
  se esperan 8 diferencias explicadas (spec §10, final).
- Clústeres recreados el 25 oct (el reinicio del Mac los borró): pruebas 55434
  (`stravagancia_test_018`, estado en `/private/tmp/garage018_pg_state.json`,
  `VALIDATION_DIR=/private/tmp/garage018-validation-q9x6iq36`) y demo 55433
  (migrada a 0012 y con el seed ficticio; demo / garage-demo). Demo 8766
  (`GARAGE_STRAVA_USER=demo`) y tablero 8765 relanzados en segundo plano
  (logs en `/private/tmp/garage-demo-8766.log` y `/private/tmp/garage-board-8765.log`).
- **Pendiente del usuario**: confirmar `maxi` como usuario de Garage para
  `GARAGE_STRAVA_USER`; parar el servidor demo 8766 (arrancado con
  `GARAGE_STRAVA_USER=demo` y sin token) y arrancarlo él con
  `GARAGE_STRAVA_USER=maxi` y su token de Strava en el entorno (nunca leer
  `.env`); en Más → Strava, «Importar histórico» desde 2012-01-01; confirmar D1–D12 (en especial D2: dos intervalos
  **repetibles** titulados «Max Life»/«Check Max Life», ambos de piezas
  retiradas, quedan como reglas normales); después,
  `garage_probikegarage_verify`.

## Entrega anterior: garage-042, ciclo de vida del material visible (18–19 oct)

Primer feedback de UI del usuario en las pruebas locales: quiere ver de un
vistazo, como en ProBikeGarage, qué material está montado, cuál disponible,
cuál en uso sin montar y cuál retirado. Especificación
`.claude/specs/2026-10-18-garage-ciclo-vida-material-spec.md` (decisiones §6,
revisión §7, re-verificación §8); informe `docs/validation/garage-042.json`.
**Sin migración**: la última sigue siendo la 0012 y la siguiente, la 0013.
Decisiones del usuario: «Retirado» se queda; un juego de pastillas es una sola
ficha, sin cantidades; el motivo al retirar queda para una tarea futura.

- **Servicio** `garage/services/lifecycle.py`: única fuente del estado y de su
  texto (`ItemLifecycle`, `item_lifecycles`, `filter_state` con `Exists` en la
  base de datos, `mount_resolver`), y etiqueta `{% life_text %}` en `garage_ui`.
  Estados en el instante `at`: **Retirado el …** (`retired_at <= at`),
  **Montado** («En Gravel desde el …», «Sobre Rueda trasera · Gravel desde el …»),
  **En uso · contextos** (perfil de uso vigente), **Disponible** o **Sin
  estrenar** (nunca montado, sin perfil, sin lectura previa, sin inicio de uso ni
  inclusión por excepción). Una retirada programada conserva el estado y añade
  «· se retira el …».
- **Material**: chips Montados · Disponibles · En uso · Retirados · Todos;
  fila «Categoría · estado»; `active` sigue aceptado como «no retirado ahora».
  Inicio («Disponible»/«Sin estrenar» en vez de «Guardado»), ficha y «Cuánto
  dura cada uno» usan los mismos textos. Bicis y Categorías no cambian.
- **Flujo Opus** (wf_860d7699): implementación → revisión independiente
  (8 hallazgos: 1 important —«Sin estrenar» ignoraba las inclusiones por
  excepción—, 2 minor, 5 nit) → corrección (7 arreglados; R042-5 rechazado:
  «sin montar» en las alertas es el lugar, compartido con Taller) →
  re-verificación `ready` (8/8). Suite completa **2618 pruebas + 45 subcasos**
  (183,91 s); `check`, `makemigrations --check` e `inspect` limpios.
  Presupuestos de consultas: Material ≤ 7; ficha suelta ≤ 44, montada ≤ 47;
  categoría ≤ 28.
- **Nota menor sin corregir** (anterior a 042): con una retirada programada,
  las acciones de la ficha leen `retired_at` sin mirar la fecha (muestran
  «Reactivar», ocultan «Montar» y «Añadir pieza»). Funciona porque «Reactivar»
  cancela la retirada. Decidir con el usuario.
- Demo 8766 reiniciada con el código nuevo para que el usuario lo pruebe.
- 19 oct (14:06 UTC): trabajo en pausa a petición del usuario y estado
  guardado. Demo 8766 y tablero 8765 levantados de nuevo como tareas en
  segundo plano de la sesión de Claude (mueren con ella; relanzarlos con los
  comandos de «PostgreSQL de pruebas y demo»). Nada en curso: ningún agente ni flujo activo.
  Pendiente del usuario: probar 042 en la demo, decidir la nota menor de arriba
  y confirmar el cambio en la deducción de iconos (spec 041 §8).

## Entrega anterior: garage-030 fase 4, operación diaria (18 oct)

Especificación `.claude/specs/2026-10-18-garage-strava-fase4-spec.md` (modo
token; maestra §3 «Disparo», «Revocación externa», §5 «Worker de Cloudflare»);
contrato en `docs/garage-domain.md` §16 («Operación diaria») y
`docs/garage-data-sources.md`. **Sin migración nueva**: la última sigue siendo
la 0012 y la siguiente, la 0013. Dos mitades:

- **Servicio**: `strava_sync._sync_owner(owner)` es el trabajo único de
  «Sincronizar ahora» (`sync_now`) y de `sync_all(now=None)`, que purga los
  avisos de más de 30 días y recorre las cuentas del propietario configurado
  (nunca crea la cuenta) ⇒ `SyncAllResult(accounts, pending, status, error,
  purged, absences)`. Ausencia como pista (`_after_window`, `ABSENCE_HINTS = 20`,
  sólo con la semana completa, sin error ni actividades inservibles), revocación
  (`revoked_at` sólo cuando Strava rechaza el token mismo: la renovación o
  `GET /athlete` tras una renovación; nulo en cuanto `GET /athlete` responde o
  al terminar bien; un `network`, un 429 u otro final fallido no lo tocan) y
  purga (`REVOKED_PURGE_DAYS = 30`, sólo `sync_all`, con `remove_strava_data`):
  a partir del día 30 en Madrid (`purge_date`/`purge_due`, la fecha que muestra
  la pantalla) y sólo si en esa misma ejecución Strava sigue rechazando el
  token. Endpoint `POST /garage/strava/sync-all/`
  (`garage:strava-sync-all`, `strava_views.sync_all`): sin sesión ni CSRF,
  `X-Sync-Token` con `hmac.compare_digest`; 404 a cualquier método si
  `GARAGE_SYNC_TOKEN` falta o tiene menos de 32 caracteres; 405 si no es POST;
  403 sin cuerpo; 200 JSON también si falla. Comandos `garage_sync_token`
  (imprime `secrets.token_urlsafe(48)`, no escribe archivos) y
  `garage_strava_sync` (ejecuta `sync_all()` e imprime el JSON). Una línea INFO
  en `garage.services.strava_sync`. Pruebas `garage/tests_strava_operation.py`
  (64: 45 de la entrega y 19 netas de la revisión).
- **Worker** (`keepalive/cloudflare-worker.js`): `scheduled()` despacha por
  `event.cron` (espacios normalizados). `*/12 * * * *`, y cualquier otro cron,
  es el keep-alive de siempre, sin cambios. `5 7,8 * * *` (UTC) es la
  sincronización y sólo actúa cuando en `Europe/Madrid` son las 09: las 09:05
  en verano y en invierno, una vez al día (también los dos días de cambio de
  hora). Hace `POST` a `env.SYNC_URL` con `X-Sync-Token: env.SYNC_TOKEN`
  (secreto del Worker) y `User-Agent: curl/8.7.1`, sin cuerpo,
  `AbortSignal.timeout(45000)` por llamada y 2 s entre llamadas; para en
  `pending == 0`, `error != ""`, una respuesta no 200, una llamada fallida o
  agotada, un JSON inesperado o a las 6 llamadas. Sin `SYNC_URL` o `SYNC_TOKEN`
  escribe qué nombre falta (nunca valores) y no llama. Nunca registra el token
  ni la URL (de un error sólo su `name`). El handler `fetch` sólo hace el ping.
  Nunca sigue una redirección (`redirect: "manual"`): un 3xx para con su
  código y el token no viaja a otra URL.
  `keepalive/README.md` explica los dos triggers, la variable, el secreto y que
  los configura el usuario en el panel. Pruebas `keepalive/worker.test.mjs`
  (39, `node --test`, `fetch`/`Date`/`setTimeout`/`AbortSignal.timeout`
  simulados).
- **Pantalla Más → Strava** (`_page`, `strava.html`): para el propietario
  configurado, «Sincronización automática: configurada. El Worker de Cloudflare
  la pide cada día a las 9:05 (hora de Madrid)» (sin cuenta añade «a partir de la
  primera sincronización manual», porque `sync_all` no la crea) o «no
  configurada (falta GARAGE_SYNC_TOKEN).», según
  `strava_views.sync_token_configured()`, sin mostrar el ajuste. Con
  `revoked_at`: aviso `pending st-due` «Strava rechaza el token desde el
  <fecha>. Renueva STRAVA_REFRESH_TOKEN en Render. Si sigue así, lo
  sincronizado desde Strava se borrará automáticamente el <purge_date>.»
  («desde el» en la zona de quien mira; la fecha de borrado es el día de Madrid
  en que la ejecución diaria purga). Sin `GARAGE_SYNC_TOKEN` no promete nada
  automático: «…se borrará en la primera sincronización diaria a partir del
  <fecha>; sin sincronización automática, sólo si alguien ejecuta manage.py
  garage_strava_sync.». Sustituye al texto genérico de `unauthorized`;
  cualquier otro error (p. ej. 429) se sigue mostrando. Sin consultas nuevas,
  sin JavaScript ni estilos en línea. Pruebas en `garage/tests_strava_views.py`
  (+9, y +5 de la revisión).
- Decisiones fuera del spec (servicio): 404 a cualquier método sin token
  válido (el 405 sólo con él); ausencia con `>` estricto contra el `after`
  pedido, sin pistas si hubo actividades inservibles y sin segunda pista con un
  borrado pendiente de la misma actividad; un `delete` confirmado que sigue en
  Strava guarda lo devuelto (nunca crea una fuente); `sync_all` sin cuenta ⇒
  `idle` (y no escribe nada para una cuenta quitada a mano mientras corre),
  para en el primer error. (Worker y
  pantalla): un fallo, timeout o JSON inesperado para el bucle ese día; un cron
  desconocido hace el keep-alive; el aviso de revocación y la línea automática
  sólo para el propietario configurado (la purga diaria no toca otra cuenta).
- Límites: la purga ocurre en la ejecución diaria de la fecha mostrada (o en la
  primera posterior si ese día no hubo ejecución o falló por red o 429) y sólo
  si el Worker (o `garage_strava_sync`) llama a `sync-all`. Detectada por la
  ejecución diaria, la purga llega justo a los 30 días (±1 h por el cambio de
  hora); detectada con el botón de madrugada, hasta unas 9 h después (la
  ejecución es a las 09:05). Con la regla anterior (`≥ 30 días`) caía casi
  siempre el día 31, un día después de la fecha mostrada. La ausencia supone
  `activity:read_all` (comprobarlo antes de desplegar, abajo). Borrados de más
  de 7 días sólo llegan por webhook. El
  logger `garage` no se ve en Render hasta garage-023. Nada probado contra
  Strava ni Cloudflare reales; nada desplegado. El servidor demo 8766 se
  reinició con el código final (18 oct) y con `GARAGE_STRAVA_USER=demo`, así
  que Más → Strava muestra el estado del propietario configurado.
- Validación (TESTING.md, «garage-030 fase 4»): `node --check` correcto y
  `node --test keepalive/worker.test.mjs` 39/39; suite completa **2552 pruebas + 45 subcasos** (176 s, tras la revisión; **2578 + 45** tras los arreglos de herramientas, abajo);
  check sin problemas, makemigrations «No changes detected», 0 bases
  residuales; capturas a 390 px (claro y oscuro) de Más → Strava (antes de la
  revisión).
- **Revisión de código independiente hecha** (spec §5): 2 importantes (purga
  sin comprobar el token; un `network` reiniciaba el plazo de 30 días) y 7
  menores (403/401 tras aceptar el token, fecha de purga, `TARGET` del README,
  redirecciones del Worker, `activity:read_all`, cuenta quitada durante la
  ejecución, token en una página 500 con DEBUG), todas corregidas con pruebas.
- **Re-verificación independiente hecha** (spec §6): 9/9 arreglos verificados;
  una aserción frágil (`"kJ" not in html` frente al token CSRF, en
  `garage/tests_elevation_screens.py`) corregida; informe
  `docs/validation/garage-030-fase-4.json`.
- Arreglos de herramientas del mismo día (agentes Opus): el tablero 8765
  acepta las subtareas jerárquicas de Beads (`garage-031.1`…; antes `/state.json`
  respondía 503 «identificador inválido»; `tests_progress.py` +6); el helper de
  la demo deja pasar `GARAGE_STRAVA_USER`, `settings_test.py` la lee y bajo
  pytest `isolation.install()` la vacía (`tests_test_environment.py` +2).

## Despliegue (garage-023): lo que falta configurar

Nada de esto lo hace una IA ni se ha hecho: lo configura el usuario cuando
autorice el despliegue (garage-023). Nunca escribir tokens en el repositorio.

- **Render, variables de entorno**:
  - `GARAGE_STRAVA_USER`: usuario de Garage dueño del atleta de Stravagancia
    (pendiente de que el usuario lo indique). Vacío ⇒ Garage no sincroniza.
  - `GARAGE_SYNC_TOKEN`: **≥ 32 caracteres**; generarlo con `python manage.py
    garage_sync_token` (imprime 64 caracteres una vez, no escribe archivos).
    Vacío o corto ⇒ `sync-all` responde 404 y no hay sincronización diaria.
  - `STRAVA_WEBHOOK_SUBSCRIPTION_ID` (opcional): id de la suscripción del
    webhook; con él, los eventos de otra suscripción se descartan.
  - Arranque con **`gunicorn --timeout 60`**: «Sincronizar ahora» y cada
    `sync-all` duran unos 30 s; el Worker espera 45 s por llamada.
  - Logger `garage` (INFO) en `LOGGING` para ver la línea diaria.
- **Antes de activar la fase 4, comprobar `activity:read_all`** (a mano, en
  producción, lo hace el usuario): la ausencia en la semana y los `delete`
  sólo borran con un 404, que sólo prueba algo si el token de Stravagancia ve
  las actividades privadas. Con una salida **privada** («Solo tú») de los
  últimos 7 días (una existente o una de prueba), pulsar «Sincronizar ahora» y
  comprobar que aparece en Garage. Si no aparece, el token no tiene
  `activity:read_all`: no configurar el Worker y avisar (una salida que se haga
  privada se borraría de Garage en un día). Una salida de prueba se borra
  después en Strava (también la recibe el webhook del legado).
- **Cloudflare, Worker `strava-keepalive`** (panel; ver `keepalive/README.md`):
  pegar `keepalive/cloudflare-worker.js` en Edit code y **sustituir `TARGET`**
  (aquí `REDACTED`) por la URL real de `/healthz/` que ya tiene la copia del
  panel **antes de Deploy**: desplegarlo tal cual rompe el keep-alive (Render
  se duerme y el POST de las 09:05 choca con un arranque en frío de más de
  45 s). Cron Triggers `*/12 * * * *` (ya existe) y **`5 7,8 * * *`**;
  variable `SYNC_URL` = `https://<app>.onrender.com/garage/strava/sync-all/`
  (con `https` y la barra final: el Worker no sigue redirecciones y un 301
  para la sincronización); **secreto** `SYNC_TOKEN` = el mismo valor que
  `GARAGE_SYNC_TOKEN`.
- **Migraciones**: `garage.0009`–`0012` sólo locales, **no están en Neon**.
  Nota sólo para el despliegue: la 0012 sustituye dos CHECK
  (`garage_maintenancerule_has_threshold` y `garage_snooze_has_amount`) por
  versiones que admiten el desnivel; las filas actuales los cumplen y en Neon
  las tablas de Garage están vacías. No preguntar por ello antes de desplegar
  (orden del usuario, 18 oct: local → Strava real → despliegue). Aplicarlas
  sólo en el despliegue autorizado, nunca con `docker compose up web` (migra
  contra Neon).
- **Tras desplegar**: `python manage.py garage_strava_sync` en la consola de
  Render (mismo trabajo acotado, imprime el JSON) y, al día siguiente, los
  registros del Worker a las 09:05 (Observability → Logs).

## Entrega anterior: garage-030 fase 3, desnivel y potencia (18 oct)

Especificación `.claude/specs/2026-10-18-garage-strava-fase3-spec.md` (incluye
garage-037); contrato en `docs/garage-domain.md` §17 y enmiendas de §13, §14,
§14 bis, §15 y §16. Dos mitades: **datos** (migración `garage.0012_elevation_power`,
sólo local; tuplas `CORE/USAGE/POWER/RIDE_METRICS`, FIT, Strava, materialización,
exportación) y **pantallas**:

- Reglas y aplazamientos por desnivel: `maintenance_due.METRICS` (último),
  `presentation.UNITS` «m» / `NAMES` «Desnivel» / `MARKS` «↑», `thresholds()`
  («20.000 m de desnivel»), `snooze_reached`, `.only()`; formularios de regla,
  vida útil y posponer con «Desnivel (m)» en metros enteros (`elevation_field`
  en `maintenance_forms.py`). Un aplazamiento con una salida sin desnivel queda
  «por revisar» y el aviso se ve.
- Pantallas: «↑ 1.234 m» (filtro `metric_m`) en Salidas, Histórico,
  previsualización FIT, Inicio, bici, objeto, intervención y efecto de la
  revisión; potencia («Ø», «máx», «NP», kJ; filtro `power_figures`) sólo en la
  revisión y el detalle de la salida (`_ride_measures.html`). Única regla CSS
  nueva: `.stats.four` (y `.stats + .stats`). Sin JavaScript nuevo.
- Estadísticas: desnivel del período, por bici, por material y por mes
  (`?chart=elevation` en Estadísticas). La potencia media no se suma.
- Menores de fases 1–2 en `strava_sync.py`/`strava_client.py`: la última ronda
  ya no se traga los avisos tardíos, un lote lleno sigue en otra ronda (o en un
  worker nuevo), «Sincronizar ahora» responde en unos 30 s
  (`RESPONSE_SECONDS`: conexión + lectura recortadas a lo que queda; código
  interno `deadline`; no es un límite estricto porque requests no acota DNS,
  un cuerpo a goteo ni la renovación del token, y el techo duro es el de
  gunicorn, 60 s) y los perfiles usan `sport_label`.
- Pruebas: `garage/tests_elevation_screens.py` (42, hoy 46 tras la revisión);
  suite de esa mitad 2429 pruebas + 45 subcasos (TESTING.md, «garage-030 fase 3,
  mitad de pantallas» y «revisión de código»).
- Revisión de código (spec §5, todo corregido): `WholeNumberInput` lee
  «20.000» como 20.000 m (Django lo guardaba como 20) en regla, vida útil y
  posponer, también salidas, días y tiempo; campos FIT opcionales repetidos o
  mal formados ⇒ desconocidos (el archivo entra); timeout conexión + lectura ≤
  lo que queda; una regla cuyo intervalo no tiene ninguna salida con desnivel
  queda «Sin datos» (no «En curso ≥ 0 %»), con «N sin desnivel», «↑ ≥» y la
  indicación de volver a importar FIT o histórico de Strava donde el desnivel es
  un mínimo. Pruebas: `garage/tests_elevation_review.py` (39); suite **2473
  pruebas + 45 subcasos**, check, makemigrations sin cambios, 0 bases residuales.
- Re-verificación (Opus, spec §6): 4/4 arreglos comprobados; 2 hallazgos
  nuevos menores corregidos por el orquestador: el campo exacto que conserva
  la regla del teléfono cuando el desnivel tiene decimales (puesto desde el
  admin) es ahora `DecimalInput` («1.234,5» vale, «2.000» se rechaza como
  ambiguo en vez de leerse como 2 m; 1 prueba) y el docstring de
  `strava_client` dice «como mucho (5, 20)». `CLAUDE.md` actualizado (0012
  sólo local, siguiente 0013, aviso de los dos CHECK). Suite **2474 pruebas +
  45 subcasos** (docs/validation/garage-030-fase-3.json). Demo 55433 migrada
  a 0012 y servidor 8766 reiniciado.
- Pendiente: probar el parser con la muestra FIT del usuario (spec maestra
  §7.3) y contra Strava real; la fase 4 se entregó después (arriba).

## Entrega anterior: garage-041, categorías iniciales con icono (18 oct)

Pedido del usuario: «en material me faltan muchas categorías» → juego inicial
«con su icono». Especificación `.claude/specs/2026-10-18-garage-categorias-iniciales-spec.md`.

- **Migración `garage.0011_category_icon`** (sólo local, **no está en Neon** ni
  en la demo 55433): `Category.icon` (`''` = deducir del nombre) y CHECK
  `icon = '' OR icon ~ '^[a-z_]+$'`. Las fases 3–4 de Strava deberán usar 0012.
  La demo de 8766 sigue con el código anterior cargado (`--noreload`): al
  reiniciarla habrá que aplicar 0011 a su base o fallará al leer categorías.
- Código: `garage/icons.py` (`ICON_CHOICES`: 43 claves con nombre y palabras
  clave; `match_icon`, `item_icon_key`, `category_icon_key`),
  `services/categories.py` (`STARTER`, `create_starter_categories`,
  `missing_starter`, `starter_offer`, `suggest_icon`), `category_views.py`
  (`category-starter`, POST), `IconGrid` y `CategoryWebForm` en `web_forms.py`,
  `_icon_grid.html`, `_starter.html`, 32 símbolos nuevos en `_icons.html`,
  estilos al final de `garage.css`, columna `icon` en la exportación
  (`docs/garage-export.md`) y lista desplegable en el admin.
- Decisiones además de la especificación:
  - El §3 tiene **42** categorías (no 37), y se crean todas.
  - El botón sale siempre en Categorías mientras falte alguna, en Material sólo
    si está vacío y en Crear material si no hay ninguna categoría.
  - **«Según el nombre» guarda `''`** y el icono se deduce cada vez; corregido
    en la revisión (antes congelaba la sugerencia). Las categorías sin icono
    abren el formulario con esa opción marcada y su casilla dibuja el icono
    sugerido. Una clave que ya no esté en la lista también se trata como `''`.
- **Cambio visible, pendiente de que el usuario lo confirme.** La deducción ya no
  sigue la tabla antigua:
  - Va sin acentos; las palabras clave casan como palabra completa (con
    plural); gana la escrita antes (el núcleo: «Llave de cadena» es
    herramienta, «Bolsa de sillín» bolsa) y, a igual posición, la más larga.
    Lo fijó la re-verificación (spec §8): antes mandaba la longitud y una
    clave casaba dentro de otra palabra («Recambios» daba desviador).
  - El nombre del objeto va antes que el de su categoría.
  - Hay iconos nuevos. Por ejemplo, «Disco» en «Frenos» pasa de freno a disco,
    «Llanta» de rueda a llanta, «Plato» de casete a platos, «Calas» de
    zapatilla a calas y «Cámara» en «Cubiertas» de cubierta a cámara.

  Vida útil orientativa: la llanta conserva la de la rueda. Disco, platos,
  calas y cámara se quedan sin cifra, porque la que heredaban era la de otra
  pieza (1.500 km de pastillas para un disco). Las opciones están en la spec,
  §7.7. Si el usuario prefiere la regla antigua, se cambia en
  `garage/icons.py` y `lifespan_forms.SUGGESTIONS` sin migración.
- Revisión independiente hecha: 1 hallazgo importante y 6 menores, todos
  corregidos con prueba (spec §7). Re-verificación: los 7 comprobados; 2 menores
  nuevos en la deducción, corregidos (spec §8).
- Pruebas:
  - `garage/tests_categories.py`: 91 casos (52 + 25 de la revisión + 14 de la
    re-verificación).
  - Suite completa: ver `docs/validation/garage-041.json`.
  - check, makemigrations e `inspect` limpios (TESTING.md).
- Demo 55433 migrada a 0011 y servidor 8766 reiniciado el 18 oct (usuario
  demo / garage-demo); el botón «Crear las categorías habituales» sale en
  Categorías.
- Pendiente: que el usuario confirme el cambio visible de la deducción.

## Entrega anterior: garage-030 fases 1–2, Strava en «modo token» (18 oct)

El usuario aprobó el alcance de §0 de
`.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`: el mismo refresh
token de Stravagancia, sólo su cuenta, sólo ciclismo, sin OAuth (garage-040).
Especificación de la fase con las decisiones tomadas:
`.claude/specs/2026-10-18-garage-strava-fase1-2-spec.md`; contrato en
`docs/garage-domain.md` §16 (y enmienda de §10).

- **Migración `garage.0010_strava_source`** (sólo local; **no está en Neon**:
  levantar `web` de Docker Compose la aplicaría junto con 0009). Aditiva salvo
  dos CHECK ampliados (tipo de fuente y de trabajo), que las filas FIT cumplen.
  Modelos `StravaAccount`, `StravaGear`, `StravaEvent`; columnas
  `ActivitySource.external_id/gear_id/possible_duplicate` e
  `ImportRun.items_imported/items_skipped`.
- Código: `garage/sports.py` (familia ciclismo, mapa de Strava),
  `services/strava_client.py` (HTTP, `timeout=(5, 20)`, `parse_float=Decimal`,
  401/429), `services/strava_sources.py` (observación, vinculación, separar,
  unir, bicis, quitar lo sincronizado), `services/strava_sync.py` (cuenta env,
  «Sincronizar ahora», histórico reanudable, webhook), `strava_views.py`,
  `strava_forms.py`, `strava.html`; precedencia por clase en
  `services/rides._recalculate`; perfiles por familia en `usage_profiles` y
  `ride_review`; exportación aditiva (`strava_gear`, columnas de `sources`).
- Legado tocado sólo en `strava_integration/views.py`: despacho por atleta (el
  legado sólo procesa su `Athlete.strava_id`), `subscription_id` y
  `compare_digest` en la verificación; sus pruebas añaden `owner_id`.
- Pantallas: Más → Strava (`/garage/strava/`), trabajo Strava en el histórico
  (sin archivo), origen y «posible duplicado» en Salidas y en la salida,
  «Separar fuente», «Unir con…», «No es un duplicado», «Powered by Strava».
- **Variables nuevas**: `GARAGE_STRAVA_USER` (usuario de Garage dueño del
  atleta) y `STRAVA_WEBHOOK_SUBSCRIPTION_ID` (opcional; si existe, otro id se
  descarta). La primera entrega decía haberlas añadido a
  `strava_app/settings.py` y **no estaban** (hallazgo bloqueante de la
  revisión); desde la revisión del 18 oct sí: `os.getenv(..., '')`, con una
  prueba que lee el archivo (no se tocó `.env`).
- Límites: `refresh_access_token()` del legado sigue sin `timeout` (no se tocó);
  Garage y el legado renuevan el mismo token (mismo riesgo de rotación que ya
  corría el legado); se supone `activity:read_all`; la paginación del histórico
  es por número de página (un borrado durante la importación puede desplazar una
  actividad, la sincronización de 7 días lo compensa en lo reciente); el logger
  `garage` no está configurado en producción (garage-023). Pendiente: fases 3
  (desnivel y potencia, 0011) y 4 (ausencia como pista, `sync-all`, Worker),
  probar contra Strava real y capturas.
- **Revisión de código (18 oct)**: 13 hallazgos corregidos con pruebas, sin
  migración nueva; detalle en la sección «Revisión de código» de la
  especificación corta. Lo principal: páginas de 50 y ≈ 12 consultas por
  actividad nueva (antes ≈ 82), «Sincronizar ahora» acotado a 14 peticiones y
  25 s, un hilo del webhook por atleta y proceso tras el commit, sin llamadas a
  Strava dentro de transacciones y con el orden de bloqueos propietario →
  evento, «Unir con…» que ya no borra notas ni excepciones (y avisa antes),
  FIT duplicado marcado, estados y modalidades en español.
- Pruebas: ver TESTING.md («garage-030 fases 1–2»): 118 de Strava, 42 del
  legado; suite completa **2201 pruebas + 45 subcasos**; check, makemigrations
  y cero bases residuales.

## Entrega anterior: ideas de ProBikeGarage, garage-034 a 039 (17–18 oct)

El usuario hizo un análisis REA de ProBikeGarage
(`docs/research/2026-10-17-probikegarage-rea.md`) y pidió incorporar lo que
falta: posponer vencimientos, componentes anidados; desnivel y Strava «luego»
(030 sigue aplazada). Se fue a dormir: «ve haciendo. ante la duda, documenta las
opciones y elige una», y quiere una comparación final con ProBikeGarage
recordando lo que Garage hace mejor (material por bici o deporte: casco,
zapatillas). Tareas creadas: 034 posponer, 035 piezas anidadas, 036 uso en cada
intervención y comparar piezas, 038 retirar con lo montado, 037 desnivel
(diseñar, no implementar sin el usuario), 039 comparación final.

**garage-034 (cerrada)**: `MaintenanceSnooze` + migración aditiva 0009 (sólo
local), `services/snoozes.py`, `snooze_forms.py`, `snooze_views.py`
(`maintenance-rule-snooze`), estado «Pospuesto» en `presentation.py`, Inicio,
Taller, fichas, detalles técnicos y exportación (`snoozes`). Especificación con
decisiones y revisiones: `.claude/specs/2026-10-17-garage-posponer-spec.md`;
contrato en `docs/garage-domain.md` §14 bis. Pruebas `garage/tests_snoozes.py`.

**garage-035 (cerrada)**: `services/parts.py`, `parts_views.py`,
`part_forms.py` (`item-part-create`), sección «Piezas» y entradilla anidada en la
ficha, y «También en esta visita» en Registrar mantenimiento
(`maintenance_views._together`, `_together.html`): una intervención por regla
marcada, atómico, alcance en la fecha elegida. Especificación
`.claude/specs/2026-10-18-garage-piezas-spec.md`. Pruebas `garage/tests_parts.py`.

**garage-036**: `services/service_usage.py` (uso desde la anterior y hasta la
siguiente por intervención; «Cuánto dura cada uno» por categoría), filtros
`span_text`, `span_short`, `metric_km`, `whole_days`, `_event_usage.html`,
`_part_lives.html`. Especificación
`.claude/specs/2026-10-18-garage-uso-intervenciones-spec.md`. Pruebas
`garage/tests_service_usage.py`.

**garage-038**: `services/retirement.py` (`mounted_in`, `retire_one`,
`retire_with_parts`, `PartsChanged`), `RetireWebForm` y casilla «Retirar lo que
sale» en Reemplazar. Especificación `.claude/specs/2026-10-18-garage-retirar-spec.md`.
Pruebas `garage/tests_retire_parts.py`.

**garage-037**: sólo diseño (`.claude/specs/2026-10-18-garage-desnivel-spec.md`);
no implementar sin el usuario. **garage-039**: comparación en
`docs/garage-vs-probikegarage.md`.

**Strava por usuario (18 oct, pendiente de aprobación)**: el usuario quiere
sincronizar desde Strava con un botón «Conectar con Strava» (OAuth 2.0 por
usuario, tokens cifrados en la base), desnivel y potencia. Especificación
conjunta `.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`
(revisión 2 tras dos revisiones independientes). Fases 1–2 implementadas el
18 oct (arriba). El usuario respondió §9 el 18 oct: modo token (el mismo
refresh token de Stravagancia, sólo su cuenta, `GARAGE_STRAVA_USER`), sólo
ciclismo, OAuth por usuario apuntado en garage-040 (§0 de la especificación).
El 18 oct dio el «adelante» («hazlo con agentes, opus 5.5»). Un agente
implementador Opus 5.5 trabajó las fases 1–2 hasta que el usuario pidió una
pausa para reiniciar el Mac; **se detuvo a mitad de trabajo**, con el código ya
en disco: `garage/services/strava_client.py`, `strava_sources.py`,
`strava_sync.py`, `garage/strava_forms.py`, `strava_views.py`, pruebas
`garage/tests_strava_*.py`, migración 0010 (si existe en `garage/migrations/`)
y la especificación corta `.claude/specs/2026-10-18-garage-strava-fase1-2-spec.md`.
Estaba redactando TESTING.md y este relevo cuando se paró: **nada de esto está
probado ni revisado**. Al retomar: leer la especificación corta, ejecutar la
suite completa (`check`, `makemigrations --check`, `inspect`), arreglar lo que
falle o relanzar el implementador con el mismo encargo (está en la conversación
y en §0/§7 de la especificación maestra), y después la revisión independiente y
la re-verificación. Tras el reinicio hay que volver a levantar los clústeres
PostgreSQL desechables (demo 55433 con su seed y la migración 0009/0010; el de
pruebas lo crea el helper), el tablero 8765 y la demo 8766 (comandos más abajo). Puntos
delicados que las revisiones fijaron: revocar en Strava afectaría al token del
legado (excepción para el atleta del propietario), el webhook no está firmado
(eventos como pistas confirmadas por API), `METRIC_FIELDS` se divide para que
la potencia no entre en `ItemUsage`, vinculación FIT↔Strava determinista.

Suite completa tras 038: **2066 pruebas + 45 subcasos pasan**; check,
makemigrations y cero bases residuales.

La demo (`tools/garage_demo_seed.py`) incluye ahora una rueda trasera con casete
y disco anidados; la base demo actual recibió lo mismo con un script local.

## Entrega anterior: garage-032 y garage-033 (17 oct)

El usuario pidió seguir («sigue sigue q es sabado») y, a mitad de trabajo, que
cada componente tenga vida útil por km o por tiempo, lo primero que llegue,
«mejor que probikegarage». Sin modelos ni migraciones.

**garage-032**: resto de pantallas al estilo B. Especificación revisada:
`.claude/specs/2026-10-17-garage-movil-2-spec.md`.

1. 032.1:
   - Hora local en todos los formularios: `garage/local_forms.py`
     (`LocalDateTimeInput`, `localize`; la zona del usuario, el selector nativo
     y UTC si la hora se repite o el valor no es exacto). Se aplica en
     `views.form_page`.
   - Taller: `services/workshop.py`, `maintenance.html`, `_wear_row.html`
     compartida con Inicio.
   - Formularios web de mantenimiento en `maintenance_forms.py`:
     `ServiceEventWebForm`, `MaintenanceRuleWebForm` (km y horas exactos),
     `ServiceTypeWebForm`, `DecimalInput` (coma decimal, «3.000» ambiguo) y
     `SpanishWebMixin`. El admin conserva sus formularios y mensajes.
   - Detalle de intervención y fotos.
2. 032.2: ficha de bici (`views.bike_dashboard`, `bike_detail.html`) y `?bike=`
   en Salidas.
3. 032.3: Estadísticas por período (`statistics_views.py`: chips, cifras,
   gráfico de todas las salidas, reparto por bici, material, gasto; informe
   detallado plegado). `monthly_usage(all_rides, through)`,
   `StatisticsReport.overall/no_bike`.
4. 032.4: listas de bicis, material y categorías, perfiles, histórico, salida
   avanzada y exportar con el estilo nuevo. `{% local_datetime %}` con
   `<time datetime>` en lugar de las fechas UTC.

**garage-033**: vida útil. Especificación:
`.claude/specs/2026-10-17-garage-vida-util-spec.md`.
- Una regla del tipo «Sustitución» del propietario, mostrada como «Vida útil».
- Servicio `services/lifespan.py`; formulario `lifespan_forms.py`; página
  `items/<uuid>/lifespan/` (`lifespan_views.py`, `lifespan.html`) con km,
  horas y tiempo (1 mes = 30 días, 1 año = 365 días) y sugerencias por pieza.
- Inicio por defecto: inicio de uso, fecha de compra, primer montaje u hoy.
- Al reemplazar un montaje, la pieza nueva puede heredarla (atómico).
- «Vida útil» en ficha, Inicio, Taller y avisos técnicos.

Pruebas nuevas: `garage/tests_mobile_{workshop,bike,stats,lists}.py` y
`tests_lifespan.py`. Ajustes intencionados:
- `tests_views.py`: cookie UTC.
- `tests_maintenance.py`: «12,34».
- `tests_mobile_item.py`: la bici tiene ficha propia.

Suite completa: **1959 pruebas + 45 subcasos pasan** (96 s); check, makemigrations y cero bases residuales.

Revisiones independientes (todas corregidas con pruebas):
- Especificación de 032.
- Código de 032.1–.2: moneda propuesta, «3.000», mensajes, umbrales exactos.
- Código de 032.3–.4 y verificación: «Personalizado» con filtros, mensajes del
  admin, fechas que desbordan.
- Código de 033 y verificación de la segunda ronda: sin bloqueantes; corregido con pruebas.
- Re-verificación final de 033: un 500 con zona horaria inválida y el aviso de sustitución sin regla; corregidos con pruebas.

Mutaciones comprobadas (redondeo silencioso, reasignación de errores, moneda):
cada una hace fallar una prueba; archivo restaurado con hash idéntico. Capturas
a 390 px en claro/iPhone y oscuro/Android de Taller, formularios, ficha de
bici, Estadísticas, listas y vida útil.

Límites declarados:

- Teléfono real sólo con HTTPS (garage-023); la tarea garage-031 sigue abierta por eso.
- `LANGUAGE_CODE` sigue en `en-us` por la app antigua: los mensajes en español
  se aplican en los formularios web de mantenimiento y de vida útil; otros
  formularios antiguos pueden mostrar mensajes de Django en inglés.
- Vida útil: los km anteriores de una pieza usada aún no cuentan (se avisa).
- El filtro del histórico interpreta las fechas en la zona del usuario (antes UTC).

## Siguiente paso

1. **garage-032 y garage-033 cerradas** (17 oct). Probarlas en un teléfono real
   junto con 031 tras desplegar.
2. **garage-031**: sólo falta probarla en un teléfono real (depende de 023).
3. **garage-010**: propuesta (`docs/garage-photo-bucket-proposal.md`) y script
   (`tools/handoff/garage_bucket_check.py`) listos; falta que el usuario autorice
   y cree bucket/credencial en `~/.config/garage-s3-test.env`.
4. **garage-022** depende de 010; **garage-023**: logger `garage`, `STORAGES`,
   docker-compose sin migrate contra Neon.
5. **garage-043** (25 oct): importador de ProBikeGarage en curso (sección
   «Última entrega» arriba). Al terminar el agente: revisión independiente
   (spec §5), re-verificación (§6), `--dry-run` y aplicación del volcado real
   en local para el usuario de Garage del propietario, y después el histórico
   de Strava + `garage_probikegarage_verify`.
   **garage-042** implementada y verificada (19 oct); falta que el usuario la
   pruebe en la demo y decida la nota menor de las acciones con retirada
   programada. **garage-030**: fases 1–4 hechas en modo token (la 4, sin migración).
   Revisión de código de la fase 4 hecha, corregida y re-verificada (spec §5
   y §6). **Orden fijado por el usuario (18 oct)**: (a) probar todo en local
   con la demo 8766 (el usuario va a dar feedback sobre la UI; recogerlo en
   Beads y priorizarlo con él antes de tocar nada); (b) resolver la
   sincronización real desde Strava en local (hace falta su usuario de Garage
   para `GARAGE_STRAVA_USER`, que arranque él el servidor con su token de
   entorno —nunca leer `.env`— y su muestra FIT, spec maestra §7.3);
   (c) el despliegue es lo último (bloque «Despliegue (garage-023)», con la
   comprobación de `activity:read_all`, y Cloudflare real).
6. Ideas de ProBikeGarage aún sin tareas (preguntar): posponer avisos, comparar
   duración de componentes, desnivel. Las plantillas de alta quedaron cubiertas
   en parte por las sugerencias de vida útil.

7. **`main` avanzó el 25 oct (legado, no Garage)**: commits `dd607f6` (sin caché
   negativa de geocodificación, espejo `overpass.openstreetmap.fr`, diagnóstico
   `getaddrinfo`) y `45a7cf6` (el webhook `create` responde antes de pedir el
   detalle: fetch → store → rename en el hilo `create-<id>`; `settings.py` fuerza
   IPv4 saliente en Render salvo `GEOCODING_FORCE_IPV4=0`). Desplegados en Render
   con autodeploy. `codex/garage-plan` **no los tiene**: al integrarlos,
   `strava_integration/views.py` chocará con los cambios de garage-030
   (`accept_event`/`subscription_matches`); conservar ambos. Suite de `main`:
   138 tests con PostgreSQL local (sin `.env`).

## Estado de tareas y evidencia

- Cerradas: 001–009, 011, 012, 014–020, 028, 029. 013/021 cerradas N/A.
- 010 in_progress (falta bucket real). 031 abierta (sólo teléfono real). 032 y 033 cerradas el 17 oct.
- 042 in_progress (implementada, revisada y re-verificada el 19 oct; pendiente de que el usuario la pruebe en la demo).
- 030 in_progress (fases 1–4 en modo token hechas y verificadas; faltan pruebas locales con el usuario, Strava real y el despliegue). 037 cerrada con la fase 3. 022/023 pendientes; 024–027 futuras.

Informes: docs/validation/garage-0{17,18,19,20}.json y docs/garage-validation.json
(= 020). Los artefactos de /private/tmp de sesiones anteriores **desaparecieron**
con el reinicio del 13–16 oct (actualización de macOS); los JSON del repo
conservan los resultados.

## PostgreSQL de pruebas y demo (recreados el 16 oct)

Pruebas: 127.0.0.1:55434, base stravagancia_test_018, rol stravagancia_test
(sin superusuario, contraseña sintética stravagancia_test). Estado en
/private/tmp/garage018_pg_state.json, datos en /private/tmp/garage018-validation-zhirv99e.

```bash
export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
python3 tools/handoff/garage_test_pg.py run -m pytest garage/tests_mobile_review.py -q --tb=short -p no:cacheprovider
python3 tools/handoff/garage_test_pg.py run manage.py check --settings=strava_app.settings_test
python3 tools/handoff/garage_test_pg.py run manage.py makemigrations --check --dry-run --settings=strava_app.settings_test
```

Demo: 127.0.0.1:55433, base stravagancia_test_demo, datos ficticios generados
por `tools/garage_demo_seed.py` (usuario demo / garage-demo): dos bicis,
sillines A→B→A, cadena que pasó de Gravel a Carretera, casco y zapatillas por
perfil, ~8 meses de salidas, una salida sin bici y reglas en varios estados.
Servidor (tarea en segundo plano de la sesión de Claude; puede detenerse):

```bash
GARAGE_TEST_PYTHON=$GARAGE_TEST_PYTHON python3 tools/handoff/garage_demo_pg.py run manage.py runserver 127.0.0.1:8766 --noreload --insecure --settings=strava_app.settings_test
```

El helper de la demo deja pasar `GARAGE_STRAVA_USER` (y nada más) a Django, para
que Más → Strava muestre el estado del propietario configurado (anteponer
`GARAGE_STRAVA_USER=demo`); el helper de pruebas no lo hace.
`strava_app/settings_test.py` lee esa variable, y bajo pytest
`test_support/isolation.py::install()` la quita del entorno (con
`GARAGE_SYNC_TOKEN`), así que en las pruebas vale "".

La demo está migrada a `garage.0012_elevation_power` (18 oct); la fase 4 no
añade migraciones, así que no hay nada que aplicarle.

Si la demo desaparece: `garage_demo_pg.py start`, `run manage.py migrate
--settings=strava_app.settings_test` y `run tools/garage_demo_seed.py`.
No ejecutar pytest con el helper de demo. Su acción `stop` BORRA los datos.
Nunca dos suites a la vez en 55434.

Tablero http://127.0.0.1:8765/ (`tools/garage_progress.py`): en marcha como
tarea en segundo plano de la sesión de Claude; relanzarlo si no responde. Desde
el 18 oct admite los ids jerárquicos de las subtareas de Beads
(`garage-NNN.N`); antes, con ellas en la exportación, `/state.json` daba 503.

## Beads y documentación al continuar

```bash
bd list --all --limit 0
bd show garage-031
bd --sandbox --dolt-auto-commit off --actor claude update <id> --append-notes 'Resultado comprobado'
bd --sandbox --dolt-auto-commit off --actor claude export --output .beads/issues.jsonl
```

No bd init/sync/dolt push/pull, no staging. No commits, pushes, despliegue,
.env, migraciones/cargas en Neon, bucket público o planes de pago.
