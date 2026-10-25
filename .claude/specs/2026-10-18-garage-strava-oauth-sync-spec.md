# Especificación: «Conectar con Strava» por usuario, sincronización, desnivel y potencia

Fecha: 18 de octubre de 2026. Autor: Claude (Fable 5.1). Revisión 2, tras dos
revisiones independientes (§10). Tareas Beads: activaría `garage-030` (aplazada
desde el 12 oct) y absorbe `garage-037` (desnivel) más la potencia pedida el
18 oct. **Sólo especificación: no implementar hasta que el usuario la apruebe.**
Rama `codex/garage-plan`; sin commits.

Pedido del usuario (18 oct): «vamos a tener sync desde strava, lo mismo que
stravagancia»; «la potencia me interesa»; y, sobre la autenticación de
Stravagancia (API habilitada a mano, token en variable de entorno), «cómo hace
probikegarage … el user pone "conectar con strava" y hay un flujo oauth2 … y
listo! … se puede hacer?».

## 0. Alcance acordado con el usuario (18 oct, revisión 3)

Respuestas del usuario a §9: (1) «de momento nada de usar/pass. usemos el token
como stravagancia, porque estoy en pruebas. pero deja apuntado como next
step»; (2) «de momento ciclismo»; (3) «sí, buena idea, cuenta de prueba. de
momento nada de oauth»; (4) y (5) pendientes de explicación (no hacen falta
ahora). En consecuencia:

- **Ahora (modo token)**: Garage sincroniza **sólo la cuenta del propietario**
  con el **mismo refresh token** de Stravagancia (variable de entorno
  `STRAVA_REFRESH_TOKEN`), a través de la misma función
  `strava_integration.utils.refresh_access_token()` (un solo camino de
  renovación, el mismo riesgo de rotación que ya corre el legado; nada de
  tokens en la base). El usuario de Garage al que pertenece ese atleta se
  indica con `GARAGE_STRAVA_USER` (nombre de usuario); la fila `StravaAccount`
  se crea con `mode='env'`, `athlete_id` leído de `GET /athlete` y sin tokens.
  No hay pantallas de conectar ni desconectar: Más → Strava muestra
  «Conectado con el token de Stravagancia (atleta …)», «Sincronizar ahora»,
  «Importar histórico desde…», las bicis de Strava con su bici de Garage, y
  el botón «Quitar lo sincronizado desde Strava» (§3 Desconectar, sin revocar).
  Sólo deportes de ciclismo (§3). Todo lo demás de §3–§8 se mantiene: webhook
  despachado por atleta y confirmado por API, histórico reanudable,
  vinculación FIT↔Strava, bicis por `gear_id`, desnivel y potencia,
  reconciliación diaria, `sync-all` con `GARAGE_SYNC_TOKEN`.
- **Variables de entorno ahora**: `GARAGE_STRAVA_USER`, `GARAGE_SYNC_TOKEN`,
  `STRAVA_WEBHOOK_SUBSCRIPTION_ID`. **No** hacen falta todavía
  `GARAGE_TOKEN_KEY` ni `GARAGE_BASE_URL`, ni la dependencia `cryptography`,
  ni la capacidad de atletas ni el dominio de vuelta en el panel de Strava.
- **Siguiente paso (garage-040, apuntado)**: «Conectar con Strava» por usuario
  tal como describe §2 (OAuth 2.0, tokens cifrados, amigos), con `mode='oauth'`
  en la misma tabla, y antes la prueba con una cuenta de usar y tirar (§3
  Legado) para ver cómo afecta al token del legado. `StravaAccount` y
  `StravaGear` se diseñan ya para admitirlo sin otra migración.
- Las fases de §7 quedan: 1 **modo token** (fila `StravaAccount` env, Más →
  Strava, comando/ajuste `GARAGE_STRAVA_USER`); 2 fuente Strava; 3 desnivel y
  potencia; 4 operación; 5 = garage-040 (OAuth por usuario, futuro).

## 1. Qué hay hoy

- **Stravagancia** (`strava_integration/`) es de una sola cuenta: un
  `STRAVA_REFRESH_TOKEN` conseguido a mano, en una variable de entorno;
  `utils.refresh_access_token()` lo renueva antes de cada llamada y reescribe el
  `.env` en local. En Render sólo está el refresh token. Webhook en
  `/archive/strava/webhook/strava/` (Strava admite **una suscripción por
  aplicación**), que guarda la actividad en la tabla `Activity` del legado y,
  si es `create`, la renombra en un hilo. Hoy, un evento de **otro atleta** se
  guardaría también en `Activity` por el `Athlete.objects.first()` de reserva.
  `Activity` no guarda `gear_id` ni potencia; sí `total_elevation_gain`. Las
  llamadas a Strava no tienen `timeout`.
- **Garage** importa FIT y entradas manuales. `Ride` tiene procedencia por campo
  (`manual` > `fit` > `unknown`, por la observación más reciente entre fuentes),
  `ActivitySource` con identidad propietario + SHA-256 + índice de sesión y los
  CHECK `garage_activitysource_kind_fit` y `garage_activitysource_hash_valid`;
  `ImportRun` con `garage_importrun_source_fit` y restricciones de progreso
  (`cursor ≤ processed`, completado ⇒ `cursor = processed`). `METRIC_FIELDS`
  (`ride_values.py`) alimenta a la vez el uso por objeto, las correcciones
  manuales y la lista de salidas «pendientes». No hay desnivel ni potencia.
- **Decisión garage-029 (12 oct)**: opción B, adaptador Strava propio de Garage,
  retirable, con `gear_id` para la bici; riesgo de la API Policy aceptado por el
  usuario para uso personal (no es un dictamen jurídico). Nota del 16 oct: con
  amigos como usuarios, OAuth por usuario y comprobar el límite de atletas por
  aplicación.
- Reglas del proyecto: no reutilizar `Activity` ni cambiar el legado salvo lo
  imprescindible (y con sus pruebas); migraciones nuevas sin reordenar ni
  destruir, y en Neon sólo con el despliegue de garage-023 (`entrypoint.sh`
  ejecuta `migrate` en cada arranque de Render: ese despliegue aplicará 0009 a
  0011 de una vez; hasta entonces no levantar `web` de Docker Compose); sin
  servicios de pago ni infraestructura nueva; pruebas con HTTP simulado (el
  arranque de pruebas bloquea los sockets).

## 2. Qué es «Conectar con Strava» (OAuth 2.0, código de autorización)

1. Una sola vez, quien despliega registra la aplicación en Strava
   (`strava.com/settings/api`): ya existe (`STRAVA_CLIENT_ID`/`SECRET`). Allí se
   fija el **Authorization Callback Domain** (uno solo por aplicación: el de
   producción; para desarrollo local, o se comprueba que `localhost` convive o
   se crea una segunda aplicación «Garage dev» con su propio id) y, si van a
   conectarse amigos, se **pide más capacidad de atletas**: una aplicación
   nueva sólo puede conectar la cuenta de su desarrollador hasta que Strava
   amplía ese límite (puede exigir revisión de la app; comprobar en el panel).
2. Cada persona, en Más → Strava, toca el botón oficial «Connect with Strava».
   Garage la manda a `https://www.strava.com/oauth/authorize` con `client_id`,
   `redirect_uri`, `response_type=code`, `approval_prompt=auto`, `scope` y un
   `state`.
3. Strava muestra «Garage quiere acceder a…»; la persona acepta (puede quitar
   permisos en esa pantalla).
4. Strava la devuelve a `redirect_uri` con `code` y `scope` concedido (o con
   `error=access_denied`).
5. El servidor comprueba `state`, cambia el `code` por tokens en
   `https://www.strava.com/oauth/token` (`grant_type=authorization_code`):
   recibe `access_token` (6 h), `refresh_token`, `expires_at` y el atleta. Los
   guarda **por usuario**, cifrados, en la base de datos.
6. Desde entonces Garage renueva el token sola (`grant_type=refresh_token`)
   cuando falta menos de 1 h para que caduque, y guarda el refresh token que
   devuelve Strava (puede ser nuevo). «Desconectar» borra los tokens y, salvo
   la excepción del legado (§3), revoca el acceso en Strava
   (`oauth/deauthorize`; desde el 1/6/2027, `oauth/revoke`).

Las variables de entorno son las de la aplicación (`STRAVA_CLIENT_ID`,
`STRAVA_CLIENT_SECRET`) más las de servidor de §5. El refresh token manual del
legado sigue existiendo sólo para Stravagancia.

**Detalles obligatorios del flujo**
- `state`: `secrets.token_urlsafe(32)`, guardado en la sesión con el `pk` del
  usuario y la hora; de un solo uso (se consume al volver), caduca a los
  10 minutos, se compara con `hmac.compare_digest`. La vuelta (`callback`)
  exige sesión iniciada y el mismo usuario; no admite `next`: siempre aterriza
  en Más → Strava (sin redirecciones abiertas).
- `redirect_uri` se construye desde `GARAGE_BASE_URL` (configuración), nunca
  desde `request.build_absolute_uri()`: detrás de Render `is_secure()` es falso
  y saldría `http://`. Producción (garage-023) añade
  `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE`;
  `SameSite=Lax` (Strict rompe la vuelta). `SECRET_KEY` real en Render (el
  `state` viaja en la sesión firmada).
- Permisos pedidos: `read`, `activity:read`, `activity:read_all` y
  `profile:read_all`. Se guarda el `scope` concedido y cada función se activa
  sólo con su permiso: sin `activity:read` no hay salidas (se avisa y no se
  intenta); con `activity:read` pero sin `activity:read_all` no se verán las
  privadas (aviso); sin `profile:read_all` no se listan las bicis (aviso).
- Un atleta de Strava sólo puede estar conectado a **un** usuario de Garage:
  se comprueba antes de guardar; si ya lo está, error claro y sin revocar (la
  concesión es del otro usuario). Una cuenta revocada desde fuera conserva su
  fila hasta la purga de 30 días y mientras tanto bloquea igual («pendiente de
  purga hasta el …»); desconectar desde la app borra la fila al momento. Documentar que una nueva autorización puede
  haber rotado el refresh token de la cuenta ya conectada: si falla, verá
  «reconectar».
- Las vistas de conexión y renovación llevan `@sensitive_variables` y
  `@sensitive_post_parameters`; nunca se registra la respuesta de tokens. El
  `code` llega por GET (puede quedar en registros de acceso): es de un solo uso
  y se canjea al instante; aceptado.
- Marca: botón oficial «Connect with Strava», «Powered by Strava» donde se
  muestren datos de Strava, y una línea en la pantalla de conexión con qué se
  guarda y qué pasa al desconectar.

## 3. Decisiones (con las opciones descartadas)

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Cuenta | a) crear la cuenta de Garage al conectar con Strava (ProBikeGarage); b) usuario y contraseña de Garage, y Strava como conexión opcional | **b)**: no ata la identidad a Strava, Garage funciona sin Strava (FIT y manual) y desconectar no borra la cuenta. |
| Tokens | a) variable de entorno (hoy); b) base de datos en claro; c) base de datos cifrados | **c)**: `StravaAccount` por usuario con los tokens cifrados con `MultiFernet` (`cryptography`; `GARAGE_TOKEN_KEY` admite varias claves separadas por comas para rotar). Sin clave, conectar está desactivado y la pantalla lo dice. `InvalidToken` ⇒ cuenta en «reconectar», nunca un 500. Fuera de admin, logs y exportación. |
| Renovación | — | Dentro de `transaction.atomic()` con `select_for_update()` sobre la fila de `StravaAccount`; se relee `expires_at` tras bloquear (otro proceso puede haber renovado). Un 401 ⇒ renovar una vez; si vuelve a fallar, releer la fila y sólo entonces marcar «reconectar». Todas las llamadas a Strava con `timeout=(5, 20)`. |
| Legado | a) migrar Stravagancia a OAuth por usuario ahora; b) dejarlo como está | **b)**: fuera de alcance (tarea aparte, §9). **Excepción obligatoria**: revocar en Strava afecta a toda la aplicación para ese atleta. Si el atleta que se desconecta es el del legado (`strava_integration.Athlete.strava_id`), Garage **sólo borra sus tokens localmente**, no revoca, y lo dice. Antes de que el propietario conecte su cuenta en producción, probar con una cuenta de usar y tirar si la nueva autorización rota el refresh token del legado: esa cuenta obtiene primero un refresh token manual (como el legado), después autoriza por OAuth, y se comprueba si el manual sigue renovando. Documentar la recuperación (regenerar el token y actualizar la variable en Render). El `delete` falsificado contra el legado (borra `Activity` por id sin confirmar) es anterior a esta especificación y queda fuera de alcance; se anota. |
| Webhook | a) endpoint nuevo; b) compartir el existente | **b)**, obligado (una suscripción por aplicación). El endpoint existente **despacha por atleta**: el legado sólo procesa eventos cuyo `owner_id` sea el de su propio atleta (se cierra el hueco de `Athlete.objects.first()`; es el único cambio en código del legado, con sus pruebas); Garage sólo los de atletas con `StravaAccount` activa; el resto se descarta sin guardar. Se comprueba `subscription_id` contra la suscripción configurada. Los eventos **no están firmados**: son **pistas**, nunca órdenes (ver «Confirmación»). Cada evento aceptado se persiste (`StravaEvent`, deduplicado por `subscription_id, owner_id, object_id, aspect_type, event_time`, con tope de 500 pendientes por atleta) **antes** de responder 200 y antes de lanzar el hilo que lo procesa; el hilo cierra su conexión a la base al terminar (`connection.close()`); la fila es la verdad: la sincronización diaria procesa lo que quedó pendiente. La verificación GET compara con `compare_digest`. |
| Confirmación de eventos | — | `delete` ⇒ `GET /activities/{id}` con el token del atleta: sólo con 404 **y** permiso `activity:read_all` se retira la fuente. `athlete` con `authorized=false` ⇒ sólo se desconecta si `GET /athlete` devuelve 401. `create`/`update` ⇒ se pide la actividad y se guarda lo que diga Strava. |
| Qué salidas | a) todo; b) sólo ciclismo | **b)**: `sport_type` Ride, GravelRide, MountainBikeRide, EBikeRide, EMountainBikeRide, VirtualRide, Velomobile, Handcycle; el resto se cuenta como omitido. Coherente con «sólo Rides» del legado. Se **canonizan** a las claves que ya usa Garage (`cycling`, `gravel_ride`, `mountain_bike_ride`, `e_bike_ride`, `virtual_ride`…); para `sport_type`, un valor específico de Strava prevalece sobre el genérico `cycling` del FIT (única excepción a la precedencia por clase; el `sub_sport` del FIT se evaluará con la muestra). Para que eso no saque salidas de los **perfiles de uso por deporte** (hoy comparan la clave exacta), los perfiles pasan a comparar por **familia**: un perfil con `cycling` cubre todas las claves de ciclismo; un perfil con una clave específica (`gravel_ride`, `virtual_ride`…) sólo esa. Las claves actuales siguen funcionando igual. |
| Qué campos | a) todo lo que devuelve Strava; b) lo que Garage usa | **b)**: inicio UTC, nombre, deporte, distancia, tiempo en movimiento, tiempo transcurrido, `gear_id`, desnivel positivo, potencia media, máxima y **ponderada de Strava** (`weighted_average_watts`, no es la NP de Garmin; se etiqueta así), energía (kJ) y `device_watts`. Nada de GPS, salud, mapa ni polilíneas. Strava no da tiempo de temporizador: desconocido. Los números se leen con `json.loads(..., parse_float=Decimal)`: nunca un float intermedio (dominio §9). |
| Potencia estimada | — | Si `device_watts` es falso, Strava estimó: **no se guardan** ni vatios ni kJ (desconocidos). Sólo potenciómetro. Valores fuera de rango (> 10 000 W) ⇒ desconocidos. |
| Fuente e identidad | — | `ActivitySource` con `source_kind='strava'`, `external_id` = id de actividad de Strava (único por propietario, parcial), `gear_id` observado, `file_hash = sha256("strava:{athlete_id}:{activity_id}")` y `session_index=0`: así la identidad única y el CHECK de hash actuales **se conservan** tal cual. `parser_version='strava-api-v3'`. Procedencia por campo `strava` con `source_id`. |
| Precedencia | a) observación más reciente (hoy, entre FIT); b) por clase | **b)**: `manual` > `fit` > `strava` > `unknown`, campo a campo; entre fuentes de la misma clase, la más reciente (como hoy). FIT prevalece en lo que mide; Strava rellena lo que el FIT no trae (bici por `gear_id`, desnivel y potencia cuando el FIT no los tiene). Reimportar un FIT después de Strava no cambia esto. |
| Bici | — | `StravaGear` (propietario, `gear_id`, nombre, `retired`, bici de Garage o nula), **sin FK a la cuenta**: sobrevive a desconectar y reconectar. `gear_id` es una observación de la fuente; la bici se resuelve en `_recalculate` a través del vínculo, procedencia `strava`; una corrección manual prevalece. Vincular, desvincular o retirar un gear recalcula las salidas afectadas y reconstruye el uso. |
| Misma salida por FIT y por Strava | a) nunca fusionar (contrato §10, pensado para FIT↔FIT); b) vincular automáticamente | **b)** sólo **entre clases distintas** y de forma determinista: se compara la observación Strava (inicio, distancia) con la observación FIT activa de cada Ride de ciclismo del propietario (o con inicio y distancia manuales si no hay fuente); candidato si el inicio difiere ≤ 90 s y la distancia ≤ 2 % (o una es desconocida). **Exactamente un** candidato ⇒ se une; cero ⇒ Ride nueva; dos o más ⇒ Ride nueva marcada «posible duplicado». Un FIT que llega después sólo se une a una Ride que tenga sólo fuente Strava. Como máximo **una fuente activa por clase y Ride**. Nunca FIT↔FIT ni Strava↔Strava (un segundo id de Strava para la misma Ride queda como «posible duplicado»). «Una fuente Strava activa por Ride» es una regla de servicio, sin restricción en la base: las fuentes FIT conservan hoy la posibilidad de varias por Ride y no se cambia. |
| Separar y unir | — | Servicio bajo bloqueo del propietario que **mueve** una fuente de una Ride a otra (única relajación de la inmutabilidad `source.ride`, sólo aquí): «Separar» crea una Ride nueva con esa fuente; «Unir con…» mueve la fuente a la Ride elegida (si respeta «una por clase»). Ambas recalculan las dos Rides y reconstruyen el uso. §10 del dominio se enmienda (excepción entre clases); la vista previa de importación deja de decir «No se fusionarán automáticamente» y explica la regla. |
| Histórico inicial | a) todo de golpe; b) reanudable por páginas | **b)**: `ImportRun` con `source_kind='strava'`, `after` = fecha elegida (por defecto, la salida más antigua de Garage o el 1 de enero del año anterior); 200 actividades por página; presupuesto por petición como el FIT; pausar, continuar y cancelar. Progreso: `processed = cursor =` páginas confirmadas, `total` nulo (se cumplen los CHECK actuales); contadores nuevos `items_imported` e `items_skipped`; errores con códigos nuevos `rate_limited` y `unauthorized` y `session_index` nulo. |
| Mantenerse al día | — | Webhook + **reconciliación diaria**: vuelve a pedir las actividades de los últimos 7 días (cambios de bici que el webhook no avisa; eventos perdidos con Render dormido de 00:15 a 09:00), procesa `StravaEvent` pendientes y **trata la ausencia** de una actividad conocida en esa ventana como pista de borrado (confirmación por `GET /activities/{id}`: 404 ⇒ fuente retirada; deporte no ciclista ⇒ retirada; si sigue ⇒ se mantiene). **Sólo con `activity:read_all`**: sin ese permiso una salida puesta en «Sólo yo» desaparece de la lista y su GET da 404 sin estar borrada, así que entonces no se detectan borrados (ni por ausencia ni por webhook: un 404 se trata como desconocido) y la pantalla recomienda conceder el permiso. Borrados fuera de 7 días: sólo por webhook (límite documentado). |
| Disparo | — | «Sincronizar ahora» (`POST /garage/strava/sync/`, sesión) y `POST /garage/strava/sync-all/`: `@csrf_exempt`, sólo POST, cabecera `X-Sync-Token` comparada con `compare_digest`, 403 genérico; si `GARAGE_SYNC_TOKEN` falta o es corto, 404. Trabajo acotado por llamada (una cuenta o N eventos) y respuesta `{"pending": n}`: el Worker de Cloudflare ya existente repite hasta `pending=0` o K veces, a las **09:05 Madrid**, cuando el propio Worker ya mantiene despierto a Render (así no añade horas de Render; a las 07:00 costaría ~15 min/día). `gunicorn --timeout 60`. El token va como **secreto del Worker** (`env.SYNC_TOKEN`), nunca en `cloudflare-worker.js`. |
| Límites de Strava | — | 429 ⇒ leer `X-RateLimit-Usage`, parar toda la ejecución, guardar el cursor y mostrar «reintentar en 15 min»; nunca bucles. Los límites son por aplicación y los comparte el legado. Comprobar en el panel los vigentes. |
| Revocación externa | — | 401 persistente al renovar ⇒ cuenta «revocada» (sin tokens). Por la API Policy §7.4, si no se reconecta en 30 días, la sincronización diaria purga sus observaciones Strava (como «quitar lo sincronizado»). |
| Desconectar | — | Renueva el token si hace falta, revoca en Strava (salvo el atleta del legado) y borra tokens y `StravaAccount` pase lo que pase con la revocación. Casilla **marcada por defecto** «Quitar también lo sincronizado desde Strava» (§7.4): retira todas las fuentes Strava; las Rides cuya única fuente era Strava y sin correcciones de **medida** (la bici o las notas corregidas a mano no cuentan) se borran con su uso y excepciones; las demás conservan Ride y correcciones y quedan «pendientes» si pierden la fecha; los vínculos de bici (`StravaGear`) se borran. Desmarcarla es una decisión explícita de la persona, documentada como desviación de §7.4. Al borrar un usuario de Garage, un `pre_delete` revoca su concesión (salvo legado). |
| Desnivel y potencia en el motor | a) sólo mostrar; b) también umbrales | Desnivel: **b)** (`elevation_gain_m` fluye a `ItemUsage`; umbral en reglas y aplazamientos, lo primero que llegue). Potencia: **a)** sólo por salida y en estadísticas; no fluye a `ItemUsage`. Un umbral por energía (kJ) queda como idea posterior. |
| Desnivel de distinto origen | — | Se muestra el de la fuente que prevalece; nunca se suman. Sin lectura previa de desnivel (`UsageBaseline` no lo admite): el desnivel de toda la vida de una pieza es sólo lo observado. |

## 4. Modelos y migraciones (locales; en Neon sólo con el despliegue de garage-023)

**0010 — fuente Strava** (en `garage`):
- `StravaAccount(OwnedResource)`: `owner` único; `athlete_id` (BigInteger,
  único); `athlete_name`; `mode` (`env` ahora, `oauth` en garage-040);
  `scopes`; `access_token_enc`, `refresh_token_enc` (vacíos en modo `env`);
  `expires_at`; `connected_at`; `revoked_at` (nulo); `last_sync_at`;
  `last_sync_status`; `last_error_code`. Sin campo en claro con el token. No se
  registra en el admin ni en la exportación.
- `StravaGear(OwnedResource)`: `gear_id` (texto, único por propietario),
  `name`, `retired`, `bike` (FK nula, PROTECT). Sin FK a la cuenta.
- `StravaEvent` (sin propietario: el atleta puede no estar conectado):
  `subscription_id`, `athlete_id`, `object_type`, `aspect_type`, `object_id`,
  `event_time`, `updates` (JSON acotado), `received_at`, `processed_at`,
  `error_code`, `attempts`; unicidad por la clave de deduplicación; purga a los
  30 días. Ni en admin ni en exportación.
- `ActivitySource`: `external_id` (BigInteger, nulo) y `gear_id` (texto,
  vacío); CHECK `source_kind IN ('fit','strava')` (sustituye a
  `garage_activitysource_kind_fit`); CHECK strava ⇒ `external_id` no nulo y
  `session_index=0`; fit ⇒ `external_id` nulo; unicidad parcial
  `(owner, external_id)` para strava. `hash_valid` e `identity_unique` se
  conservan (§3 «Fuente e identidad»). `external_id` es inmutable (`clean`); separar y unir sólo cambian `ride`.
- `ImportRun`: CHECK `source_kind IN ('fit','strava')` (sustituye a
  `garage_importrun_source_fit`); `items_imported`, `items_skipped` (nulos).
- `ride_values`: clase `strava` en `validate_provenance` (con `source_id`);
  `ERROR_CODES` + `rate_limited`, `unauthorized`.
- Puntos del código que hoy dicen `kind == "fit"` y deben admitir `strava`:
  `Ride.clean`, `ItemUsage.clean`, `usage._validate_canonical_ride`,
  `export._ride` y la validación de `sources` (rechaza `source_kind != 'fit'`),
  `rides._mutate` (nombre de restricción), textos «Retirar fuente FIT»,
  `ActivitySource.__str__`, `ImportRun.__str__` («FIT import»), el mensaje de
  `rides._snapshot`, «Only FIT provenance has a source» en
  `validate_provenance`, «FIT · sesión» y «Sin fuentes FIT activas» en
  `usage_ride.html`, y los `.only()` de `service_usage.py` y `views.py`.

**0011 — desnivel y potencia** (en `garage`):
- `METRIC_FIELDS` se divide: `USAGE_METRICS` = distancia, tres tiempos y
  `elevation_gain_m` (lo que fluye a `ItemUsage`); `RIDE_METRICS` =
  `USAGE_METRICS` + `average_power_w`, `max_power_w`, `weighted_power_w`,
  `energy_kj` (sólo Ride y ActivitySource). Las correcciones manuales admiten
  `RIDE_METRICS`. El criterio de salida «pendiente» y la cobertura
  (`history_queryset`, `coverage`) **no cambian**: siguen en los cuatro campos
  originales más bici, inicio y deporte vacío, como hoy.
- `RideValues` (Ride y ActivitySource): los cinco campos nuevos
  `Decimal(20,3)`, nulos, con `exact_usage_value` y CHECK de rango como los
  demás; validación de plausibilidad en el parser y el adaptador.
- `ItemUsage`: `elevation_gain_m`.
- `MaintenanceRule` y `MaintenanceSnooze`: `elevation_gain_m`; se sustituyen
  `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` por
  versiones que lo incluyan; CHECK positivos nuevos. Se amplían las tuplas:
  `MaintenanceRule.clean/clean_fields`, `SNOOZE_AMOUNTS`,
  `maintenance_due.METRICS` y sus `.only()`, `presentation.UNITS/NAMES`,
  `thresholds()`, `snooze_reached`, `statistics.METRICS`, `monthly.METRICS`,
  los formularios de regla, vida útil y posponer (unidad «m»).
- Exportación (`garage-export` v1, aditiva): columnas nuevas en `rides`,
  `sources` (+ `source_kind`, `external_id`, `gear_id`), `maintenance_rules`,
  `snoozes`; tabla `strava_gear` (gear_id, nombre, retirado, bici); `units`
  nuevas (`elevation_gain_m: metres`, vatios, kJ); `omitted` añade «tokens y
  eventos de Strava». Ampliar `SOURCE_FIELDS` amplía las columnas CSV de
  `sources`: documentado en `garage-export.md`.

Ninguna de las dos migraciones borra, cambia ni reordena datos; 0010 y 0011
**sustituyen cuatro CHECK** por otros más amplios que las filas actuales
cumplen. Eso no es estrictamente «sólo aditivo» como pide CLAUDE.md, y es
inevitable mientras exista `source_kind='fit'` como CHECK: se dice
explícitamente al usuario para que lo apruebe. Pruebas de migración sobre
filas FIT y reglas existentes.

## 5. Configuración y operación (lo hace el usuario)

- Strava, panel de la aplicación: Authorization Callback Domain de producción
  (y decidir cómo se prueba en local: `localhost` junto al de producción, si
  Strava lo admite, o una aplicación «dev» aparte); capacidad de atletas > 1 si
  se conectarán amigos; límites de peticiones vigentes; `subscription_id` de la
  suscripción de webhook (para comprobarla).
- Variables de entorno nuevas: `GARAGE_BASE_URL`, `GARAGE_TOKEN_KEY` (una o
  varias claves Fernet), `GARAGE_SYNC_TOKEN` (≥ 32 bytes) y
  `STRAVA_WEBHOOK_SUBSCRIPTION_ID`. Se generan con
  `manage.py garage_strava_keys`, que sólo las imprime una vez: **no escribe
  `.env`** ni ningún archivo.
- Producción (garage-023): `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`, `SECRET_KEY` real.
- Worker de Cloudflare: segundo cron (09:05 Madrid) despachado por `event.cron`
  en el mismo Worker, con el secreto `SYNC_TOKEN` en sus bindings; bucle hasta
  `pending=0` o K intentos. Cada petición despierta a Render como `/healthz`.
- Dependencia nueva: `cryptography` (sin coste, sin infraestructura).
- Antes del 1/6/2027: `oauth/revoke` y el nuevo dominio de la API. Garage usa
  su propia constante base; la duplicada del legado (`services.py`,
  `renaming.py`) no se toca aquí (tarea de 2027 ya anotada).
- Política de Strava (riesgo aceptado en garage-029, ahora por cada persona que
  conecta): cada amigo autoriza su propia cuenta; sus datos se guardan sólo
  para él; desconectar borra tokens de inmediato y, por defecto, lo
  sincronizado (§7.4, ≤ 30 días; también tras revocación externa); los
  borrados llegan por webhook y por la ausencia en la ventana de 7 días (§6.3,
  ≤ 48 h, salvo borrados antiguos). No es un dictamen jurídico.

## 6. Pantallas

- **Más → Strava**: estado («No conectado» / «Conectado como … desde el …»,
  permisos concedidos, última sincronización y resultado), botón oficial
  «Connect with Strava» con la línea de aviso, «Sincronizar ahora», «Importar
  histórico desde …» (fecha), lista de bicis de Strava con su bici de Garage
  (selector, «sin vincular»), «Desconectar» con la casilla «Quitar también lo
  sincronizado desde Strava» (marcada). «Powered by Strava» donde haya datos.
- **Salidas**: origen de cada salida (Garmin, Strava, ambas, manual) y la marca
  «posible duplicado» con «Unir con…»; en la ficha: desnivel y potencia cuando
  existen («estimada por Strava: no se guarda» sin potenciómetro); «Separar
  fuente» y «Unir con…».
- **Histórico**: el trabajo Strava como los de FIT, con páginas en vez de
  sesiones; pausar, continuar, cancelar; regla de vinculación explicada.
- **Bici y componente**: desnivel junto a km y horas («2.795 km · 31.200 m»).
- **Reglas, vida útil y posponer**: campo «Desnivel (m)»; «lo primero que
  llegue» incluye los metros.
- **Estadísticas**: desnivel del período y por bici; potencia media del
  período ponderada por tiempo en movimiento (si falta, por temporizador; si
  falta, la salida se excluye y se cuenta); máxima del período; kJ totales; la
  potencia ponderada de Strava sólo por salida (no se promedia). Sin segundo
  eje en el gráfico.
- **Inicio**: por bici «km · h · m».

## 7. Fases (cada una con especificación corta, pruebas y revisión)

1. **Conexión**: `StravaAccount`, cifrado, connect/callback/disconnect
   (excepción del legado), Más → Strava, renovación con bloqueo, comando de
   claves, configuración de producción. Sin sincronizar todavía.
2. **Fuente Strava**: migración 0010, procedencia `strava`, precedencia por
   clase, vinculación FIT↔Strava determinista, separar y unir, `StravaGear`,
   histórico reanudable, «Sincronizar ahora», despacho del webhook por atleta
   con el hueco del legado cerrado, `StravaEvent` con confirmación por API,
   perfiles de uso por familia de deporte.
3. **Desnivel y potencia**: migración 0011, parser FIT (campos de sesión
   confirmados en el perfil de fitdecode: 20 `avg_power` W, 21 `max_power`,
   22 `total_ascent` m, 34 `normalized_power`, 48 `total_work` J → kJ;
   centinelas inválidos ⇒ desconocido; subir `PARSER_VERSION`; comprobar con
   la muestra), materialización, reglas y aplazamientos por desnivel,
   pantallas y estadísticas, exportación.
4. **Operación y retirada**: reconciliación diaria, ausencia como pista,
   `sync-all` acotado y el Worker, 429 y reintentos, revocación externa y
   purga a 30 días, desconectar con borrado, purga de eventos, documentación
   de despliegue (garage-023).

Orden: 1 → 2 → 3 → 4. El desnivel por FIT (parte de 3) podría hacerse sin
Strava, pero el usuario quiere ambas cosas.

## 8. Pruebas

Todo con HTTP simulado (nunca Strava real) y datos sintéticos:
- OAuth: `state` ausente, distinto, caducado, de otro usuario o reutilizado ⇒
  rechazo; `access_denied`; intercambio con respuesta inválida; permisos
  parciales y funciones desactivadas; atleta ya conectado por otro usuario;
  tokens cifrados (no aparecen en claro en la tabla, admin, logs, páginas de
  error con DEBUG ni exportación); rotación de claves; renovación concurrente
  (dos hilos, bloqueo real) sin marcar «reconectar» a una cuenta sana; 401
  persistente ⇒ revocada; `timeout` en todas las llamadas.
- Webhook: evento de atleta desconocido ⇒ descartado y no guardado en el
  legado; `subscription_id` ajeno ⇒ descartado; evento del atleta del legado
  ⇒ como hoy; `delete` falso (la actividad sigue) ⇒ nada; `delete` real ⇒
  fuente retirada; `authorized=false` falso ⇒ nada; respuesta < 2 s sin llamar
  a Strava dentro de la petición; deduplicación; tope por atleta; el hilo
  cierra la conexión.
- Fuente: identidad por hash derivado; vinculación con uno, cero y dos
  candidatos; FIT posterior sólo a Ride Strava; una fuente activa por clase;
  separar y unir recalculan las dos Rides y el uso; precedencia por clase campo
  a campo (incluido `sport_type` específico) y perfiles por familia de
  deporte; ausencia y 404 sin `activity:read_all` no retiran nada; reimportar
  FIT tras Strava;
  `parse_float=Decimal`; `device_watts` falso ⇒ sin vatios ni kJ; valores fuera
  de rango.
- Bicis: vínculo `gear_id`→bici, cambio de bici recogido por la reconciliación,
  desvincular y retirar reconstruyen el uso, corrección manual prevalece,
  vínculos que sobreviven a desconectar sin borrar datos.
- Histórico: paginación, página vacía, deporte omitido y canonizado, 429 con
  cursor, pausar/continuar, presupuesto, concurrencia con bloqueo del
  propietario; la lista de pendientes no cambia por los campos nuevos.
- Desnivel y potencia: parser (válido, ausente, centinela), `ItemUsage` con
  desnivel y sin potencia, reglas y aplazamientos por metros (incluidas reglas
  sólo de desnivel), estadísticas ponderadas con tiempos nulos, exportación y
  columnas CSV, migraciones sobre filas y reglas existentes.
- Operación: `sync-all` con token inválido, ausente o corto; `pending`;
  ausencia confirmada o no; purga a 30 días; desconectar con y sin borrado
  (incluida una Ride con sólo la bici corregida); `pre_delete`; GET sin
  escrituras; presupuestos de consultas.
- Suite completa, `check`, `makemigrations --check`, capturas y revisión
  independiente por fase; pruebas del legado tras el cambio del webhook.

## 9. Preguntas abiertas para el usuario

1. ¿Confirmás usuario y contraseña de Garage, con Strava como conexión
   opcional (no «entrar con Strava»)?
2. ¿Sólo deportes de ciclismo, o también otros (correr, para zapatillas)?
3. Tu propia cuenta es la del legado: ¿aceptás probar antes con una cuenta de
   usar y tirar cómo afecta a Stravagancia? ¿Querés, en una tarea aparte, que
   Stravagancia pase también a OAuth por usuario y deje de reescribir `.env`?
4. Capacidad de atletas y dominio de vuelta en tu aplicación de Strava: ¿lo
   gestionás vos cuando toque? ¿Preferís una aplicación «dev» aparte para
   probar en local?
5. ¿De acuerdo con que «Quitar lo sincronizado» venga marcado por defecto al
   desconectar?

## 10. Revisiones independientes (18 oct)

**Seguridad y operación**: 2 bloqueantes (revocar en Strava mataría el token
del legado; eventos de webhook sin firmar tratados como órdenes) y 9
importantes (state y `redirect_uri` detrás de Render, renovación concurrente,
hilo y conexiones, `sync-all` y Worker, ventana de sueño de Render y §6.3/§7.4,
permisos, migraciones en el arranque de Render y cambio en el legado, cifrado
y fugas, `timeout` y 429), más menores (marca, dominio de desarrollo, borrado
de usuario). **Dominio y datos**: 3 bloqueantes (`METRIC_FIELDS` alimenta uso y
pendientes; los CHECK de progreso de `ImportRun`; vinculación y «separar»
indeterminadas) y 8 importantes (`gear_id` sin columna y vínculos que se
perdían, floats de Strava, tipos y rangos, restricciones de 0011, entradas de
la vinculación, borrado al desconectar, estadísticas de potencia,
`sport_type`), más menores (campos FIT confirmados, exportación, pruebas).
Todo incorporado en esta revisión 2. **Re-verificación**: todos los puntos
verificados; dos importantes nuevos (perfiles por deporte frente al
`sport_type` específico de Strava; falsa detección de borrado sin
`activity:read_all`) y menores (cuenta revocada y atleta único, variable del
`subscription_id`, hora del cron, textos FIT restantes, no aditividad
explícita), incorporados en esta misma revisión.
