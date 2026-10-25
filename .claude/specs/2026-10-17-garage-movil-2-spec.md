# Especificación garage-032: resto de Garage en el móvil (estilo B)

Fecha: 17 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-032`.
Continúa garage-031 (`.claude/specs/2026-10-16-garage-movil-spec.md`), que
dejó fuera Taller, Estadísticas, la ficha de bici y los formularios largos.
Mismo marco, estilo B «Instrumentos», tokens y componentes de `garage.css`.
Rama `codex/garage-plan`; sin commits, staging, push ni despliegue.

## 1. Objetivo

Que todo lo que se toca a diario desde el teléfono tenga el mismo nivel que
Inicio, la ficha de componente y la revisión de salidas:

- Pestaña **Taller**: qué requiere atención, últimas intervenciones, reglas.
- **Registrar mantenimiento** y crear o editar reglas sin metros, segundos,
  microsegundos ni zonas IANA escritas a mano.
- **Ficha de bici** con el mismo patrón que la ficha de componente.
- Pestaña **Estadísticas** legible: período con un toque, cifras, gráfico,
  reparto por bici y material.
- **Listas** de bicis, material y categorías; **fechas locales** en español en
  las plantillas antiguas que siguen visibles.

Terminada cuando esas pantallas se usan con una mano a 390 px, en claro y
oscuro, en iPhone (Safari) y Android (Chrome), sin perder información ni
exactitud de las pantallas antiguas (lo técnico queda en «Detalles»).

## 2. Alcance y división

| Subtarea | Contenido | Depende de |
|---|---|---|
| 032a | Hora local en formularios; Taller; registrar mantenimiento; reglas en km y h; detalle de intervención (§4–§7) | — |
| 032b | Ficha de bici; filtro de salidas por bici (§8) | 032a |
| 032c | Estadísticas (§9) | 032a |
| 032d | Listas de inventario; fechas locales en plantillas antiguas (§10) | 032a |

Fuera de alcance (ideas de ProBikeGarage aún sin aprobar): posponer avisos,
plantillas con intervalos sugeridos, comparar duración de componentes,
desnivel. Tampoco: fotos con cámara, notificaciones, API, Strava.
**Sin cambios de modelo ni migraciones** (`garage.0001`–`0008` están en Neon).

## 3. Decisiones

| Tema | Decisión |
|---|---|
| Zona por defecto | `timezones.user_time_zone(request)` (cookie `garage_tz` validada; si no, `GARAGE_DEFAULT_TIME_ZONE` o Europe/Madrid). Sustituye al «UTC» inicial de los formularios sin enlazar. La zona sigue siendo un campo del formulario: plegado en «Zona horaria: Europe/Madrid · Cambiar»; se despliega si tiene error. |
| Selector de fecha | Widget `LocalDateTimeInput`: `type="datetime-local"` cuando el valor no tiene fracción de segundo (con `step="1"` si tiene segundos); si tiene microsegundos, campo de texto con el formato exacto actual. Nunca se pierde precisión al editar. |
| Unidades de reglas | Sólo en la web (`MaintenanceRuleWebForm`; el admin conserva metros y segundos): km con hasta 6 decimales y horas aceptadas sólo si × 3600 da un valor exacto al milisegundo; se guardan metros y segundos exactos. Un valor guardado que no se puede mostrar exacto en km/h se edita en su unidad exacta. Los errores del modelo sobre `distance_m`/`moving_time_s` se muestran en el campo visible (nunca 500). Nunca se redondea en silencio. |
| Decimales | Campos de texto con `inputmode="decimal"` que aceptan coma decimal («3,5», «2.700,5»): un `type="number"` puede vaciar en silencio un valor con coma. |
| Cambio de hora | Si un valor inicial convertido cae en la hora repetida (fin del horario de verano), ese formulario se queda en UTC para poder guardarse sin tocarlo. |
| Moneda | La intervención nueva propone la última moneda usada; si el importe queda vacío y la moneda no se tocó, se guarda sin moneda (la pareja importe/moneda del modelo exige ambos o ninguno). |
| Borrar | Los botones de eliminar salen de las listas y pasan a la pantalla de edición, en una zona separada y con texto explícito. URLs y métodos (POST) sin cambios. |
| Datos | Servicios existentes (`maintenance_due`, `statistics`, `monthly_usage`) y presentación (`presentation.wear`). Sólo ampliaciones aditivas. GET sin escrituras. |
| Mensajes | Los errores de hora en inglés de `forms.py` pasan a español (mismos códigos). |

## 4. Hora local en formularios (032a)

`garage/local_forms.py` (nuevo):

- `LocalDateTimeInput(forms.DateTimeInput)`: decide `type` y formato por valor
  como en §3; `supports_microseconds = True`.
- `localize(form, zone)`: si el formulario tiene `time_zone` y no está enlazado,
  pone `initial["time_zone"] = zone.key` y convierte a la hora de pared de esa
  zona cada valor inicial de un `LocalDateTimeField` que hoy se muestra en UTC
  (naive UTC o aware). Cambia el widget de esos campos a `LocalDateTimeInput`.
  Si ya hay otra zona inicial explícita distinta de UTC, no la toca.
- Se aplica en las vistas que pintan `form.html` con un campo de zona:
  mantenimiento, inventario (anclas), montajes, cierre/reemplazo/transferencia,
  retirada, lecturas. Perfiles (`usage_forms`) e histórico (`history_forms`)
  pasan en 032d; Estadísticas en 032c (formulario sin enlazar en la zona del
  usuario). `datetime-local` opcional: botón «Vaciar» (iOS no permite vaciarlo).

`form.html`: campos con `div.field`, ayuda y errores; la zona en un
`<details class="zone">` (abierto si tiene error); botones en `actionbar`
(Guardar / Cancelar) y, si la vista da `delete_url`, una sección «Eliminar»
con formulario POST y texto del objeto. Explicación como `p.lede`.

## 5. Taller (032a)

`services/workshop.py`: `workshop_snapshot(actor, *, at=None, all_events=False)`
en una transacción con el bloqueo del propietario (como `home_snapshot`):

- `wears`: `by_severity(wear(due))` de todas las reglas, sin retirados, cada uno
  con su lugar (misma función que Inicio: `home.mount_resolver` y `place_of`).
- Grupos: `attention` (vencido, revisar, próximo), `nodata`, `calm` (en curso,
  al día).
- `events`: últimas 20 intervenciones (`performed_at` desc) con tipo, objeto o
  bici; `events_total`.
- `rules` (con tipo, destino y umbrales) y `types`.

`maintenance.html`:

1. «Requiere atención» con las filas de Inicio (anillo, objeto, tipo · lugar,
   chip, cifra). Extraer la fila a `_wear_row.html` y usarla también en Inicio.
2. «Sin datos» (fila compacta por regla: qué falta) y «En curso y al día»
   (filas con anillo pequeño, plegables si son más de 6).
3. «Últimas intervenciones» (fecha local, tipo, objeto, importe) → detalle;
   «Ver todas (N)» con `?all=1`.
4. «Reglas»: tipo · destino, umbrales legibles («3.000 km · 100 h · 365 días»),
   enlace a editar. «Tipos de intervención»: nombres con enlace a editar.
5. «Detalles técnicos de los avisos» (`details.more`) con
   `maintenance_alerts.html` actual (cobertura, contexto, «90 %»).

Barra: iOS `+` arriba, Android FAB «Registrar» → `service-event-create`.
Presupuesto medido: ≤ 24 consultas y constante al añadir reglas, tipos e
intervenciones (`==` en la prueba).

## 6. Registrar mantenimiento y reglas (032a)

- `service-event-create` y `-edit`: `service_event_form.html` con selector de
  destino (objeto o bici; prefijado con `?item=` o `?bike=` propios, 404 ajeno),
  tipo, fecha y hora local (por defecto ahora, al minuto), importe y moneda
  (por defecto la última usada por el propietario), notas. Sin JavaScript
  obligatorio. Tras guardar, al detalle de la intervención como hoy.
- `maintenance-rule-create` y `-edit`: `form.html` con km y horas (§3), días,
  salidas y ancla opcional en hora local; ayuda «Avisa al 90 %».
- `service-type-*`: `form.html` con eliminar en la edición.
- `?bike=` también prefija reglas.

## 7. Detalle de intervención (032a)

`service_event.html`: cabecera (icono llave, tipo, destino con enlace, fecha
local), cifra de importe, notas, lecturas desde la intervención (valor con
unidad legible), fotos, barra «Editar» y «Añadir foto»; «Eliminar» sólo en
la edición.

## 8. Ficha de bici (032b)

`views.bike_dashboard(request, bike)`; plantilla `bike_detail.html`:

1. Cabecera: icono, nombre, marca/modelo, «desde …» o «Retirada el …».
2. «Requiere atención»: desgaste de reglas de la bici y de lo montado en ella
   ahora (directo o anidado), por gravedad, con `_wear_row.html`.
3. Cifras totales de la bici: km, h, salidas (salidas con esa bici).
4. «Km por mes» (`monthly_usage(bike=…)`, `line_chart`), como la ficha de
   componente.
5. «Montado ahora»: componentes con montaje abierto en la bici y anidados
   («sobre …»), icono, posición, desde cuándo, chip del peor desgaste si tiene.
6. «Últimas salidas» (5) con fecha local y km → revisión; «Ver todas» →
   `usage-ride-list?bike=<uuid>` (filtro nuevo, propio o 404).
7. «Intervenciones» de la bici; fotos; `details.more` con datos, retirar o
   reactivar, historial completo de montajes.
8. Barra: «Registrar mantenimiento» (`?bike=`) y «Editar».

«Últimas salidas» excluye las salidas sin inicio. `?bike=` en Salidas: propio o
404 (también UUID mal formado), se conserva en la paginación y se combina con
`pending=1`. Cifras: «Registrado en Garage» y «N sin distancia» si faltan
valores (`Sum` ignora nulos). Presupuesto: medir, fijar y exigir que no crezca.

## 9. Estadísticas (032c)

`statistics_page`:

- Chips de período (enlaces GET `?period=`): `12m` (por defecto) =
  [día 1 del mes de hace 11 meses, ahora); `year` = [1 ene, ahora); `last` =
  año natural anterior completo; `all` = todo. Límites en la zona del usuario,
  `[desde, hasta)`, calculados una vez y compartidos por cifras y gráfico. Si
  llega cualquier campo del formulario antiguo, gana ese formulario
  («Personalizado») y no hay gráfico.
- Cifras del período para todas las salidas con inicio: km, h, salidas
  (`StatisticsReport.overall`, ampliación aditiva).
- «Km por mes» de todas las salidas: `monthly_usage(all_rides=True, …)` y
  parámetro `through=(año, mes)` (≤ mes de `at`); un mes es «en curso» si
  contiene `at`. 12 meses (o los del año en curso / pasado); en `all`, rotulado
  «últimos 12 meses».
- «Por bici»: km, h y salidas del período con barra proporcional; «Sin bici»
  con enlace a salidas por revisar.
- «Material más usado»: 8 primeros por km observados (o «uso pendiente»).
- «Gasto en mantenimiento» del período por moneda: cada intervención con
  `performed_at` en [desde, hasta) sumada una sola vez (no `row.costs`, que
  mezcla compra y adquisición); «N sin importe» si faltan, como mínimo.
- Honestidad: «N sin distancia» y `pending_started_rides` visibles.
- «Informe detallado» (`details.more`): el formulario y las tarjetas actuales.

Presupuesto: medir, fijar y exigir que no crezca al añadir objetos y salidas.

## 10. Listas y fechas (032d)

- `list.html`: buscador, chips Activos / Retirados / Todos, filas con icono,
  nombre, categoría o marca, estado; paginación con «Página N de M».
- Fechas `Y-m-d H:i:s T` de plantillas visibles (montajes, lecturas, perfiles,
  histórico, trabajos de importación) a `{% local_datetime %}` (nueva etiqueta:
  «17 oct 2026, 10:30», segundos si no son 0, desfase en la hora repetida, en
  `<time datetime="ISO UTC">` para conservar el instante exacto). Las
  exportaciones siguen en UTC. Formularios de perfiles e histórico con `localize`.

## 11. Pruebas

Por subtarea, PostgreSQL de pruebas y `settings_test`:

- 032a: widget (tipos por precisión, microsegundos conservados), `localize`
  (zona por cookie, conversión de valores iniciales, enlazado intacto), reglas
  en km/h (exactitud, rechazo de exceso de decimales), Taller (grupos, orden,
  ajenos ocultos, «90 %», presupuesto, sin escrituras), prefijado de bici,
  moneda por defecto, eliminar desde edición, detalle.
- 032b: ficha de bici (atención anidada, cifras, montado ahora, salidas,
  filtro `?bike=` propio/ajeno, presupuesto constante).
- 032c: períodos (límites locales, cambio de hora, año pasado completo),
  `overall`, `monthly_usage(all_rides, through)`, gasto por moneda,
  formulario antiguo intacto, presupuesto.
- 032d: listas (búsqueda, estado, paginación), fechas locales.
- Ajustar a propósito: `tests_mobile_item.py` («la bici conserva la ficha
  genérica»), `tests_views.py` (microsegundos: cookie UTC explícita porque la
  zona por defecto pasa a ser la del usuario) y `tests_maintenance.py`
  («12.34 EUR» → «12,34» y «EUR»). El formulario base de reglas (admin) no cambia.

Además: suite completa, `check`, `makemigrations --check`, `node --check`,
capturas a 390 px claro/oscuro y revisión independiente.

## 12. Revisión independiente (17 oct)

Incorporado arriba: error 500 por errores del modelo en campos km/h, horas no
siempre exactas, hora repetida, cobertura de `localize`, pruebas afectadas,
períodos y gasto de Estadísticas, honestidad con nulos, presupuestos, moneda
sin importe, coma decimal, `?bike=` y salidas sin inicio, `local_datetime`,
borrar fuera del formulario y 409, barras SVG sin `style`, vaciar fechas en iOS.
Mensajes del modelo en inglés: traducidos en los formularios de mantenimiento.

Revisión de código (17 oct, dos rondas), corregido con pruebas: moneda propuesta
sin importe en el POST real (`show_hidden_initial`), «3.000» ambiguo (miles o
decimales) rechazado, mensajes del modelo y de Django en español sólo en los
formularios web (el admin conserva los suyos), umbrales mostrados exactos,
origen conservado tras errores, «Personalizado» con filtros sólo con informe
detallado y fechas en la zona del formulario, fechas que desbordan en UTC,
primer instante del año sin datos, avisos «sin tiempo», género en listas.

## 13. Riesgos

- `datetime-local` no admite microsegundos: por eso el widget cae a texto.
- Formularios enlazados con errores conservan lo enviado (sin conversión).
- Taller y Estadísticas cargan todo el propietario: medir presupuestos.
- Teléfono real sigue pendiente de HTTPS (garage-023).
