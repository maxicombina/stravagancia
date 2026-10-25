# Fuentes de salidas de Garage

Decisión de `garage-003`, revisada el **4 de octubre de 2026**. Solo documentación: no se han importado archivos, consultado cuentas personales, contactado proveedores ni cambiado el histórico existente. No es un dictamen jurídico.

## Revisión garage-029 — 12 de octubre de 2026

El usuario declaró que Garage es, en principio, sólo para su uso personal, y
**eligió sincronizar salidas y bicis desde Strava** (opción B: adaptador propio de
Garage que reutiliza el cliente, el token y el webhook existentes, con `gear_id`
para la bici). **Está aplazado** en `garage-030`: hasta que el usuario lo active,
sigue vigente lo de abajo (FIT propio y entrada manual) y no se implementa nada
de Strava en Garage.

Se descartaron leer la tabla `Activity` del legado (opción C) y la exportación
masiva de Strava como vía principal (opción D). El usuario acepta el riesgo de la
API Policy (§5.5, §6.2, §5.3/5.4 leídos literalmente), igual que la app existente,
que ya conserva sus Rides en Neon. El diseño debe permitir retirar la fuente Strava
(procedencia por campo, fuentes retiradas y reconstrucción de `ItemUsage`) si
Garage se comercializa. No es un dictamen jurídico. Al activar `garage-030`,
actualizar la matriz de abajo (filas de `gear_id` y actividades Strava).

**Activado el 18 oct 2026 (garage-030, fases 1–2, modo token)**: sólo la cuenta
del propietario (`GARAGE_STRAVA_USER`), con el mismo refresh token de
Stravagancia y sin guardar tokens; sólo ciclismo; sin OAuth (garage-040). Las
filas de `gear_id` y de actividades Strava de la matriz quedan actualizadas.
Contrato en `docs/garage-domain.md` §16. Lo de abajo (FIT y manual) sigue
vigente para esas fuentes; donde dice que Strava no se admite, prevalece esta
revisión.

## Desnivel y potencia — garage-030 fase 3 (18 oct 2026)

Migración local `0012_elevation_power` (aditiva salvo los dos CHECK de «al
menos un umbral/cantidad», sustituidos por versiones que admiten el desnivel).
Salidas y fuentes guardan cinco observaciones nuevas, `Decimal(20,3)` y nulas
(desconocido): `elevation_gain_m` (desnivel positivo, m; 0 es un valor
conocido), `average_power_w`, `max_power_w`, `weighted_power_w` (W) y
`energy_kj` (kJ). Precedencia sin cambios (manual > FIT > Strava, campo a campo):
FIT prevalece en lo que mide y Strava rellena lo que el FIT no trae. Sólo el
desnivel pasa al uso por objeto (`ItemUsage`, íntegro como la distancia); la
potencia queda en la salida. El criterio de «pendiente» y la cobertura del
histórico siguen siendo los cuatro campos originales: un desnivel o una
potencia desconocidos nunca hacen pendiente una salida.

- **FIT** (`PARSER_VERSION = fitdecode-0.11.0-m2`): campos nativos de sesión 20
  `avg_power`, 21 `max_power`, 22 `total_ascent`, 34 `normalized_power` (se
  guarda como `weighted_power_w`) y 48 `total_work` (J → kJ con tres decimales
  exactos). Centinelas inválidos ⇒ desconocido. Son observaciones opcionales:
  uno repetido en la sesión, que no sea un entero nativo (coma flotante, lista)
  o que no se pueda normalizar queda desconocido y el archivo se importa igual
  (revisión de código de la fase 3: antes se ignoraban y ese archivo entraba).
  Los campos originales (inicio, deporte, distancia y tiempos) siguen
  rechazando el archivo si se repiten o están mal formados.
- **Strava**: `total_elevation_gain` → `elevation_gain_m` siempre;
  `average_watts`, `max_watts`, `weighted_average_watts` (la ponderación propia
  de Strava, no la NP de Garmin) y `kilojoules` (ya en kJ) **sólo si
  `device_watts` es `true`**: la potencia estimada por Strava no es una medida y
  se guarda como desconocida, sin columna extra. Números con
  `parse_float=Decimal`; negativo o con más de tres decimales ⇒ desconocido.
- **Plausibilidad** (FIT y Strava, nunca un error): potencia media y ponderada
  ≤ 2.500 W, máxima ≤ 5.000 W, desnivel ≤ 20.000 m y energía ≤ 50.000 kJ; por
  encima, desconocido. Las correcciones manuales sólo exigen el formato exacto.
- **Fuentes anteriores a la fase 3.** Los FIT no se guardan, así que no hay
  relectura masiva: **volver a importar el mismo archivo** (mismo hash y sesión)
  refresca la fuente, sus observaciones y la versión del parser, recalcula la
  salida (las correcciones manuales se conservan) y reconstruye su uso. Las
  fuentes Strava de las fases 1–2 se rellenan en su **siguiente observación**
  («Sincronizar ahora» ve los últimos 7 días; el histórico de Strava, el
  período que se elija, o un aviso del webhook de esa actividad).
- Una corrección manual de desnivel o potencia cuenta como corrección de
  **medida**: conserva una salida que se queda sin fuentes Strava.

## Operación diaria — garage-030 fase 4 (18 oct 2026)

Sin migración. Contrato en `docs/garage-domain.md` §16 («Operación diaria»).

- **Disparo diario.** El Worker de Cloudflare llama a
  `POST /garage/strava/sync-all/` con `X-Sync-Token` (`GARAGE_SYNC_TOKEN` en
  Render, ≥ 32 caracteres; sin él la URL responde 404). Cada llamada hace el
  mismo trabajo acotado que «Sincronizar ahora» para la cuenta del propietario
  y responde cuántos avisos quedan (`pending`); el Worker repite hasta 0, un
  error o su tope de llamadas. Un 429 para la ejecución y no se reintenta hasta
  el día siguiente (o una pulsación manual). La sincronización diaria nunca
  crea la cuenta: tras «Quitar lo sincronizado» sólo vuelve con una
  sincronización o importación manual.
- **Ausencia en la semana como pista de borrado.** Con la semana leída entera y
  sin errores, y sólo con `activity:read_all`, una actividad Strava ya guardada
  de esos 7 días que la lista no trae se confirma con
  `GET /activities/{id}`: 404 ⇒ se borra la fuente (política §6.3); ya no es
  ciclismo ⇒ se borra; sigue ⇒ se conserva y se actualiza. Sin
  `activity:read_all` una salida hecha privada daría 404: se comprueba a mano
  antes de desplegar (docs/garage-handoff.md, «Despliegue»). Las retiradas a
  mano no se tocan. Borrados de más de 7 días: sólo por webhook (límite
  documentado).
- **Revocación y purga (§7.4).** Si Strava rechaza el token mismo (la
  renovación, o `GET /athlete` tras renovarlo), la cuenta queda marcada como
  revocada desde ese día (el webhook deja de aceptar sus avisos); la marca
  desaparece en cuanto Strava vuelve a aceptar el token. Un fallo de red o un
  429 no la ponen ni la quitan. Desde el día 30 tras la marca (fecha de Madrid,
  la que muestra Más → Strava), la sincronización diaria comprueba primero el
  token y, sólo si Strava lo sigue rechazando, borra lo sincronizado desde
  Strava exactamente como «Quitar lo sincronizado» (fuentes, salidas
  sólo-Strava sin correcciones de medida, bicis de Strava, la cuenta y sus
  avisos). Lo propio (FIT, entradas y correcciones manuales) se conserva.

## ProBikeGarage como origen de inventario — garage-043 (25 oct 2026)

Sin migración. Spec `.claude/specs/2026-10-25-garage-probikegarage-import-spec.md`
(§9: decisiones de la implementación); contrato de dominio en
`docs/garage-domain.md` §13 (enmienda garage-043).

**Qué es.** Un volcado JSON que el propio usuario obtiene de
`api.probikegarage.com` con su sesión y **sólo peticiones GET** (nada cambia en
ProBikeGarage): `format: "probikegarage-dump"`, `version: 2`, `exported_at` y las
listas `bikes`, `components` (con sus `service_intervals`), `installations`,
`services` y `rides`. Contiene datos personales (nombres, notas, precios
apuntados en las notas, historial): vive **fuera del repositorio** y nunca se
copia a fixtures, pruebas, documentos ni a la demo; las pruebas usan un volcado
sintético. Unidades: metros, segundos, metros de desnivel y número de salidas;
instantes ISO 8601 con zona. `0001-01-01T00:00:00Z` es el nulo de ProBikeGarage.

**Cómo se usa.** Un solo uso sobre un Garage sin bicis ni material (sin
`--force`; pueden existir ya categorías, tipos de intervención, salidas y bicis
de Strava, que se reutilizan):

1. `manage.py garage_import_probikegarage <volcado> --owner <id> --dry-run`:
   valida todo y muestra el informe (recuentos por tabla, categorías nuevas,
   avisos y errores con tabla, id y nombre) sin escribir nada.
2. El mismo comando sin `--dry-run` y con `--mapping <archivo nuevo fuera del
   repositorio>`: escribe en una transacción con el bloqueo del propietario,
   sólo a través de los servicios del dominio, y guarda el mapa id de
   ProBikeGarage → UUID de Garage (sólo identificadores, permisos 0600). Con
   errores no escribe nada y termina con código distinto de 0.
3. Más → Strava → «Importar histórico» desde una fecha anterior a la salida más
   antigua del volcado (garage-030, `activity:read_all`): la bici de cada salida
   sale de su `gear_id` a través del `StravaGear` que el importador ya vinculó.
   Si el histórico de Strava se importó antes, vincular la bici recalcula esas
   salidas.
4. `manage.py garage_probikegarage_verify <volcado> --owner <id> [--mapping …]`:
   compara, sin escribir, en el instante del volcado.

**Qué entra.**

| ProBikeGarage | Garage |
| --- | --- |
| `bikes` | `Bike` (nombre; marca y modelo de `strava_bike`) y su `StravaGear` (`strava_bike.id`) vinculado; retirada real ⇒ `retire_inventory` al final |
| `components` | `Item` con la categoría de su tipo (tabla fija `TYPE_CATEGORIES`: nombres del juego inicial de garage-041 cuando existe, y Frenos, Rodamientos, Roldanas, Insertos tubeless, Guía de cadena, Cuadro y Otros); `other` por palabra del nombre (cala, roldana, nube o insert), si no «Otros»; un tipo desconocido va a «Otros» con aviso. Notas tal cual; nombres duplicados se conservan; sin marca, modelo, precio ni compra |
| `installations` | `Installation` sin posición (`slot` nulo): primero en bici, después los anidados por profundidad. `added_at` nulo («desde siempre») ⇒ lo más antiguo entre los demás montajes de su bici y su primera salida, con nota. Retirados después de sus montajes, en orden de fecha |
| `service_intervals` con `repeat=true` | `MaintenanceRule` del tipo con el título del intervalo; `distance`, `moving-time`, `elapsed-time` (días enteros), `rides`, `elevation-gain`; ancla en el primer montaje (nula si nunca se montó) |
| `service_intervals` con `repeat=false` («Max life») | La vida útil de la pieza («Sustitución», garage-033); varios se combinan en una sola, lo primero que llegue |
| `services` | Un `ServiceEvent` por cada intervalo listado de cada componente (con su tipo); si a un componente no le corresponde ninguno, uno con el título como tipo. Título distinto del tipo ⇒ «Título. » delante de las notas. Sin importe |
| `initial_usage` | `UsageBaseline` de vida **estimada**, fuente «ProBikeGarage (uso inicial)», corte en el primer montaje (o en el instante del volcado si nunca se montó). Una vida útil de Garage no suma esa lectura (cuenta las salidas desde su referencia): el informe lo avisa por pieza |

**Qué no entra y por qué.**

- **Salidas.** Se descargan de Strava (garage-030): copiarlas del volcado como
  fuente «strava» falsearía la procedencia. El volcado sólo sirve para resolver
  «desde siempre» y para verificar.
- **Desnivel del uso inicial.** `UsageBaseline` no admite desnivel y no hay
  migración (sería la 0013, en otra tarea): se avisa.
- `next`, `stats`/`stats_diff` (Garage los calcula; la verificación usa `next`),
  aplazamientos, etiquetas de salida, bici por defecto, fotos y adjuntos: se
  avisa cuando aparecen y no se importan.

**Procedencia.** Es inventario e historial que el propio usuario escribió en
otra aplicación: se trata como entrada manual suya (se corrige y borra como
cualquier inventario). Lo único que ProBikeGarage obtuvo de Strava es
`strava_bike` (id, nombre, marca y modelo de su bici): el id se guarda como
`gear_id` de `StravaGear`, como haría una sincronización, y la marca y el modelo
pasan a la bici como datos de inventario editables (decisión D12).

**Verificación.** Bicis (salidas con esa bici), componentes (km, horas y salidas
de toda la vida con `summarize_item_usage`, desnivel sumando `ItemUsage`),
reglas (lo que falta según `maintenance_due` frente a `next`, misma unidad;
`elapsed-time` en días) y qué salidas del volcado tienen fuente Strava en Garage
(faltan, con otra bici). Se compara en `exported_at`, no ahora: las salidas
posteriores al volcado y el calendario cambiarían el resultado. Tolerancias:
distancia ±0,5 % o ±100 m (en las reglas, sobre el uso que ProBikeGarage midió
desde la referencia, umbral − `next`), tiempo ±60 s, desnivel ±1 % (al menos
1 m), salidas exactas y días ±1. Los días de una pieza retirada se cuentan hasta
su retirada (ProBikeGarage los detiene ahí; el calendario de Garage no se
detiene). Una regla de una pieza que nunca se montó, sin referencia en Garage
(«Sin datos») y con todo el intervalo por delante en ProBikeGarage, no es una
diferencia. Sin mapa empareja por nombre y categoría, y separa duplicados por
retirada y primer montaje.

## Decisión aplicable a las siguientes entregas

Garage usará **archivos de actividades propios del usuario, preferentemente FIT originales de su Edge 840, y entrada manual** como fuente del histórico y de los contadores duraderos. El recorrido elegido es Edge/Garmin Connect → archivo aportado por el usuario → Garage; que la misma salida se envíe también a Strava no cambia esta procedencia.

**Descartar el adaptador Strava para el histórico y el motor de uso de Garage con las condiciones públicas comprobadas.** No construir `garage-013` ni `garage-021` para ese fin. No significa que toda aplicación con Strava esté prohibida ni que sea imposible negociar otros términos; una integración transitoria con otro fin necesita una decisión nueva. No ofrecerla como base del futuro servicio comercial.

Se puede implementar el inventario, las lecturas previas manuales y el motor con datos sintéticos. Se puede desarrollar `garage-012` con fixtures sintéticos; la importación real requiere después una muestra autorizada y validada. `garage-014` se orienta a archivos y correcciones manuales, sin completar huecos desde la API. `garage-020` exporta de las salidas únicamente campos con procedencia acreditada (manual o FIT activa); las lecturas previas, que escribe el propio usuario, se exportan con su valor y su etiqueta `source` tal cual. La fuente elegida no requiere nuevas suscripciones ni contratar una API; sigue sujeta a las cuotas de infraestructura y a la licencia del parser que se elija.

## Qué dicen las fuentes oficiales y qué interpretamos

### Strava

La [API Policy](https://www.strava.com/legal/api_policy) abierta muestra fecha efectiva **1/6/2026**. Confirma caché de siete días (§6.2), límites de almacenamiento persistente (§5.5), análisis y derivados (§5.4), retirada por borrado en 48 horas (§6.3) y eliminación por revocación/fin en hasta 30 días (§7.4). §5.8 restringe cobros ligados a Strava, pero exceptúa funcionalidad propia no duplicativa. §3.3 contempla requisitos de suscripción; no exime al suscriptor de estas restricciones. §6.6 preserva el derecho del usuario a exportar sus datos.

**Interpretación técnica:** el histórico consultable y los contadores de mantenimiento solicitados no encajan en esa caché; guardar solo totales no soluciona los límites sobre derivados. Por ello se descarta su uso aquí. El resumen previo del plan sobre junio y siete días queda confirmado, no corregido. El derecho de exportación no demuestra por sí solo permiso para reutilizar comercialmente una exportación Strava: esa vía queda pendiente y no se usa.

El [API Agreement](https://www.strava.com/legal/api), también efectivo **1/6/2026**, define Strava Data por su obtención mediante API Materials (§2.3), y Data incluye además otros datos de la aplicación. Sus condiciones incorporan la política; el acuerdo prevalece si hay conflicto. El acceso puede revocarse y los casos dudosos pueden consultarse (§2.2). §3.2 dice que el acceso es actualmente sin cargo, reservando futuros cobros. No se ha comprobado la capacidad, registro o tier de la aplicación actual.

**Límite importante:** Policy §§2.5/6.4 usa el término amplio Data, mientras §7.4 concreta Strava y personales derivados. No prometer que desconectar Strava dentro de la misma Developer Application permite siempre conservar los demás datos. La app existente ya usa Strava: definir el ámbito contractual y el tratamiento de su integración e histórico antes de activar Garage en producción; una separación de modelos no prueba una excepción contractual. Esta entrega no desconecta, elimina ni migra datos.

Los [webhooks oficiales](https://developers.strava.com/docs/webhooks/) enumeran creación, borrado, revocación y cambios de título, tipo o privacidad; no garantizan aviso al cambiar la bici. Tampoco resolverían por sí solos una eventual reconciliación de equipamiento.

### Garmin

La [FAQ del programa oficial](https://developer.garmin.com/gc-developer-program/program-faq/) dice que no cobra licencia/mantenimiento por acceso al programa, **solo empresarial**, y que algunas métricas pueden exigir pago o pedido mínimo comercial. La [Activity API](https://developer.garmin.com/gc-developer-program/activity-api/) requiere aprobación para evaluación y consentimiento del usuario. **Interpretación:** no presupuestar una API personal pública gratuita ni habilitarla; no se ha solicitado acceso.

El [protocolo FIT](https://developer.garmin.com/fit/overview/) está diseñado para compartir datos de dispositivos y describe transferencia a plataformas de escritorio, móvil y nube. Esto apoya elegir archivos propios, pero no concede por sí solo una licencia comercial universal sobre cualquier contenido o SDK.

La [guía Activity FIT](https://developer.garmin.com/fit/articles/file-types/activity.html) describe fecha, deporte, distancia y resúmenes Session, con inicio, tiempo transcurrido y temporizador. Device Info puede identificar dispositivos/sensores; eventos de cambios electrónicos son cambios de marcha. **Interpretación:** ni un sensor ni una marcha identifican automáticamente la bici física de Garage. No encontramos garantía pública de exportación del historial de Gear de Connect dentro del FIT. No afirmar que esos datos nunca puedan aparecer: inspeccionar la muestra.

El [manual del Edge 840](https://www8.garmin.com/manuals/webhelp/GUID-16B12CFE-F96E-4DE9-9F5F-8C4A5936D3B9/EN-US/GUID-D59411F0-644D-4112-9955-44FCB5B1F2D5.html), versión 5 de agosto de 2026, confirma historial de distancia/tiempo y ausencia de registro cuando el temporizador está parado. La [guía de decodificación](https://developer.garmin.com/fit/articles/cookbook/decoding_activity_files.html) advierte sobre varias sesiones, archivos truncados y offset local opcional. **Decisión:** separar tiempo de temporizador de tiempo en movimiento; no llamar al primero `moving_time` sin validación. La equivalencia con Strava no está garantizada.

Las páginas oficiales [exportar datos](https://support.garmin.com/en-US/?faq=W1TvTPW8JZ6LfJSfK512Q8) y [Gear Tracking](https://support.garmin.com/en-US/?faq=9EtB5L0OA26gp56Yv9tyH9) se abrieron, pero el lector devolvió solo la estructura del sitio. Los resultados indexados del propio soporte muestran exportación original (habitualmente FIT), TCX y GPX, y Gear editable por actividad. **Límite de verificación:** no se leyó el artículo completo mediante apertura; no tomar esos extractos como prueba de todos los campos o condiciones. FIT y entrada manual siguen siendo la elección; TCX/GPX son alternativas a validar, no equivalentes garantizados.

## Matriz de procedencia y conservación propuesta

Esta tabla define comportamiento del producto; las celdas de archivos/manuales son decisiones de minimización y propiedad, no nuevas autorizaciones del proveedor. Uso comercial significa ofrecer Garage con información aportada legítimamente por cada cliente, sin revender sus datos; falta la revisión previa a lanzar `garage-026`.

| Campo o recurso | Procedencia admitida / ausencia | Conservación propuesta | Retirada y uso comercial |
| --- | --- | --- | --- |
| Propietario, UUID y clave de importación | Usuario autenticado; UUID propio; hash por usuario + sesión | Mientras exista la salida | Borrado de usuario/salida; admitido como diseño propio |
| Inicio UTC, deporte, distancia | FIT propio validado; manual explícito; TCX/GPX pendiente | Histórico normalizado mientras el usuario lo mantenga | Eliminar o recalcular al borrar; comercial condicionado a derechos del aportante |
| Desnivel, potencia y energía (garage-030 fase 3) | FIT de sesión, Strava (potencia sólo medida) o manual; plausibilidad ⇒ desconocido | Igual que salida; sólo el desnivel pasa a `ItemUsage` | Precedencia por clase como las demás métricas; reimportar el FIT o volver a observar en Strava rellena las fuentes antiguas |
| Segundos de temporizador, transcurridos, movimiento | Campos independientes y nullable; método y unidad documentados; estimaciones explícitas | Igual que salida | Desconocido no es cero; no copiar métrica Strava como estimación propia |
| Bici y material de cada salida | Elección manual, perfiles y montajes; vínculo del archivo solo si verificado | Histórico manual con fechas de vigencia | Recalcular por corrección; no asignar bici por defecto ni inferirla del Edge |
| Lectura previa de kilómetros/horas/salidas | Usuario introduce valor, instante de corte, origen declarado y si es estimación | Mientras se mantenga el objeto/histórico | Borrar/corregir lectura; origen «Garmin manual» solo cuando realmente procede de Garmin, no de API Strava |
| Archivo bruto propio | Carga explícita y validación en memoria/temporal; no subir a herramientas de terceros | Borrar temporal tras procesar; no archivar bruto inicialmente | Copia original permanece con usuario; ofrecer exportación normalizada propia |
| GPS, salud y seriales de sensores | No necesarios para Garage inicial | No persistir | No exportar ni usar comercialmente estos campos en esta fase |
| `gear_id` de Strava | Admitido (garage-030): observación de la fuente Strava; la bici de Garage se elige a mano en `StravaGear` | Mientras exista la fuente o el vínculo; «Quitar lo sincronizado» lo borra | Procedencia `strava` por campo; una corrección manual prevalece; retirar recalcula salidas y uso |
| Actividades Strava (API, token del propietario) | Admitidas (garage-030): sólo ciclismo; inicio, nombre, deporte, distancia, movimiento, transcurrido, desnivel y, sólo con potenciómetro (`device_watts`), potencia media, máxima, ponderada y kJ; nada de GPS, mapa ni salud | Fuente `strava` por actividad; borrado en Strava confirmado por API (aviso del webhook o ausencia en la semana) ⇒ se borra la fuente; 30 días de token rechazado ⇒ purga como «Quitar lo sincronizado» | Retirable entera («Quitar lo sincronizado»); FIT prevalece en lo que mide; sin reutilizar `Activity` del legado |
| Respuestas brutas y avisos del webhook | Sólo pistas (`StravaEvent`, sin títulos; también las sintéticas de ausencia, `origin: absence`) | Purga a los 30 días | Nunca exportados ni en el admin |
| Actividades Strava del legado (`Activity`) | Legado, sin reetiquetar como Garmin o manual | Sin modificación por esta tarea | Garage no las lee (opción C descartada); sólo se cerró el despacho del webhook por atleta |
| Fotos, inventario e intervenciones | Autoría/aporte legítimo del usuario | Según preferencias y política propia | Exportación y borrado propio; ámbito de la Developer Application pendiente si se mantiene Strava |
| Inventario e historial importados de ProBikeGarage (garage-043) | Volcado propio del usuario, sólo GET, fuera del repositorio; las salidas nunca desde él (vienen de Strava) | Como el inventario propio; el mapa de ids queda en un archivo del usuario fuera del repositorio | Se corrige o borra como cualquier inventario; marca y modelo de la bici vienen de su bici de Strava |

## Contrato de importación para implementar

Registrar fuente por campo, usuario, fecha de importación, versión de parser, hash de archivo y sesión. No guardar tokens ni datos personales del archivo en logs. La corrección manual es un nuevo valor con su procedencia; pulsar «confirmar» un dato de API no lo convierte en observación independiente.

Resolver duplicados dentro del usuario: hash/sesión para reimportación exacta; fecha/deporte/distancia como candidatos, nunca fusión automática ambigua. Un FIT nuevo no legitima campos heredados de Strava. Para un registro combinado, sustituir cada métrica mediante lectura independiente del archivo, mantener desconocidos y conservar auditoría mínima propia. Diseñar cualquier retirada futura por dependencia de campos y recalcular `ItemUsage`; no mantener derivados de una fuente retirada por cambiarles el nombre.

Garmin/manual prevalece para métricas duraderas, las correcciones manuales prevalecen sobre reimportaciones y la bici desconocida queda pendiente. Contar sesiones de ciclismo sin sumar a la vez Session y Lap; rechazar o previsualizar multisesión/corrupción. GPX no debe convertirse silenciosamente en una salida con duración/distancia equivalentes a FIT; cualquier cálculo posterior deberá tener algoritmo, versión y marca de estimación.

## Pendientes verificables antes de uso real

1. Muestra aportada voluntariamente: un FIT original de Edge 840, idealmente con pausa, y si se desean alternativas, TCX/GPX de la misma salida. Pedirla cuando se valide el importador, sin frenar inventario. Procesarla localmente, no guardarla como fixture personal ni publicarla. Confirmar origen previo a Strava, sesiones, UTC, unidades, tiempos y metadatos de bici reales.
2. Elegir y revisar licencia/versión del parser; pruebas sintéticas de reimportación, dos usuarios, pausas, métricas ausentes y archivo inválido. Esta decisión documental no ejecuta tests ni importa datos.
3. Antes de despliegue, resolver titular explícito de datos existentes, ámbito de la Developer Application, tratamiento de legado y relación con la sincronización Strava ya instalada. No autorizar por omisión su uso en Garage.
4. Antes de comercializar, revisar términos aplicables al procesamiento de archivos propios, derechos y consentimiento del usuario, privacidad/exportación/borrado y capacidad/costes. Las páginas técnicas Garmin no verifican todos esos requisitos. Cualquier API futura necesita decisión nueva; no contactar proveedores sin instrucción.

Todas las fuentes técnicas/legales completas citadas arriba se abrieron y se leyeron el 4/10/2026; las dos páginas de soporte tienen el límite de extracción declarado. No se declara permiso jurídico definitivo, acceso aprobado a APIs ni coste cero garantizado a escala comercial.

## Muestra FIT local validada — 4 de octubre de 2026

El usuario facilitó un original de su Garmin para comprobar compatibilidad. Se
leyó solo en memoria, sin copiarlo a fixtures, exportar datos sensibles ni escribir
en Neon. Garmin FIT SDK 21.217.0 y fitdecode 0.11.0 comprobaron CRC y decodificación:
una sesión de ciclismo, inicio UTC y campos de distancia, temporizador y tiempo
transcurrido válidos. No hay campo explícito de movimiento ni identificación
suficiente de la bici en la sesión. Existen segundos fraccionarios y pausas, por
lo que el importador debe documentar precisión y mantener temporizador separado
de movimiento. Esto valida la muestra, no implementa todavía garage-012.

Para garage-012 se propone evaluar `fitdecode==0.11.0`, con CRC y tratamiento de
errores configurados explícitamente en `RAISE` (sus valores por defecto avisan).
Las pruebas locales rechazaron truncamiento, byte corrupto y datos extra finales.
El SDK oficial permite que `check_integrity()` pase con un byte extra final:
no basta ese método sin validación adicional del tamaño/lectura completa.

fitdecode publica licencia MIT y requiere conservar sus avisos; su perfil FIT
21.171.0 es anterior al del SDK oficial usado en la comprobación, por lo que se
probarán campos desconocidos y errores con fixtures sintéticas. El SDK oficial
usa FIT Protocol License, con condiciones de uso y redistribución propias; no
se ha añadido como dependencia de la aplicación. La selección definitiva y
los avisos de licencia pertenecen a garage-012; la comercialización requiere
la revisión prevista en garage-026.

Fuentes primarias: [licencia de fitdecode](https://raw.githubusercontent.com/polyvertex/fitdecode/master/LICENSE.txt),
[historial de fitdecode](https://raw.githubusercontent.com/polyvertex/fitdecode/master/HISTORY.rst),
[licencia del SDK oficial](https://raw.githubusercontent.com/garmin/fit-python-sdk/main/LICENSE.txt).
