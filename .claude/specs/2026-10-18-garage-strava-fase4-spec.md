# Strava fase 4: operación diaria (garage-030, 18 oct 2026)

Especificación corta de la fase 4 de `.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`
(§3 «Mantenerse al día», «Disparo», «Límites de Strava», «Revocación externa»;
§5 «Worker de Cloudflare»; §7.4; §8 «Operación»), en **modo token** (§0: sólo
la cuenta del propietario, token de Stravagancia, sin OAuth; «desconectar con
revocación» es de garage-040 y no entra aquí). Decisiones concretas, archivos y
pruebas para que los agentes la implementen sin volver a la maestra.

## 1. Punto de partida (fases 1–3 cerradas)

- `garage/services/strava_sync.py`: `sync_now(actor)` («Sincronizar ahora»:
  `GET /athlete`, últimos 7 días en ≤ 2 páginas de 50, ≤ 10 avisos pendientes,
  tope de 14 llamadas, `_Deadline` de 25 s con timeouts recortados a 30 s,
  `complete=False` cuando se quedó sin tiempo), `process_pending_events`
  (confirma avisos del webhook: `delete` ⇒ `GET /activities/{id}` y 404 ⇒
  fuente borrada; `create/update` ⇒ se guarda lo que diga Strava),
  `purge_events()` (eventos de más de 30 días), `_record(account, status,
  error)` (`last_sync_at/last_sync_status/last_error_code`), y el gancho vacío
  `_after_window(owner, account, seen_ids, window_start)` reservado para esta
  fase. Códigos de parada: `rate_limited`, `unauthorized`, `network`.
- `StravaAccount` (0010) ya tiene `revoked_at`, `mode='env'`, sin tokens;
  `StravaEvent` con clave de deduplicación única y tope de 500 pendientes;
  `ActivitySource.external_id/gear_id/possible_duplicate/withdrawn_at`.
- `garage/strava_views.py`: `strava_page`, `strava_sync` (sesión, POST),
  `strava_import`, `gear_link`, `strava_remove` («Quitar lo sincronizado desde
  Strava», fase 1–2 decisión 6: borra fuentes Strava, salidas sólo-Strava sin
  correcciones de medida, `StravaGear`, la fila `StravaAccount` y sus eventos).
- `strava_app/settings.py`: `GARAGE_STRAVA_USER`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID`.
  **Falta `GARAGE_SYNC_TOKEN`.**
- `keepalive/cloudflare-worker.js` (sin commit, con `keepalive/README.md`):
  Worker de Cloudflare con un cron `*/12 * * * *` que hace GET a `/healthz/`
  entre las 09 y las 24 (Madrid); `scheduled(event, env, ctx)`; sin secretos en
  el código.
- Migraciones locales: 0009–0012. **Esta fase no añade ninguna migración.** Si
  un agente cree que una es imprescindible, no la crea: lo explica en su
  informe y sigue con lo demás.

## 2. Decisiones

| Tema | Decisión |
|---|---|
| Servicio | `sync_all(now=None)` en `strava_sync.py`: trabajo acotado por llamada y resultado `SyncAllResult(accounts, pending, status, error, purged, absences)`. Pasos: (1) `purge_events()`; (2) por cada `StravaAccount` activa (en modo token, como mucho la del propietario configurado; escrito como bucle para garage-040): si `revoked_at` no es nulo y han pasado ≥ 30 días ⇒ **purga** (misma operación que «Quitar lo sincronizado», reutilizar su servicio; la fila desaparece y `purged += 1`); si no, ejecuta el mismo trabajo que «Sincronizar ahora» (refactorizar `sync_now(actor)` en `_sync_owner(owner)` que usan ambos; sin duplicar código) incluida la ausencia (abajo). `pending` = avisos pendientes tras la ejecución, más 1 si la semana quedó incompleta (`complete=False`): el Worker vuelve a llamar. `status` ∈ `ok`, `partial`, `failed`, `idle` (sin cuenta ni propietario configurado). Un código de parada (`rate_limited`, `unauthorized`, `network`) ⇒ `status='failed'`, `error=<código>` y se **deja** `pending` como esté: nunca se reintenta en la misma llamada. |
| Endpoint | `POST /garage/strava/sync-all/` (`strava_views.sync_all`, nombre `strava-sync-all`): `@csrf_exempt`, `@require_POST`, sin sesión ni login; cabecera `X-Sync-Token` comparada con `hmac.compare_digest` contra `settings.GARAGE_SYNC_TOKEN`. Si el ajuste está vacío o tiene menos de 32 caracteres ⇒ **404** (como una URL inexistente). Cabecera ausente o distinta ⇒ **403** genérico sin cuerpo explicativo. Nunca se registra ni se muestra el token. Cuerpo de la petición ignorado. Respuesta `200 application/json`: `{"pending": n, "status": "...", "error": "", "accounts": k, "purged": p, "absences": a}` también cuando `status='failed'` (el Worker lee el JSON; el código HTTP sólo distingue autenticación). |
| Worker | En `keepalive/cloudflare-worker.js`, `scheduled(event, env, ctx)` despacha por `event.cron`: el keep-alive sigue igual con `*/12 * * * *`; nuevo cron `5 7,8 * * *` (UTC) y el código sólo actúa cuando la hora en `Europe/Madrid` (`Intl.DateTimeFormat`) es las **09** (así es 09:05 Madrid en verano e invierno sin disparar dos veces). Hace `POST` a `env.SYNC_URL` (variable del panel, p. ej. `https://<app>.onrender.com/garage/strava/sync-all/`) con `X-Sync-Token: env.SYNC_TOKEN` (**secreto** del Worker, nunca en el código ni en el README) y User-Agent `curl/8.7.1` como el keep-alive; repite hasta `pending == 0`, `error != ""`, una respuesta no 200 o **K = 6** llamadas, con 2 s entre llamadas; cada llamada con timeout de 45 s (`AbortSignal.timeout`). Sin SYNC_URL o SYNC_TOKEN en `env` no hace nada y lo escribe en `console.log` (sin valores). `node --check` debe pasar. `keepalive/README.md` documenta los dos triggers, la variable, el secreto y que el usuario los configura en el panel; nada se despliega. |
| Ausencia como pista | Se implementa `_after_window(owner, account, seen_ids, window_start, complete)`: sólo si la semana se leyó **completa y sin error**. Fuentes Strava activas del propietario (`withdrawn_at` nulo, `external_id` no nulo) cuyo `started_at` observado ≥ `window_start` y cuyo `external_id` ∉ `seen_ids` ⇒ se persiste una pista sintética `StravaEvent` (`object_type='activity'`, `aspect_type='delete'`, `object_id=external_id`, `athlete_id`, `subscription_id=0`, `event_time=int(window_start.timestamp())`, `updates={"origin": "absence"}`), deduplicada por la clave única existente y sujeta al tope de 500. La confirma el mismo camino que un `delete` del webhook: 404 ⇒ fuente borrada (y la salida, si queda sin fuentes ni correcciones de medida); deporte no ciclista ⇒ borrada; sigue ⇒ se conserva y se actualiza. En modo token se supone `activity:read_all` (`ENV_SCOPES`). Tope `ABSENCE_HINTS = 20` por llamada; las pistas cuentan en `pending`. Fuentes retiradas a mano (`withdrawn_at`) se ignoran. |
| Revocación externa | `unauthorized` persistente (401 tras una renovación) ⇒ `revoked_at = now` si era nulo (además de `last_sync_status='failed'`, `last_error_code='unauthorized'`). Un `_sync_owner` que termina sin `unauthorized` pone `revoked_at = NULL`. Mientras `revoked_at` no es nulo el webhook y los workers ya ignoran al atleta (filtros existentes). La **purga a 30 días** sólo la hace `sync_all` (no el botón manual, que simplemente lo intenta otra vez). Límite 30 días inclusive: `now - revoked_at >= 30 días`. |
| 429 | Como hoy: `rate_limited` para toda la ejecución, cursor guardado, nada de reintentos en la misma llamada. `sync_all` lo devuelve en `error`; el Worker para ese día. Más → Strava sigue diciendo «reintenta en 15 minutos». |
| Comandos | `manage.py garage_sync_token`: imprime una sola vez `secrets.token_urlsafe(48)` (≥ 32 caracteres); no escribe `.env` ni ningún archivo. `manage.py garage_strava_sync`: ejecuta `sync_all()` y escribe el JSON de la respuesta (uso local y desde la consola de Render; mismo trabajo acotado). Ambos con pruebas. |
| Ajustes | `GARAGE_SYNC_TOKEN = os.getenv('GARAGE_SYNC_TOKEN', '')` en `settings.py` con comentario (≥ 32 caracteres; sin él el endpoint responde 404). `settings_test` lo deja vacío; las pruebas usan `override_settings`. |
| Registro | Una línea `INFO` en el logger `garage` por ejecución de `sync_all` con contadores y códigos (nunca el token ni nombres). |
| Pantalla Más → Strava | Sin migración. Añadir: «Sincronización automática: configurada» / «no configurada (falta GARAGE_SYNC_TOKEN)» según el ajuste (sin mostrarlo); si `revoked_at` no es nulo: «Strava rechaza el token desde el <fecha>. Renueva STRAVA_REFRESH_TOKEN en Render. Si sigue así, lo sincronizado desde Strava se borrará automáticamente el <fecha + 30 días>.» Estilo B, sin JavaScript, textos en español. |
| Fuera de alcance | OAuth, «Desconectar» con revocación (garage-040); borrados de más de 7 días que no lleguen por webhook (límite documentado); el `refresh_access_token()` del legado sin timeout; el `delete` falsificado del legado. |

## 3. Archivos

Cambiados: `garage/services/strava_sync.py` (`_sync_owner`, `sync_all`,
`_after_window`, `SyncAllResult`, `ABSENCE_HINTS`, `REVOKED_PURGE_DAYS = 30`),
`garage/strava_views.py` (`sync_all`), `garage/urls.py`, `garage/templates/garage/strava.html`,
`strava_app/settings.py`, `keepalive/cloudflare-worker.js`, `keepalive/README.md`,
`docs/garage-domain.md` §16 (operación: ausencia, revocación, purga, disparo),
`docs/garage-data-sources.md` (Strava: ausencia y purga), `docs/garage-handoff.md`
(sección de la fase 4 y bloque «Despliegue (garage-023)»: variables
`GARAGE_STRAVA_USER`, `GARAGE_SYNC_TOKEN`, `STRAVA_WEBHOOK_SUBSCRIPTION_ID`,
triggers y secreto del Worker, `gunicorn --timeout 60`), `TESTING.md`.
Nuevos: `garage/management/commands/garage_sync_token.py`,
`garage/management/commands/garage_strava_sync.py`, `garage/tests_strava_operation.py`,
`keepalive/worker.test.mjs` (pruebas del Worker con `node --test`, `fetch` simulado).

## 4. Pruebas (además de las existentes, que deben seguir en verde)

- Endpoint: sin `GARAGE_SYNC_TOKEN` ⇒ 404; token de 31 caracteres ⇒ 404; con
  token: cabecera ausente ⇒ 403, distinta ⇒ 403 (sin texto que ayude), igual ⇒
  200 con el JSON; `GET` ⇒ 405; sin sesión; CSRF no exigido; nada se escribe
  cuando la autenticación falla; el token no aparece en logs ni en la
  respuesta.
- `sync_all`: sin propietario configurado ⇒ `idle` y `pending 0`; con cuenta:
  mismo resultado que «Sincronizar ahora» (misma semana, mismos avisos) más la
  ausencia; semana incompleta ⇒ `pending ≥ 1`; `rate_limited` ⇒ `failed`,
  `error`, pendientes intactos, ninguna llamada más; `purge_events` ejecutado.
- Ausencia: fuente conocida de la ventana no listada ⇒ pista sintética
  deduplicada; 404 ⇒ fuente borrada (salida borrada si sólo tenía Strava y no
  tiene correcciones de medida; conservada si las tiene o tiene FIT); sigue en
  Strava ⇒ conservada y actualizada; deporte no ciclista ⇒ borrada; fuente
  retirada a mano ⇒ ignorada; fuente anterior a la ventana ⇒ ignorada; semana
  incompleta o con error ⇒ sin pistas; error en el GET ⇒ pista pendiente;
  tope `ABSENCE_HINTS`; la pista cuenta en `pending`.
- Revocación: 401 persistente ⇒ `revoked_at` puesto (una vez; no se mueve en
  fallos siguientes); éxito posterior ⇒ `revoked_at` nulo; `sync_all` con
  `revoked_at` de 29 días ⇒ sin purga; de 30 y 31 ⇒ purga (fuentes, salidas
  sólo-Strava sin correcciones de medida, `StravaGear`, fila, eventos) y
  `purged == 1`; el botón manual no purga.
- Comandos: `garage_sync_token` imprime ≥ 32 caracteres y no crea archivos;
  `garage_strava_sync` imprime el JSON.
- Worker: `node --check keepalive/cloudflare-worker.js`; `node --test
  keepalive/worker.test.mjs` con `fetch` simulado: el cron de keep-alive no
  llama a sync; el cron de las 07:05/08:05 UTC sólo actúa a las 09 de Madrid
  (fijar la fecha con `Date` simulada en los dos horarios); bucle que para en
  `pending 0`, en `error`, en respuesta no 200 y en K = 6; sin `SYNC_URL` o
  `SYNC_TOKEN` no llama.
- Pantalla: textos de sincronización automática y de revocación; sin
  consultas nuevas (presupuestos).
- Suite completa, `check`, `makemigrations --check` («No changes detected»),
  `inspect` (0 filas), pruebas del legado.

## 5. Revisión de código (18 oct 2026)

Revisión independiente de la fase 4: sin bloqueantes, 2 hallazgos importantes y
7 menores. Todos corregidos con pruebas; ninguna migración nueva (siguen 12; la
siguiente es la 0013). Estas correcciones **sustituyen** dos frases de §2: «Un
`_sync_owner` que termina sin `unauthorized` pone `revoked_at = NULL`» y
«Límite 30 días inclusive: `now - revoked_at >= 30 días`».

| # | Gravedad | Hallazgo | Cambio |
|---|---|---|---|
| 1 | Importante | `sync_all` purgaba una cuenta revocada hace ≥ 30 días sin comprobar si Strava vuelve a aceptar el token (token renovado tras la última ejecución fallida, o Worker caído que vuelve tras el día 30): borraba todo lo de Strava sin llamar a Strava. | `sync_all` ejecuta primero `_sync_owner(owner, create=False)` en todas las cuentas; sólo purga (`_purge_revoked`, comprobado otra vez con el bloqueo) si esa ejecución termina con `SyncResult.rejected` (Strava rechazó el token mismo) y la purga ya toca. Token que vale ⇒ la marca se anula y no hay purga; `network`/`rate_limited` ⇒ sin purga ese día y error informado. |
| 2 | Importante | `_record(revocation=True)` anulaba `revoked_at` en cualquier final que no fuera `unauthorized`, también `network`, `rate_limited` e `invalid_response`: un día sin red reiniciaba el plazo de 30 días. | `_record(..., revoked=True/False/None)`: `True` (rechazo) ⇒ `Coalesce(revoked_at, now)`; `False` (final `ok`/`partial`) ⇒ nulo; `None` (cualquier otro fallo) ⇒ intacto. La anulación al responder `GET /athlete` se mantiene. Prueba antigua cambiada a «sólo un final correcto la anula». |
| 3 | Menor | Cualquier `unauthorized` marcaba la cuenta, también un 403 en el `GET` de un aviso o un 401 persistente en `/athlete/activities` después de que `GET /athlete` respondiera; el webhook dejaba de aceptar avisos. | `_sync_owner` lleva `accepted` (tras `GET /athlete`); `rejected = code == "unauthorized" and not accepted`. Un 401/403 posterior hace fallar la ejecución sin tocar `revoked_at`. |
| 4 | Menor | La pantalla mostraba `revoked_at + 30 días`, pero la purga caía casi siempre el día 31; además prometía «se borrará automáticamente» sin `GARAGE_SYNC_TOKEN`. | `DAILY_SYNC_ZONE = Europe/Madrid`, `purge_date(revoked_at)` = día local de la revocación + 30 y `purge_due(revoked_at, now)` = día local de `now` ≥ esa fecha: la ejecución de las 09:05 de la fecha mostrada purga (probado en primavera, otoño, tras medianoche y el día anterior, incluido uno con más de 30 días exactos). La pantalla usa `purge_date`; sin sincronización automática dice «…se borrará en la primera sincronización diaria a partir del <fecha>; sin sincronización automática, sólo si alguien ejecuta manage.py garage_strava_sync.». `REVOKED_PURGE` (timedelta) desaparece. |
| 5 | Menor | `keepalive/README.md` y la entrega decían «pegar este archivo → Deploy», con `TARGET` redactado: rompía el keep-alive. | README y bloque «Despliegue (garage-023)» del handoff: sustituir `TARGET` por la URL real de `/healthz/` (la de la copia del panel) antes de Deploy, con el motivo. Prueba de node sobre el README y de pytest sobre el bloque. |
| 6 | Menor | El `fetch` de la sincronización seguía redirecciones: un `SYNC_URL` sin barra final daba 301 → GET con `X-Sync-Token` y un «405» engañoso; una redirección reenviaba el secreto. | `redirect: "manual"`: un 3xx es una parada no 200 con su código. Pruebas 301/302/307/308 (una sola llamada) y `redirect` comprobado en cada POST. README: `SYNC_URL` con `https` y `/sync-all/` con la barra final. |
| 7 | Menor | La ausencia borra sólo con un 404, que prueba algo únicamente si el token tiene `activity:read_all` (supuesto por `ENV_SCOPES`, nunca comprobado). | Paso «Antes de activar la fase 4, comprobar `activity:read_all`» en el bloque «Despliegue»: una salida privada («Solo tú») de los últimos 7 días debe aparecer en Garage tras «Sincronizar ahora»; si no, no configurar el Worker. Comentario en `ENV_SCOPES`; domain §16 y data-sources lo citan. Prueba sobre el bloque del handoff. (Se descartó un ajuste que desactive la ausencia: más configuración para el usuario; queda como alternativa.) |
| 8 | Menor | `sync_all` llamaba a `_sync_owner` → `ensure_account`, que crea la cuenta desde `GET /athlete` si la fila falta: una «Quitar lo sincronizado» simultánea volvía a crear la cuenta y la semana. | `ensure_account(..., create=False)` lanza `AccountGone`; `_sync_owner(owner, create=False)` además comprueba la fila con el bloqueo del propietario antes de cada escritura (`_still_there`) y termina como `idle`; `sync_all` no cuenta esa cuenta. Pruebas: quitada antes de su sincronización, durante `GET /athlete` y durante la página. El botón (`create=True`) no cambia. |
| 9 | Menor | Con DEBUG=True, la página 500 técnica imprimía la variable local `given` (el token) del marco de la vista. | `@sensitive_variables` no basta: Django sólo filtra variables con DEBUG desactivado (`SafeExceptionReporterFilter.is_active`). La comparación pasa a `_sync_token_matches(request)`, un marco propio que ya ha vuelto cuando corre la sincronización (con `@sensitive_variables("given")` para los informes con DEBUG desactivado). Prueba: 500 con DEBUG sin el token. |

Pruebas (una ejecución cada vez, PostgreSQL desechable 55434):
`garage/tests_strava_operation.py` 64 (45 → se sustituyen 3 y se añaden 22),
`garage/tests_strava_views.py` +5 (34), `keepalive/worker.test.mjs` 39 (+5);
9 mutaciones detectadas y archivos restaurados con hash idéntico. Suite
completa **2552 pruebas + 45 subcasos** (176 s); `node --check` correcto,
`node --test` 39/39; `check` sin problemas; `makemigrations --check --dry-run`
«No changes detected»; `inspect` 0 filas.

Límites que quedan: la purga de una revocación detectada con el botón de
madrugada llega hasta unas 9 h después de 30 días exactos (la ejecución diaria
es a las 09:05) y ±1 h por el cambio de hora; una cuenta revocada cuyo día de
purga coincide con fallos de red o 429 se purga el primer día sin ellos.
Ninguna prueba contra Strava ni Cloudflare reales.

## 6. Re-verificación (18 oct 2026)

Verificador Opus independiente (sólo lectura más pruebas, una suite cada vez):
los 9 hallazgos de §5, **verificados** uno a uno (código, línea y prueba que lo
cubre): purga sólo tras comprobar el token en la misma ejecución; `revoked_at`
intacto en `network`/`rate_limited`/`invalid_response`; 401/403 tras aceptar el
token no marcan la cuenta; fecha de purga = día de Madrid mostrado; `TARGET`
antes de Deploy; `redirect: "manual"`; comprobación manual de
`activity:read_all`; cuenta quitada durante la ejecución ⇒ `idle`; token fuera
del marco de la vista. `node --check` correcto, `node --test` 39/39; suite
completa 2552 + 45; `check`, `makemigrations --check` e `inspect` limpios; sólo
12 migraciones.

Hallazgos nuevos:

- Menor (anterior a la fase 4): `garage/tests_elevation_screens.py` afirmaba
  `"kJ" not in html` sobre toda la página; el token CSRF puede contener «kJ»
  (1 fallo en 2552 en una ejecución, limpia la siguiente). Corregido: las dos
  aserciones comprueban `<span>kJ</span>`.
- Nimiedad, sin cambio: con `GARAGE_SYNC_TOKEN` configurado y la fecha de purga
  ya pasada sin ejecución (Worker caído, red o 429 ese día), el aviso sigue
  diciendo «se borrará automáticamente el <fecha pasada>». El handoff documenta
  que la purga llega en la primera ejecución posterior.

Suite completa final del orquestador: **2552 pruebas + 45 subcasos** (169,63 s);
tras los arreglos de herramientas del mismo día (tablero con subtareas de Beads,
`GARAGE_STRAVA_USER` en la demo), **2578 + 45** (179,19 s).
Informe: `docs/validation/garage-030-fase-4.json`. Demo 8766 reiniciada con el
código final. Nada probado contra Strava ni Cloudflare reales; nada desplegado.
