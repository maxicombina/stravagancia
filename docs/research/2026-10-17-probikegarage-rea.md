# ProBikeGarage: cómo funciona (análisis con REA, 17 oct 2026)

Notas de una sesión lateral de Claude, para comparar con Garage. **No** es
documentación de Garage ni una propuesta: no se han tocado beads, código ni los
documentos `docs/garage-*`. No se copió código de ProBikeGarage: aquí sólo hay
comportamiento observado, nombres de campos de la API y textos de la interfaz.

## Método y límites

- Herramienta: [REA](https://github.com/morluto/rea) `rea-agents@6.5.0` por CLI
  (`npx`), sin registrar el MCP ni cambiar la configuración del agente.
- Navegador: el Chrome del usuario, con su sesión iniciada en
  app.probikegarage.com y la depuración remota activada temporalmente desde
  `chrome://inspect/#remote-debugging` (socket `ws://127.0.0.1:9222/...`).
- Comandos REA usados:
  - `list-browser-targets` con `--allowed-origins https://app.probikegarage.com`.
  - `analyze-web-bundle`: con dart2js no encuentra rutas ni endpoints; sus
    heurísticas están pensadas para JS normal.
  - `inspect-web-page --include-script-sources` y `export-web-scripts`: copia
    local de `main.dart.js` (5,3 MB) para extraer cadenas: rutas de la API,
    claves JSON y textos de la interfaz.
  - `inspect-web-page --include-json-body-shapes` durante 30 s mientras se
    navegaba: **formas** JSON (rutas, tipos y recuentos) de cada respuesta de
    `api.probikegarage.com`, sin valores.
- Interfaz: extensión Claude in Chrome (capturas y árbol de semántica de
  Flutter).
- **Sólo lectura.** Las peticiones observadas fueron sólo `GET`/`OPTIONS`. Se
  abrió un formulario («Nuevo intervalo de servicio») y se cerró sin guardar.
  No se pulsó «Posponer», «Sincronizar», borrar ni guardar.
- Las capturas crudas (`capture.json`, `shapes.json`, `strings.txt`) quedaron en
  el scratchpad temporal de la sesión, no en el repo, porque contienen datos
  personales y código de terceros.
- Lo que no se ve desde el cliente (cálculos del servidor, avisos push,
  cron de sincronización) se deduce de los nombres y textos; se indica cuando
  es una inferencia.

## Arquitectura

- **Flutter web** compilado con dart2js (`main.dart.js`), renderizado con
  CanvasKit (canvas, no DOM), PWA (`manifest.json`, `flutter_service_worker.js`).
  El mismo código sirve para la web, iOS y Android.
- **API REST JSON** en `https://api.probikegarage.com` (otro origen, con CORS:
  cada GET va precedido de un OPTIONS). Identificadores UUID.
- **Firebase**: Analytics (eventos `component_created`, `service_created`,
  `snooze_created`…), Cloud Messaging (push) y Crashlytics.
- **Strava**: OAuth en `probikegarage.com/strava/auth/{login,callback}`. La
  cuenta de ProBikeGarage se crea al conectar con Strava por primera vez.
- **Cobros**: Paddle en la web (`paddle_web`, precios mensual y anual) y
  compras integradas de App Store y Google Play.
- Interfaz traducida a unos 10 idiomas (es, en, pt, it, fr, de, tr, sl…).

## Modelo de datos (formas JSON observadas)

Todas las entidades llevan `id` y `user_id`.

- **Bike**: `name`, `default` (bici por defecto), `retired_at`,
  `strava_bike {id, name, nickname, brand_name, model_name, frame_type,
  description}`, `usage`, `status`, `components[]` (en `detailed-bikes`).
- **Component**: `type` (catálogo fijo, ver abajo), `name`, `notes`,
  `retired_at`, `initial_usage {distance, moving_time, elevation_gain, rides}`,
  `usage`, `status`, `service_intervals[]` y `current_installations[]`.
- **Installation** (los «Intercambios»): `component_id`, `target_type`
  (bici o componente), `target_id`, `bike_id`, `added_at`, `removed_at`,
  `ride_tags[]`, `included_ride_tags[]`, `excluded_ride_tags[]`,
  `target_component`, `bike`. Un componente puede ir montado **dentro de otro**
  (las «piezas»: p. ej. casete y disco dentro de la rueda trasera).
- **ServiceInterval**: `component_id`, `title`, `type`, `value`, `repeat`
  (bool), `notes`, `next` (número: lo que falta), `services[]` y `snooze`.
  Tipos en la interfaz: Distancia, Tiempo en movimiento, Tiempo transcurrido,
  Actividades y Desnivel positivo (este último sólo con Premium).
- **Service** (intervención): `title`/`name`, `serviced_at`, `notes`,
  `target_type`/`target_id`, `bikes_ids[]`, `components_ids[]`,
  `service_intervals_ids[]`, `target_components_ids[]`,
  `target_service_intervals_ids[]`, `attachments[]`, `stats` (uso acumulado al
  hacerla: `distance`, `moving_time`, `elapsed_time`, `elevation_gain`,
  `rides`) y `stats_diff` (diferencia con la intervención anterior).
- **Snooze** (posponer): `target_type`/`target_id`, `components_ids[]`,
  `service_intervals_ids[]`, `type`, `value`, `remaining`, `created_at`,
  `dismissed_at`. Rutas `/snoozes` y `/default-snooze-data` (valores por
  defecto). Puede afectar a una bici, a un componente o a un intervalo
  (`SnoozeBike`, `SnoozeComponent`, `SnoozeServiceInterval`).
- **Status** (calculado, en bici y componente): `requires_maintenance`,
  `does_require_maintenance(_count)`, `will_require_maintenance(_count)` (pronto),
  `next_maintenance_percent`, `is_snooze_target`, `snooze_id`, `setup_pending`,
  `children_count`.
- **Usage** (calculado): totales `distance`, `moving_time`, `elevation_gain`,
  `energy`, `rides`, más medias y máximos por actividad (`avg_*`/`max_*`:
  distancia, tiempo, desnivel, energía, potencia, potencia normalizada,
  velocidad, cadencia y temperatura).
- **Ride**: `title`, `started_at`, `distance`, `moving_time`,
  `elevation_gain`, `max_speed`, `avg_power`, `max_power`, `normalized_power`,
  `avg_cadence`, `avg_temperature`, `work_output`, `tags[]`, `bike_id`,
  `components_ids[]` y `strava_activity` (copia de la actividad de Strava:
  `gear_id`, `sport_type`, `trainer`, `commute`, `map.summary_polyline`,
  `start_latlng`, `kilojoules`, `weighted_average_watts`…).
- **Attachment**: sobre una bici, un componente o una intervención; se puede
  usar como foto de portada (`/attachments/target-picture`).
- **Sugerencias de compra**: `/components/{id}/shopping-suggestions` busca
  ofertas de afiliados (Amazon) para el `type`/marca/modelo/velocidades del
  componente, con definiciones de catálogo y una puntuación de coincidencia.
- **Catálogos y alta guiada**: `/bikes-catalog`, `/components-catalog`
  (definiciones con marca, modelo, serie e intervalos de servicio por
  defecto), `/setup-suggestions` y `/bikes/{id}/setup` para dar de alta todos
  los componentes de una bici nueva de una vez.
- **Sincronización**: `/strava/sync`, `/strava/sync-status` (`last_sync_status`,
  `last_sync_finished_at`, `last_ride_updated_at`).
- Otros: `/subscription`, `/user`, `/user/settings`, `/user-features`
  (`has_reports`), `/devices` (registro de dispositivos para push), `/report`.

Tipos de componente: battery, bearings, bottom-bracket, brake, brake-caliper,
brake-lever, brake-pads, brake-rotor, cable, cassette, chain, chainguide,
chainrings, cranks, fork, frame, front-derailleur, grips, handlebar, headset,
hub, inner-tube, insert, light, pedals, rear-derailleur, saddle, sealant,
shifter, shock, stem, tyre, wheel, entre otros.

### Endpoints vistos en uso (GET)

```
/detailed-bikes                         /detailed-bikes/{id}
/bikes/{id}/components?sort=next-service
/bikes/{id}/services
/components?sort=next-service&filter=available
/components/{id}                        /components/{id}/children?sort=next-service
/components/{id}/installations          /components/{id}/services
/components/{id}/shopping-suggestions
/attachments?target_type=bike|component&target_id={id}
/rides?page=N&bike_id=&component_id=    /rides/{id}   /rides/{id}/components
/strava/sync-status   /subscription   /user-features
```

Otras rutas que aparecen en el bundle: `/service-intervals`, `/services`,
`/installations`, `/snoozes`, `/default-snooze-data`, `/replace`, `/retire`,
`/dismiss`, `/components-v2`, `/service-components`, `/components-catalog`,
`/bikes-catalog`, `/setup`, `/setup-suggestions`, `/strava/sync`, `/devices`,
`/report`, `/pricing-preview`, `/subscription/manage`, `/user/premium`,
`/user/privacy`, `/user/settings`, `/visit`.

## Comportamiento en la interfaz

- **Inicio**: estado de Strava («Última actividad actualizada hace N horas»,
  «Sincronizar con Strava», «¿Auto-sincronización inteligente?»: sincroniza
  sola al menos una vez al día); lista de bicis con km/h/desnivel y aviso;
  componentes filtrables («Disponibles», tipo) y ordenados por «Próximo
  servicio»; actividades recientes con etiquetas (`#montaña #exterior …`).
- **Ficha de bici**: totales (distancia, tiempo en movimiento y desnivel; la
  flecha abre Estadísticas), botones **Añadir servicio** y **Posponer**,
  componentes con icono de aviso (vencido) o de despertador (pospuesto),
  Servicios, Archivos adjuntos y Actividades.
- **Ficha de componente**: tipo, nombre, bici; totales; Añadir servicio y
  Posponer; notas libres; tarjeta de **sugerencia de compra** (afiliado);
  **Intervalos de servicio** con un anillo de progreso:
  «Pasado 25 km de 300 km · El último servicio fue el … después de 358 km» o
  «Queda 448 km de 3.500 km»; **Piezas** (hijos); **Intercambios** (historial
  de montajes: «Desde …, Actualmente instalado»); Servicios; Archivos adjuntos y
  Actividades.
- **Lista de servicios**: cada intervención muestra las piezas afectadas, el uso
  acumulado al hacerla y la diferencia con la anterior, en km, h, m de
  desnivel y días.
- **Formulario de intervalo**: Nombre, Tipo (Distancia / Tiempo en movimiento /
  Tiempo transcurrido / Actividades / Desnivel positivo), Valor, **Repetir**
  (activado por defecto) y Notas. **Cada intervalo tiene un único tipo**: no
  hay «lo primero que llegue» dentro de un intervalo, así que hacen falta dos
  intervalos.
- **Registrar un servicio**: se marcan los componentes e intervalos que se
  reparan; «también se repararán todas las piezas, y sus intervalos de
  servicio, de los componentes seleccionados» (se propaga a los hijos).
- **Reemplazar componente**: fecha y hora del reemplazo (posterior a la
  instalación) y otro componente distinto; opción de retirar el antiguo.
- **Retirar** una bici o un componente: se puede retirar también lo que lleva
  montado o dejarlo disponible.
- **Validaciones de montaje**: no instalar en una bici o componente retirado,
  ni un componente retirado, ni solapar períodos en el mismo destino.
- **Etiquetas por tipo de actividad** en un montaje: «Incluir todas las
  actividades» o incluir/excluir etiquetas (p. ej. ruedas distintas para
  rodillo y exterior); también hay etiquetas personalizadas.
- **Uso inicial manual** para material ya usado sin actividades previas.
- **Estadísticas**: totales, energía, actividades, velocidad media y máxima,
  potencia media; tabla de medias y máximos por actividad. Casi todo queda
  difuminado sin Premium («Obtén todas las estadísticas con Premium»).
- **Notificaciones**: push de «componente requiere acción» y de actividad
  nueva (canales `probikegarage-component-action-required` y
  `probikegarage-rides`).
- **Premium**: estadísticas completas, intervalos por desnivel, informes
  («Obtener informe») y soporte prioritario.

## Comparación con Garage (este repo)

Fuentes: lectura del código de `garage/` (sin ejecutar nada), beads
(`bd list --all`, `bd show` de 006, 015, 017, 018, 027, 030 y 033, sólo
lectura) y la demo ficticia en `http://127.0.0.1:8766/garage/`. Se
comprobaron en el código, además del resumen del agente, que no hay desnivel en
modelos ni importador FIT, que no hay posponer y que cada intervención tiene un
único destino.

| Función de ProBikeGarage | Garage | Notas |
|---|---|---|
| Bicis, retirar, foto | Parcial | Varias bicis, retirar/reactivar, fotos. Retirar desmonta lo montado, no lo retira. Sin bici por defecto ni enlace a la bici de Strava. |
| Tipos de componente | Parcial | Categorías libres del usuario en vez de catálogo fijo; marca, modelo, nº de serie y precio. Sin cantidad («2 piezas»). |
| Uso inicial manual | Sí | «Material ya usado»: km, horas y salidas previas, con alcance y marca de «estimado» (`UsageBaseline`). |
| Piezas anidadas | Parcial | `Installation.parent_item`, detección de ciclos y el uso fluye hacia abajo. **Una intervención en el padre no repara a los hijos.** |
| Historial de montajes y reemplazo | Sí | Períodos con inicio y fin, sin solapes (restricción PostgreSQL), posiciones exclusivas, traspaso, reemplazo atómico que hereda la vida útil. Sin opción «retirar el reemplazado». |
| Filtro por tipo de actividad | Parcial, otro enfoque | En lugar de etiquetas en el montaje, perfiles de uso versionados por bici o deporte y excepciones por salida. |
| Intervalos de servicio | Parcial, mejor en parte | `MaintenanceRule` admite km, horas, salidas y días **a la vez, vence con el primero** (ProBikeGarage necesita un intervalo por tipo). Aviso al 90 % y «≥» con histórico incompleto. **Sin desnivel**; siempre se repite (no hay intervalo de una sola vez). |
| Registro de intervención | Parcial | Fecha y hora, notas, coste y moneda, fotos y lecturas opcionales. **Un destino y un tipo por registro**: no hay selección múltiple de componentes e intervalos, ni foto del uso con su diferencia respecto a la intervención anterior. |
| Posponer avisos | No | Ya figuraba como idea pendiente en `docs/garage-handoff.md`. |
| Estado y avisos en la app | Sí | Vencido, pronto, al día y desconocido; lista «Requiere atención» en Inicio, Taller y ficha de bici; «sin datos» equivale a `setup_pending`. |
| Salidas | Parcial | FIT o manuales; componentes usados por salida y pantalla de revisión. **Sin desnivel, potencia, cadencia, temperatura, velocidad, mapa ni etiquetas.** |
| Sincronización con Strava | No (aplazada) | garage-030, decidida pero aplazada hasta que el usuario la active. Hoy sólo se importan FIT a mano. |
| Adjuntos | Parcial | Sólo fotos (WebP, 2000 px, cuota) en bici, material o intervención. Sin otros archivos ni foto de portada. Bucket real pendiente (garage-010). |
| Estadísticas | Parcial | Período, bici, categoría y material; km, horas y salidas; gasto y coste por km; gráfico mensual. Sin medias ni máximos por salida, ni energía, potencia, cadencia, temperatura o velocidad. |
| Sugerencias de compra | No | Afiliados; no encaja con el uso personal. |
| Catálogo y alta guiada | No | Hay sugerencias de vida útil por tipo de pieza (garage-033), pero no catálogo de marca y modelo ni alta de todos los componentes de una bici de una vez. |
| Notificaciones push | No | Sólo dentro de la app; garage-027 (abierta, futura) decide el canal. |
| Idiomas y unidades | No | Sólo español y métrico; sí maneja la zona horaria de cada usuario. |
| Informe / exportación | Parcial | Exportación completa JSON y CSV (ZIP); sin informe formateado. |

### Lo que Garage tiene y ProBikeGarage no

- Importación de FIT originales de Garmin: vista previa, deduplicación,
  ejecuciones reanudables y cancelables, cobertura del histórico, retirada de
  fuentes y correcciones manuales que sobreviven a una reimportación.
- Equipación y material sin montar compartidos entre bicis (casco,
  zapatillas…) mediante perfiles de uso; revisión por salida de bici y
  material; asignación por lotes de salidas sin bici.
- Costes: precio de compra e importe de cada intervención con moneda, gasto y
  coste por km.
- Reglas con varios umbrales (lo primero que llegue, incluidos días) y
  **vida útil** de primera clase que hereda la pieza de repuesto.
- Honestidad con los datos: uso desconocido, parcial («≥») o completo, y
  lecturas marcadas como estimadas.
- Historial de montajes más rico: posiciones exclusivas (rueda delantera y
  trasera), traspasos, ciclos de anidamiento en el tiempo y períodos inactivos
  conservados al reactivar.
- Exportación completa de los datos, PWA instalable, sin suscripción.

### Huecos principales, de más a menos impacto (opinión, no propuesta)

1. **Sin ingesta automática de salidas.** Todo depende de subir FIT a mano.
   La sincronización con Strava (garage-030) es lo que más acerca Garage a
   ProBikeGarage, pero está aplazada por decisión del usuario.
2. **Sin desnivel en las salidas.** El FIT lo trae (ascenso total de la
   sesión), pero Garage no lo guarda. Impide reglas por desnivel (Premium en
   ProBikeGarage) y estadísticas por desnivel. Afecta al modelo y requiere
   migración aditiva.
3. **Intervención con un solo destino.** Registrar «servicio de horquilla» o
   «mantenimiento de transmisión» que cubra varias piezas e intervalos, y que
   se propague a las piezas anidadas, es una mejora de uso clara.
4. **Posponer avisos.** Modelo de ProBikeGarage: posponer una bici, un
   componente o un intervalo una cantidad de un tipo (km, días…), con lo que
   queda y una acción para dejar de posponer.
5. **Detalles menores**: foto del uso con su diferencia en cada intervención,
   intervalos de una sola vez (sin repetir), bici por defecto, cantidad de
   piezas, alta guiada de una bici nueva.

Fuera de alcance por las reglas del proyecto (`CLAUDE.md`): push,
sugerencias de compra con afiliados, suscripción e idiomas, salvo que el
usuario los pida.
