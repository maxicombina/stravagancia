# garage-030, fases 1–2: «modo token» y fuente Strava

Fecha: 18 oct 2026. Autor: Claude (implementador). Desarrolla las fases 1 y 2 de
`.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md` con el alcance de su
§0: **modo token** (el mismo refresh token de Stravagancia mediante
`strava_integration.utils.refresh_access_token()`), sólo la cuenta del
propietario (`GARAGE_STRAVA_USER`), sólo ciclismo, **sin OAuth**, sin
`cryptography`. Rama `codex/garage-plan`, sin commits; nada en Neon.

## Decisiones concretas dentro de la especificación maestra

1. **Migración `0010_strava_source`** (aditiva salvo los dos CHECK ampliados):
   `StravaAccount` (propietario único, `athlete_id` único, `mode` env|oauth,
   tokens vacíos en env, por CHECK), `StravaGear` (sin FK a la cuenta),
   `StravaEvent` (sin propietario, clave de deduplicación única),
   `ActivitySource.external_id/gear_id/possible_duplicate`, `ImportRun.items_imported/items_skipped`.
   CHECK nuevos: tipo ∈ {fit, strava}; strava ⇒ `external_id` > 0 y
   `session_index = 0`; fit ⇒ `external_id` nulo y `gear_id` vacío; un trabajo
   Strava no tiene manifiesto ni total; unicidad parcial `(owner, external_id)`.
2. **Marca «posible duplicado»**: booleano `ActivitySource.possible_duplicate`
   en la misma 0010 (sin migración extra y sin tocar `manual_overrides`). Se
   pone al llegar una fuente que no pudo unirse (≥ 2 candidatas o la única ya
   tiene fuente Strava activa); «Unir con…» y «No es un duplicado» la limpian.
   Las candidatas de «Unir con…» se calculan al leer (±6 h, sin escribir).
3. **Vinculación**: candidata = salida propia de ciclismo (familia) o con
   deporte desconocido cuyo punto de comparación cumple |Δinicio| ≤ 90 s y
   |Δdistancia| ≤ 2 % de la mayor (o alguna desconocida). Punto: cada fuente FIT
   activa; sin FIT activa, inicio y distancia efectivos de la salida (manual o
   Strava). Un FIT nuevo sólo se une a una salida con Strava activa y sin FIT
   activa (comparando con la observación Strava).
4. **Precedencia**: fuentes activas ordenadas por clase (fit antes que strava) y,
   dentro de la clase, por la más reciente; manual siempre primero. Excepción:
   `sport_type` específico de Strava sustituye al `cycling` genérico del FIT.
   La bici sale del `gear_id` de la fuente Strava activa a través de
   `StravaGear.bike` (procedencia `strava`), salvo corrección manual.
5. **Borrado de datos Strava** (política §6.3/§7.4): un `delete` confirmado con
   404, un cambio a deporte no ciclista y «Quitar lo sincronizado» **borran** la
   fila `ActivitySource` Strava (no quedan observaciones). «Retirar» desde la
   ficha sigue marcando `withdrawn_at`; la sincronización respeta esa decisión
   y omite la actividad. Una salida que se queda sin ninguna fuente y sin
   correcciones de **medida** (inicio, deporte, distancia y los tres tiempos; el
   nombre, la bici y las notas no cuentan) se borra con su uso; si no, queda.
6. **«Quitar lo sincronizado desde Strava»** (casilla obligatoria) borra además
   los `StravaGear`, la fila `StravaAccount` y los eventos del atleta: el
   webhook deja de aceptar sus eventos hasta el siguiente «Sincronizar ahora» o
   «Importar», que vuelven a crear la fila. Los `ImportRun` se conservan.
7. **Bicis de Strava**: de `GET /athlete` (`bikes`, si viene) y de cada
   `gear_id` observado (nombre vacío). `retired` refleja Strava, no desvincula y
   su cambio recalcula las salidas afectadas como vincular o desvincular.
8. **Histórico**: `after` (fecha local → instante), páginas de 50 en orden
   ascendente (revisión: antes 200), hasta 4 páginas por pulsación (máx. 5); `processed = cursor =` páginas
   confirmadas, `total` nulo; una página y su punto de control en una sola
   transacción con el bloqueo del propietario y una única reconstrucción del uso.
   Errores ⇒ estado `failed` con `rate_limited`, `unauthorized`,
   `unexpected_failure` (red) o `invalid_metric`; se puede continuar.
9. **«Sincronizar ahora»**: `GET /athlete` (nombre y bicis), últimos 7 días (≤ 2
   páginas de 50) y hasta 10 eventos pendientes (revisión: antes 5 y 50). La ausencia como pista de borrado es
   de la fase 4: queda un punto de extensión con los ids vistos y la ventana.
10. **Webhook**: si `STRAVA_WEBHOOK_SUBSCRIPTION_ID` existe, otro id se descarta
   para todos; Garage persiste el evento (si el atleta tiene `StravaAccount`)
   antes de lo lento del legado y, tras el commit, un hilo por atleta y proceso
   que cierra su conexión (revisión); el
   legado sólo procesa eventos de un `Athlete.strava_id` suyo. Las pruebas del
   legado añaden `owner_id` (Strava siempre lo envía). `athlete` se ignora en
   modo env. En modo env se supone `activity:read_all` (el token del legado lo
   tiene): un 404 confirma el borrado.
11. **Perfiles por familia**: `cycling` cubre todas las claves de ciclismo
   (`garage/sports.py`); una clave específica sólo la suya; vacío, todas.
   También en la revisión de una salida.
12. **Límite conocido**: `refresh_access_token()` del legado no tiene `timeout`;
   no se toca aquí (sólo `views.py` del legado). Todas las llamadas propias de
   Garage usan `timeout=(5, 20)` y `json.loads(..., parse_float=Decimal)`.

## Archivos

Nuevos: `garage/sports.py`, `garage/services/strava_client.py`,
`strava_sources.py`, `strava_sync.py`, `garage/strava_views.py`,
`garage/strava_forms.py`, plantillas `strava.html`, `source_merge.html`,
migración 0010 y pruebas `garage/tests_strava_*.py`.
Cambiados: `models.py`, `ride_values.py`, servicios `rides`, `usage`,
`usage_profiles`, `ride_review`, `home`, `export`, `import_history`,
`ownership`; `history_views.py`, `usage_views.py`, `urls.py`, plantillas de
salida, histórico, trabajo y Más; `strava_integration/views.py` y sus pruebas;
`strava_app/settings.py` (dos variables); documentación de dominio, exportación,
fuentes, TESTING y handoff.

## Plan de pruebas

HTTP simulado con cuerpos JSON en texto (ejercita `parse_float=Decimal`),
datos sintéticos, PostgreSQL local. Cuenta env (sin configurar, otro usuario,
`GET /athlete`, atleta ya vinculado); 401 una renovación y luego
`unauthorized`; 429 con `X-RateLimit-Usage`; timeout en todas las llamadas;
canonización y omitidos; perfiles por familia; vinculación 0/1/2 y ya con
Strava; FIT posterior sólo a salida sólo-Strava; una Strava activa por salida;
separar y unir; precedencia campo a campo y excepción de deporte; bicis
vincular/desvincular/retirar con reconstrucción y corrección manual; histórico
(paginación, página vacía, CHECK de progreso, pausar/continuar/cancelar, 429
con cursor); webhook (atleta desconocido, suscripción ajena, legado, dedupe,
tope, hilo y conexión, `delete` falso y real); exportación aditiva; migración
sobre filas FIT; lista de pendientes; GET sin escrituras; presupuestos de
consultas. Después: pruebas del legado, suite completa, `check`,
`makemigrations --check`, `inspect`.

## Revisión de código (18 oct, tras la revisión independiente)

Hallazgos corregidos, todos con pruebas (sin migración nueva; 0010 sigue
siendo la única de esta fase):

1. **Bloqueante — ajustes.** `strava_app/settings.py` no declaraba
   `GARAGE_STRAVA_USER` ni `STRAVA_WEBHOOK_SUBSCRIPTION_ID`; ahora los lee de
   `os.getenv` con `''` por defecto. Como ese archivo se niega a importarse
   bajo pytest, la prueba analiza su código (`ast`) y exige ambas asignaciones.
2. **Coste del histórico.** Antes ≈ 82 consultas por actividad nueva (≈ 17 000
   por página de 200 dentro de un único bloqueo). Ahora: páginas de 50 con su
   punto de control; `StravaBatch` carga una vez por página las fuentes
   conocidas, las bicis de Strava y los puntos de comparación (`LinkIndex`,
   dos consultas por rango, actualizado en memoria al crear o unir); la
   validación de las filas de la página es `full_clean` sin consultas por
   restricción (`_validate_trusted`: formatos y `clean()` sí; UNIQUE/CHECK los
   hace PostgreSQL y un fallo deshace sólo el savepoint de esa actividad, que
   recarga el contexto); `Ride.clean()` comprueba la procedencia con una sola
   consulta (antes una por campo). Medido: ≈ 12 consultas por actividad nueva
   (presupuesto probado ≤ 15, y ≤ 4 si no cambia). «Sincronizar ahora»: como
   mucho 14 peticiones (`SYNC_MAX_CALLS`) y ninguna nueva tras 25 s
   (`REQUEST_SECONDS`); el histórico tampoco pide otra página tras 25 s.
3. **Webhook.** El hilo arranca con `transaction.on_commit`, como mucho uno por
   atleta y proceso (si ya hay uno, hace otra ronda); cada aviso se reclama
   (intento contado y confirmado) y la llamada a Strava, renovación incluida,
   va sin transacción abierta; la escritura toma primero el bloqueo del
   propietario y después la fila del evento, y comprueba que la cuenta sigue
   existiendo (se acabó la inversión con «Quitar lo sincronizado»). Un error no
   recuperable (`invalid_response`) se da por cerrado al quinto intento. Dos
   procesos pueden confirmar el mismo aviso: inocuo (instantánea idempotente
   bajo el bloqueo). Pruebas: ninguna llamada con `in_atomic_block` (base real,
   transaccional), un solo trabajador y ronda extra, y «Quitar lo
   sincronizado» termina mientras un aviso está en vuelo (dos conexiones).
4. **«Unir con…».** La salida que se vacía se conserva si tiene cualquier
   corrección manual (nombre, bici, notas incluidos) o excepciones de material;
   la página (`source_merge.html`) avisa antes del POST de qué se borra o se
   conserva y si quedará sin inicio. Los borrados por política (404, deja de
   ser ciclismo, «Quitar lo sincronizado») mantienen la regla de medidas.
5. Errores del trabajo: se acumulan entre páginas sin repetir (≤ 20); una
   página confirmada quita los transitorios (429, 401, red).
6. Un 429/401/red de los avisos en «Sincronizar ahora» deja la cuenta en
   `failed` con su código y un mensaje de error; además se avisa de los avisos
   pendientes y de si la semana quedó sin leer entera.
7. Un FIT nuevo que coincide con una salida que ya tiene otro FIT activo (de
   otro archivo) va a una salida nueva marcada «posible duplicado»; las
   sesiones del mismo archivo no se marcan entre sí (también en la vista previa).
8. Más → Strava: una sola consulta de bicis para todos los formularios.
9. Estados del trabajo en español (filtro `run_state`, también en el índice
   del histórico y en los trabajos FIT) y modalidades con `SPORT_LABELS`
   (filtro `sport_label`) en la salida, la lista y el histórico.
10. Cada selector se etiqueta «Bici de Garage para «…»» con su bici de Strava.
11. «Unir con…» sin candidatas muestra el estado vacío (200) y no escribe
   mensajes en la sesión.
12. Una actividad pedida por un aviso debe traer `athlete.id` de esta cuenta;
   si no, se omite y se registra sólo el código (`athlete`).
13. Pruebas añadidas: presupuestos de consultas, 404 sin `activity:read_all`
   (no borra ni llama a Strava), ajustes, y lo anterior. `source_merge.html`
   existe ahora (la lista de archivos ya la citaba).

Archivos tocados: `strava_app/settings.py`; `garage/models.py` (sólo
`Ride.clean` y `ActivitySource.clean`); `services/rides.py`
(`_validate_trusted`, `_recalculate(trusted=…)`, `fit_join_target` con el
hash); `services/strava_client.py`, `strava_sources.py`, `strava_sync.py`,
`import_history.py`; `strava_views.py`, `strava_forms.py`, `history_views.py`,
`templatetags/garage_ui.py`; plantillas `strava.html`, `source_merge.html`
(nueva), `history_run.html`, `history_index.html`, `usage_ride.html`,
`usage_rides.html`; pruebas `garage/tests_strava_*.py`; `docs/garage-domain.md`.
Pruebas: 118 de Strava (25 nuevas), 42 del legado y suite completa de
2201 pruebas + 45 subcasos; `check`, `makemigrations --check` y `inspect`
limpios. Pendiente igual que antes: fases 3–4 y probar contra Strava real.
