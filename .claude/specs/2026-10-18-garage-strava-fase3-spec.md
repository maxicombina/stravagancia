# Especificación garage-030 fase 3: desnivel y potencia

Fecha: 18 de octubre de 2026. Autor: Claude (Fable 5.1), orquestando agentes Opus 5.5.
Tareas Beads: `garage-030` (fase 3) y `garage-037` (desnivel; queda dentro de esta
fase). Spec maestra: `.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`
(§4, bloque «desnivel y potencia», y §7.3). Diseño previo del desnivel:
`.claude/specs/2026-10-18-garage-desnivel-spec.md` (esta spec lo sustituye).
Pedido del usuario: «lo de la falta de desnivel … la potencia me interesa».
Rama `codex/garage-plan`; sin commits. **Una migración, la 0012** (la 0011 la
usó garage-041). Nunca en Neon.

## 1. Punto de partida

- `garage/ride_values.py`: `METRIC_FIELDS = (distance_m, moving_time_s,
  timer_time_s, elapsed_time_s)`, la tupla que usan Ride, ActivitySource,
  ItemUsage, la precedencia por clase (`services/rides._recalculate`), la
  materialización (`services/usage.py`), la exportación y las pantallas.
- FIT: `garage/importers/fit.py` lee los campos nativos de sesión 2, 5, 7, 8, 9
  y 59 (`NATIVE_FIELDS`), con centinelas inválidos ⇒ nulo (`decimal_metric`) y
  `PARSER_VERSION = 'fitdecode-0.11.0'`. Volver a importar el mismo archivo
  (`rides.import_fit_session` con el mismo `file_hash`) refresca las
  observaciones y la versión del parser.
- Strava: `services/strava_sources.OBSERVED` traduce `distance`, `moving_time`
  y `elapsed_time`; al observar una actividad nueva crea la fuente y, si ya
  existe, refresca lo observado.
- Reglas y aplazamientos: `MaintenanceRule`/`MaintenanceSnooze` con
  `distance_m`, `moving_time_s`, `ride_count`, `calendar_days`; CHECK
  `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount`;
  `maintenance_due.METRICS`, `presentation.UNITS/NAMES`, `SNOOZE_AMOUNTS`,
  formularios `maintenance_forms`, `snooze_forms`, `lifespan_forms`.
- Estadísticas: `services/statistics.METRICS` y `monthly.METRICS` (distancia,
  tiempo en movimiento, salidas).

## 2. Decisiones

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Campos nuevos | a) sólo desnivel; b) desnivel y potencia | **b)**: el usuario quiere ambos. Ride y ActivitySource: `elevation_gain_m`, `average_power_w`, `max_power_w`, `weighted_power_w`, `energy_kj`, `Decimal(20,3)`, nulos, con `exact_usage_value` y CHECK de rango como los demás (desnivel puede ser 0). `ItemUsage`: sólo `elevation_gain_m`. |
| Tupla de métricas | a) ampliar `METRIC_FIELDS`; b) dividirla | **b)**: `USAGE_METRICS` = las cuatro de hoy + `elevation_gain_m` (lo que fluye al uso por objeto); `RIDE_METRICS` = `USAGE_METRICS` + las cuatro de potencia (sólo Ride y ActivitySource). `METRIC_FIELDS` se conserva como alias de `USAGE_METRICS` y cada uso se revisa: precedencia, correcciones manuales (`RIDE_METRICS`), `_snapshot`, exportación, `.only()`. El criterio de «pendiente» y la cobertura (`history_queryset`, `coverage`) **no cambian**. |
| FIT | — | Campos nativos de sesión 20 `avg_power` (W), 21 `max_power` (W), 22 `total_ascent` (m), 34 `normalized_power` (W) y 48 `total_work` (J → kJ, tres decimales). Centinelas inválidos ⇒ nulo. Plausibilidad: potencia media y normalizada ≤ 2.500 W, máxima ≤ 5.000 W, desnivel ≤ 20.000 m, energía ≤ 50.000 kJ; fuera de rango ⇒ nulo (nunca error). `PARSER_VERSION` pasa a `fitdecode-0.11.0-m2`. **Relleno de fuentes antiguas:** a) comando de relectura masiva (descartado: los archivos no se guardan); b) **volver a importar el archivo**, que ya refresca la fuente (elegida; documentar en `docs/garage-data-sources.md`). |
| Strava | a) guardar siempre la potencia; b) sólo cuando `device_watts` es verdadero; c) columna extra «estimada» | **b)**: la potencia estimada de Strava no es una medida; sin columna nueva. Campos: `total_elevation_gain` → `elevation_gain_m`, `average_watts`, `max_watts`, `weighted_average_watts`, `kilojoules` (ya en kJ). Misma plausibilidad que FIT. Al volver a observar una fuente existente (ventana de «Sincronizar ahora» o histórico) se refrescan también los campos nuevos: así se rellenan las fuentes de la fase 2. |
| Precedencia y correcciones | — | Sin cambios de clase (manual > fit > strava). Las correcciones manuales admiten `RIDE_METRICS`; la procedencia por campo (`field_provenance`) cubre los campos nuevos. |
| Materialización | — | `elevation_gain_m` fluye a `ItemUsage` igual que la distancia (cada objeto montado recibe el valor íntegro de la salida). La potencia no se materializa. |
| Reglas y aplazamientos | a) sólo reglas; b) reglas y aplazamientos | **b)**: umbral y cantidad `elevation_gain_m` (metros enteros, > 0, ≤ `MAX_USAGE_VALUE`). La migración **sustituye** `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` por versiones que lo incluyan (las filas actuales las cumplen) y añade los CHECK positivos. Entran en `maintenance_due.METRICS`, `SNOOZE_AMOUNTS`, `thresholds()`, `snooze_reached`, `presentation.UNITS` («m») y `NAMES` («Desnivel»), `clean/clean_fields`, los `.only()` y los formularios de regla, vida útil (unidad «m») y posponer. Mismas reglas: primero alcanzado gana, «pronto» al 90 %, referencia = último evento del mismo objetivo/tipo o `anchor_at`. Un aplazamiento sólo está activo si **todas** sus cantidades son conocidas y no alcanzadas: una fuente sin desnivel deja ese aplazamiento inactivo con el estado «revisar» que ya existe para cantidades desconocidas. |
| Pantallas | a) todo en todas partes; b) desnivel en listas, potencia sólo en la salida | **b)**: donde se enseñan distancia y tiempo (salidas, revisión, histórico, bici, objeto, intervención, inicio) se añade el desnivel como «↑ 1.234 m» cuando se conoce. La potencia (media, máxima, normalizada, kJ) sólo en el detalle/revisión de la salida, con «Ø», «máx» y «NP». Filtro nuevo `metric_m` en `garage_ui` (entero con separador de miles y «m»). Sin JavaScript nuevo. |
| Estadísticas | a) desnivel y potencia; b) sólo desnivel | **b)**: `statistics.METRICS` y `monthly.METRICS` suman `elevation_gain_m` (desnivel total por bici y por mes); la potencia media de un periodo no es aditiva y se deja para más adelante (documentado). |
| Exportación (v1, aditiva) | — | Columnas nuevas al final de `rides` y `sources` (los cinco campos), de `usage` (`elevation_gain_m`), de `maintenance_rules` y `snoozes` (`elevation_gain_m`); `units` nuevas (`elevation_gain_m: metres`, `*_power_w: watts`, `energy_kj: kilojoules`). `docs/garage-export.md` actualizado. |
| Menores aplazados de la re-verificación de fases 1–2 | — | Se corrigen en esta fase, con prueba cada uno, en `services/strava_sync.py` y plantillas: (1) los avisos que quedan esperando tras la última ronda de `process_pending_events` no vuelven a programarse (`_again`); (2) más de 50 avisos pendientes de un atleta dejan un resto sin procesar; (3) el tiempo máximo de una petición de «Sincronizar ahora» (hasta 14 llamadas de 25 s) debe acotarse con el `deadline` existente de forma que la respuesta no supere unos 30 s y el resto quede para la siguiente; (4) `usage_profile.html` y `usage_profiles.html` muestran la clave de deporte en crudo: usar el filtro `sport_label`. |

## 3. Migración `0012_elevation_power`

Aditiva salvo la sustitución de los dos CHECK de «al menos un umbral/cantidad».
Pruebas de migración sobre filas existentes: fuentes FIT y Strava, usos,
reglas y aplazamientos con los campos antiguos; reversible. **No aplicar en la
demo (55433) ni en Neon**: la demo la migra el orquestador al cerrar la fase.

## 4. Pruebas (además de las existentes, que deben seguir en verde)

Parser FIT (campos nuevos, centinelas, plausibilidad, versión); adaptador
Strava (`device_watts` falso ⇒ sin potencia; desnivel siempre; refresco de una
fuente existente); precedencia y correcciones manuales con `RIDE_METRICS`;
materialización del desnivel y su reconstrucción; reglas por desnivel (primero
alcanzado, 90 %, referencia); aplazamientos por desnivel (activo, alcanzado,
cantidad desconocida); formularios (unidad «m», enteros); estadísticas por
bici y por mes; exportación (columnas y `units`, CSV); pantallas (desnivel en
listas, potencia sólo en la salida, nada cuando es nulo); presupuestos de
consultas sin crecer; los cuatro menores de fases 1–2; migración. Suite
completa, `check`, `makemigrations --check`, `inspect` 0 filas, revisión
independiente y re-verificación.

## 5. Revisión de código (18 oct 2026)

Veredicto del revisor: aprobar tras corregir la entrada de desnivel. Se corrigen
los cinco hallazgos; ninguna migración nueva ni editada (la 0012 sigue igual).

1. **IMPORTANTE, `elevation_field` guardaba «20.000» como 20 m.** El
   `IntegerField` de Django quita un «.0*» final antes de `int()`. Nuevo
   `WholeNumberInput` (`maintenance_forms.py`): texto con teclado numérico (un
   `type="number"` podría reinterpretar el punto antes del servidor), quita
   espacios normales, duros y finos, lee los grupos de miles con punto
   (`DOT_GROUPS`, sin ambigüedad porque no hay decimales) y rechaza cualquier
   otro punto o coma con «Introduce metros enteros, sin decimales (1500 o
   1.500).». Lo usan el desnivel de regla, posponer y vida útil y, como el
   mismo defecto ya existía, salidas y días de la regla del teléfono
   (`Meta.field_classes`) y de posponer, y el tiempo de la vida útil. El admin
   no cambia. Pruebas: `tests_elevation_review.py` (miles en los tres
   formularios, decimales rechazados, enteros, widget, admin).
2. **MENOR, `CLAUDE.md` no recoge la 0012.** Correcto, pero esta revisión
   tiene prohibido editar `CLAUDE.md`. Se corrige la afirmación falsa de
   `docs/garage-handoff.md` («CLAUDE.md lo recoge») y se deja escrito allí lo
   que falta: añadir la 0012 a las migraciones sólo locales, poner la 0013 como
   siguiente y avisar al usuario de que la 0012 sustituye dos CHECK, lo que
   necesita su aprobación antes de desplegar (garage-023). Sin prueba: es
   documentación.
3. **MENOR, el límite de 30 s no era estricto.** `StravaClient._timeout()`
   reparte ahora lo que queda: conexión `min(5, left/2)` y lectura `min(20,
   left − conexión)`, así que juntos nunca lo superan (antes una llamada
   empezada a los 25 s podía llegar a ~35 s). Como requests no tiene timeout
   total (DNS, cuerpo a goteo, renovación del token sin timeout), los
   docstrings de `strava_client`/`strava_sync`, `docs/garage-domain.md` §16 y
   el handoff dicen «unos 30 s», con gunicorn (60 s) como techo duro. Pruebas:
   suma ≤ lo que queda para 9 valores, `(5, 20)` sin prisa, ajustes en
   `tests_elevation_screens.py`.
4. **MENOR, un campo FIT opcional mal formado rechazaba el archivo.**
   `importers/fit.py` separa `CORE_FIELDS` (estrictos, como antes) de
   `OPTIONAL_FIELDS` (20, 21, 22, 34, 48): repetidos, no enteros (coma
   flotante, lista) o no normalizables ⇒ desconocido (`optional_metric`). La
   prueba que esperaba `fit_duplicate_field` para la potencia se sustituye por
   dos: sesión con campos opcionales repetidos/flotantes/en lista (el resto
   intacto; un campo original repetido sigue rechazando) e importación de un FIT
   con `avg_power` en coma flotante. `docs/garage-data-sources.md` actualizado.
5. **MENOR, desnivel ausente sin aviso en reglas y estadísticas.** Se aplican
   las dos opciones del revisor. (a) `maintenance_due`: si ninguna salida del
   intervalo de una regla trae desnivel, su valor es desconocido
   (`MaintenanceMetric.unrecorded`, estado «Sin datos»), como en estadísticas;
   un intervalo vacío sigue siendo 0 y distancia/tiempo no cambian. El Taller
   da un motivo propio en «Sin datos». (b) Con desnivel parcial,
   `WearMetric.missing_text` («N sin desnivel») en la fila del aviso y en la
   ficha del objeto; nota con el recuento en objeto y Posponer
   (`_elevation_rule_note.html`); «↑ ≥» en las filas por bici y por material de
   Estadísticas y en las bicis de Inicio (recuento en el mismo agregado); el
   gráfico mensual de desnivel dice cuántas salidas no lo registran. Donde el
   desnivel es un mínimo se añade «Volver a importar los FIT o el histórico de
   Strava completa el desnivel de las salidas anteriores.»
   (`_elevation_hint.html`). Sin consultas nuevas. Pruebas:
   `TestRidesWithoutElevation` y ajuste de la regla de gravel en
   `tests_elevation_screens.py`. `docs/garage-domain.md` §14 y §15.

Mutaciones de cada arreglo: todas hacen fallar pruebas; archivos restaurados con
hash idéntico. Suite completa **2473 pruebas + 45 subcasos** (antes 2429),
`check` sin problemas, `makemigrations --check` «No changes detected»,
`inspect` 0 filas. Sigue pendiente: actualizar `CLAUDE.md`, migrar la demo,
re-verificación, la muestra FIT del usuario (spec maestra §7.3) y Strava real.

## 6. Re-verificación (18 oct 2026)

Verificador independiente (Opus): los cuatro arreglos de código de §5 están
comprobados contra el código y sus pruebas; el de `CLAUDE.md` quedó para el
orquestador. Suite 2473 + 45, `check`, `makemigrations --check` e `inspect`
limpios. Dos hallazgos nuevos, corregidos por el orquestador (Fable):

1. **MENOR, campo exacto con decimales.** `MaintenanceRuleWebForm` conserva el
   campo exacto cuando el desnivel guardado tiene decimales (sólo posible desde
   el admin), pero era el `DecimalField` plano del modelo y leía «2.000» como
   2 m. Ahora es `DecimalInput` (mismo campo que los km): «1.234,5» y «1234.5»
   valen, «2.000» se rechaza como ambiguo, «1,2345» da «Como máximo 3
   decimales.», y el valor se muestra «1.234,5» con teclado decimal. El admin
   no cambia. Prueba en `tests_elevation_review.py`.
2. **TRIVIAL, docstring.** `strava_client.py` decía «cada petición usa
   timeout=(5, 20)»; ahora «como mucho», coherente con el recorte por plazo.

`CLAUDE.md` («Retomar ahora») nombra la 0012 como sólo local, pone la 0013 como
siguiente y avisa de que la 0012 sustituye los CHECK
`garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` (aprobación
explícita del usuario antes de desplegar). Suite final **2474 + 45**. Demo
55433 migrada a 0012 y servidor 8766 reiniciado.

Sin probar por nadie: el parser con la muestra FIT personal del usuario (spec
maestra §7.3) y una sincronización contra Strava real.
