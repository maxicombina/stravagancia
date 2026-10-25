# garage-043 · Importar el estado de ProBikeGarage en Garage (25 oct 2026)

El usuario quiere **migrar sus datos de ProBikeGarage** (app.probikegarage.com) a
Garage y «replicar el estado»: bicis, material con fecha de instalación, km,
horas, desnivel, intervalos de servicio, intervenciones y salidas. Decisión
suya del 25 oct: «si hay que re-bajar de Strava, se re-baja». No usa la
exportación de Garage (020): es un **importador nuevo** de un volcado JSON de la
API de ProBikeGarage, de un solo uso sobre un Garage vacío, más una
**verificación** que compara Garage con el volcado.

Orquesta Claude Fable 5.1; implementa un agente Opus 5.5 (regla del usuario,
18 oct). **Sin migración**: la siguiente sigue reservada como 0013 y no se crea
aquí (ver §7, D10).

## 0. El volcado (hecho el 25 oct, fuera del repositorio)

Obtenido en el Chrome del usuario con su sesión, **sólo GET** a
`https://api.probikegarage.com` (nada se cambió en ProBikeGarage). Archivos en
`~/.cache/stravagancia/probikegarage/` (datos personales: **nunca** copiarlos al
repositorio, a fixtures, a documentos ni a la demo ficticia):

- `probikegarage-2026-10-25-compact.json` (373 KB): el formato que lee el
  importador (§1). 2 bicis, **50 componentes** (31 activos + 19 retirados;
  `/components?filter=all`), 62 montajes, 59 intervalos, 177 intervenciones,
  350 salidas (2012-02-18 → 2026-10-25).
- `probikegarage-2026-10-25-raw.json` (3,2 MB): respuestas crudas por ruta
  (`responses["/rides?page=1"]`…), con títulos de salidas, `components_ids` por
  salida, `stats_diff`, etc. Sólo para consultar.

Hechos del volcado que fijan decisiones (comprobados con un script local):

- Ninguna referencia rota; sin solapes de montajes del mismo componente; ningún
  retirado con montaje abierto; sin etiquetas de salida en montajes
  (`ride_tags` vacíos); sin aplazamientos (`snooze: null`); sin adjuntos; sin
  bici por defecto; sin potencia medida (`max_power` siempre nulo: la media es
  estimada por Strava y Garage la descarta).
- Centinela **`0001-01-01T00:00:00Z` = nulo** en `retired_at`, `added_at`,
  `removed_at` y en `subscription`.
- Un único montaje con `added_at` centinela: la horquilla de la primera bici
  («desde siempre»); su uso en PBG es el total de esa bici.
- Intervalos: `distance` (m) y `moving-time` (s) con `repeat` true/false,
  `elapsed-time` (s: 5 184 000 = 60 días, 31 536 000 = 365 días) siempre con
  repetición. Los 21 intervalos con `repeat=false` se titulan «Max life»/«Max
  Life» (20 de distancia, 1 de tiempo en movimiento) y no tienen intervenciones.
- Intervenciones: `target_type` `service_interval` (146) o `component` (31);
  174 con un componente y 3 con dos (unos pedales + sus calas: las calas van en
  `target_components_ids` y los intervalos listados son de los pedales); 10 sin
  intervalo («Medición», «Purgado TRASERO»…); `title == name` salvo que el
  volcado compacto omita `name`.
- `initial_usage` distinto de cero en 4 componentes (km y horas; uno retirado
  además con desnivel); `rides` siempre 0.
- Salidas: 343 con bici (210 de la primera, 133 de la segunda; cada bici tiene
  su `strava_bike.id`) y 7 sin bici (2012 y 2020, sin `gear_id`, 6 con
  distancia 0). `sport_type` `MountainBikeRide` (299) o `Ride` (51). Los totales
  por bici del volcado cuadran exactamente con la suma de sus salidas.

## 1. Formato de entrada (`format: "probikegarage-dump"`, `version: 2`)

JSON con estas claves (las que el importador usa; el resto se ignora):

```jsonc
{
  "format": "probikegarage-dump", "version": 2, "exported_at": "…Z",
  "bikes": [{"id": "uuid", "name": "…", "default": false, "retired_at": "0001-01-01T00:00:00Z",
             "strava_bike": {"id": "b123", "name": "…", "brand_name": "…", "model_name": "…", "frame_type": 3},
             "usage": {"distance": 0, "moving_time": 0, "elevation_gain": 0, "rides": 0}}],
  "components": [{"id": "uuid", "name": "…", "type": "chain", "notes": "…", "retired_at": "…Z|centinela",
                  "initial_usage": {"rides": 0, "distance": 0, "moving_time": 0, "elevation_gain": 0},
                  "usage": {"distance": 0, "moving_time": 0, "elevation_gain": 0, "rides": 0},
                  "service_intervals": [{"id": "uuid", "title": "…", "type": "distance|moving-time|elapsed-time|rides|elevation-gain",
                                         "value": 300000, "repeat": true, "next": -92444, "notes": "…", "snooze": null}],
                  "current_installations": ["installation uuid"]}],
  "installations": [{"id": "uuid", "component_id": "uuid", "target_type": "bike|component", "target_id": "uuid",
                     "bike_id": "uuid|''", "added_at": "…Z|centinela", "removed_at": "…Z|centinela",
                     "ride_tags": [], "included_ride_tags": [], "excluded_ride_tags": []}],
  "services": [{"id": "uuid", "title": "…", "name": "… (opcional)", "serviced_at": "…Z", "notes": "… (opcional)",
                "target_type": "service_interval|component|bike", "target_id": "uuid",
                "bikes_ids": [], "components_ids": ["uuid"], "service_intervals_ids": ["uuid"],
                "target_components_ids": ["uuid"] /* opcional */, "target_service_intervals_ids": [] /* opcional */,
                "stats": {"distance": 0, "moving_time": 0, "elapsed_time": 0, "elevation_gain": 0, "rides": 0}}],
  "rides": [{"strava_id": 123, "started_at": "…Z", "distance": 0, "moving_time": 0, "elapsed_time": 0,
             "elevation_gain": 0, "bike": "8 primeros caracteres del id de la bici o ''", "gear_id": "b123|''",
             "sport_type": "MountainBikeRide", "tags": "mountain,outdoor,ride", "components": ["8 chars", …]}]
}
```

Unidades: metros, segundos, metros de desnivel, número de salidas. Instantes
ISO 8601 UTC con `Z` (precisión de minuto; las salidas, de segundo). El
importador rechaza (`version` ≠ 2, `format` distinto, referencias rotas,
instante sin zona, montaje con fin ≤ inicio, solape de montajes del mismo
componente, intervalo con `value` ≤ 0 o tipo desconocido) **antes** de
escribir nada, con un informe legible por tabla y fila (`id` y nombre).

## 2. Mapeo a Garage (decisiones; ver §7 para las dudas)

Todo se escribe a través de los servicios existentes (nunca ORM directo salvo
lectura), en **una transacción** con el bloqueo del propietario, y termina con
`rebuild_usage(owner)`. El importador se niega a correr si el propietario ya
tiene alguna `Bike` o `Item` (un solo uso sobre un Garage vacío; sin `--force`).
Las categorías se reutilizan por nombre canónico (`services.categories._canonical`).

### 2.1 Bicis → `Bike` + `StravaGear`

`create_inventory(owner, Bike, name, brand=strava_bike.brand_name, model=strava_bike.model_name, notes="")`.
`retired_at` real → `retire_inventory` al final. Vínculo con Strava:
`ensure_gear(owner, gear_id=strava_bike.id, name=strava_bike.name)` +
`link_gear(owner, gear.pk, bike)` (dentro del mismo bloqueo; sin salidas aún no
recalcula nada) para que el histórico de Strava asigne cada salida a su bici.

### 2.2 Tipos → `Category` (nombre, icono)

Tabla fija en el código (`TYPE_CATEGORIES`): nombres del juego inicial de
garage-041 cuando existe equivalente (así «Crear las categorías habituales» no
duplica después) y nuevos cuando no:

| `type` de PBG | Categoría (icono) |
|---|---|
| chain | Cadena (chain) |
| cassette | Casete (cassette) |
| chainrings | Platos (chainring) |
| cranks | Bielas (crank) |
| bottom-bracket | Pedalier (bottom_bracket) |
| front-derailleur / rear-derailleur | Desviador delantero / Desviador trasero (derailleur) |
| shifter | Manetas de cambio (shifter) |
| cable | Cables y fundas (cable) |
| wheel / rim / spoke / hub | Rueda (wheel) / Llanta (rim) / Radios (spoke) / Buje (hub) |
| tyre | Cubierta (tire) |
| inner-tube | Cámara (tube) |
| sealant | Líquido sellante (sealant) |
| insert | Insertos tubeless (tire) |
| brake | **Frenos** (caliper) |
| brake-pads | Pastillas (brake) |
| brake-rotor | Discos (disc) |
| brake-caliper | Pinzas (caliper) |
| brake-lever | Manetas de freno (brake_lever) |
| fork | **Horquilla de suspensión** (suspension_fork) |
| shock | Amortiguador (shock) |
| headset | Dirección (headset) |
| stem / handlebar / grips | Potencia (stem) / Manillar (handlebar) / Puños o cinta (grips) |
| seat-post / saddle | Tija (seatpost) / Sillín (saddle) |
| pedals | Pedales (pedal) |
| bearings | **Rodamientos** (part) |
| frame | Cuadro (bike) |
| chainguide | Guía de cadena (part) |
| light / battery / computer | Luces (light) / Batería (battery) / Ciclocomputador (computer) |
| helmet / shoes | Casco (helmet) / Zapatillas (shoe) |
| other | por nombre: «cala» → Calas (cleat); «roldana» → **Roldanas** (derailleur); «nube» o «insert» → Insertos tubeless (tire); si no, **Otros** (part) |
| cualquier otro | Otros (part) + aviso en el informe |

Comparación del nombre: sin acentos, minúsculas, palabra completa o prefijo
(«roldanas» casa con «roldana»).

### 2.3 Componentes → `Item`

`create_inventory(owner, Item, name, category, notes=notes)`; sin marca, modelo,
precio ni fecha de compra (PBG no los tiene; los precios que el usuario apuntó
en `notes` se quedan en las notas). Nombres duplicados se conservan tal cual
(cuatro pedalieres del mismo modelo, dos juegos de rodamientos…): Garage los admite y
el historial los distingue. `retired_at` real → `retire_inventory(owner, Item,
pk, at=retired_at)` **después** de crear sus montajes (todos terminan ≤ esa
fecha en el volcado; si uno terminara después, error de validación en la
previsualización).

### 2.4 Montajes → `Installation`

`create_installation(owner, item, bike=…|None, parent_item=…|None, started_at=added_at, ended_at=removed_at|None, slot=None, notes=…)`.
Orden: primero los montajes en bici, luego los anidados por profundidad (el
padre siempre existe antes). `slot` siempre nulo (PBG no tiene posiciones).

`added_at` centinela («desde siempre»): `started_at` = el instante **más
antiguo** entre los demás montajes de esa bici y la primera salida de esa bici
en `rides`; nota del montaje «Montado desde el principio en ProBikeGarage
(fecha exacta desconocida)». Con el volcado real: la horquilla desde el
2024-03-13 08:49 UTC (el montaje más antiguo de esa bici, un freno). Si no hay nada, error en la
previsualización.

### 2.5 Intervalos → reglas y vida útil

`ServiceType` por título del intervalo (recortado; único por propietario sin
distinguir mayúsculas: «Max life» y «Max Life» son uno). Umbral según `type`:
`distance` → `distance_m`; `moving-time` → `moving_time_s`; `elapsed-time` →
`calendar_days = round(value / 86400)` (mínimo 1); `rides` → `ride_count`;
`elevation-gain` → `elevation_gain_m`. `notes` del intervalo → `notes` de la
regla.

- `repeat = true` → `save_maintenance(owner, MaintenanceRule, item=…, service_type=…, <umbral>, anchor_at=A, notes=…)`
  con **A = inicio del primer montaje** del componente (o el centinela resuelto;
  nulo si nunca se montó: Garage lo mostrará como «Sin datos» hasta la primera
  intervención, igual que PBG muestra el intervalo entero). La referencia real
  la dan las intervenciones importadas (§2.6): el ancla sólo cuenta si no hay
  ninguna.
- `repeat = false` → **vida útil**: `set_lifespan(owner, item, distance_m=…|moving_time_s=…|calendar_days=…|elevation_gain_m=…, start=A)`
  (tipo «Sustitución», garage-033). Varios no repetibles en un mismo componente
  se combinan en una sola vida útil (lo primero que llegue); dos del mismo
  umbral → se conserva el primero y se avisa. El título («Max life») no se
  guarda: ya es «Vida útil».
- Dos intervalos repetibles con el mismo título en un mismo componente violarían
  `garage_rule_item_type_unique`: error en la previsualización (el volcado real
  no lo tiene).
- `next` y `snooze` no se importan (`next` se usa en la verificación, §4).

### 2.6 Intervenciones → `ServiceEvent`

Por cada intervención y cada componente de `components_ids` ∪
`target_components_ids`:

1. Los intervalos listados (`service_intervals_ids` ∪
   `target_service_intervals_ids`) **que pertenezcan a ese componente**: un
   `ServiceEvent(item=componente, service_type=tipo del intervalo, performed_at=serviced_at, notes)`
   por intervalo. Así «Refresh kit» sobre los pedales con tres intervalos crea
   tres intervenciones en los pedales (reinicia las tres reglas), como hace PBG.
2. Si a ese componente no le corresponde ningún intervalo listado (las calas de
   las tres intervenciones conjuntas; las 10 sin intervalo): un `ServiceEvent`
   con `service_type` = título de la intervención (se crea el tipo si falta).
   Es historial: no reinicia reglas (ninguna de ese tipo) y la ficha lo lista.

`notes` del evento: las de PBG; si el título difiere del nombre del tipo
(«Servicio» registrado sobre «Check tightness»), se antepone «Título. » para no
perderlo. `stats`/`stats_diff` no se guardan (Garage lo calcula desde las
salidas; §4 los usa para comprobar). Sin importe ni moneda. Un `ServiceEvent`
sobre un intervalo de vida útil (ninguno en el volcado) sería una «Sustitución».

### 2.7 Uso inicial → `UsageBaseline`

Por cada componente con `initial_usage.distance` o `.moving_time` > 0:
`record_baseline(owner, item=…, metric=distance_m|moving_time_s, scope="lifetime", cut_at=C, value=…, source="ProBikeGarage (uso inicial)", is_estimated=True, notes="")`
con **C = inicio del primer montaje** (PBG suma el uso inicial antes de la
primera salida contada; Garage suma las salidas con inicio ≥ C, así que el
total coincide). `rides` = 0 y valores 0 no se registran. `elevation_gain`
inicial **no se puede guardar** (`UsageBaseline` no admite desnivel y no se
añade migración): se avisa en el informe (afecta a un único componente
retirado).

### 2.8 Salidas: no se importan del volcado

Las salidas vienen de **Strava** con garage-030 (modo token; cuenta del
propietario `GARAGE_STRAVA_USER`): Más → Strava → «Importar histórico» desde
el 2012-01-01 (la salida más antigua del volcado es del 2012-02-18), con
`activity:read_all`. `StravaGear` ya vinculado (§2.1) asigna cada salida a su
bici; las 7 salidas sin `gear_id` quedan sin bici (revisión), como en PBG. Las
salidas del volcado sólo sirven para verificar (§4). Importarlas como fuente
«strava» desde la copia de PBG se descarta: la procedencia sería falsa y
Garage ya sabe bajarlas.

### 2.9 Lo que no existe en el volcado y no se toca

Perfiles de uso, excepciones por salida, aplazamientos, fotos, lecturas de
ámbito `service`/`acquisition`, posiciones (`slot`), precios, marcas, modelos.

## 3. Entregables

1. `garage/importers/probikegarage.py`: lectura y validación del volcado,
   resolución de centinelas, mapeo puro (sin base de datos) a un **plan**
   (dataclasses: categorías a crear/reutilizar, bicis, items, montajes
   ordenados, reglas, vidas útiles, eventos, lecturas, avisos y errores).
2. `garage/services/probikegarage_import.py`: `preview(actor, dump)` → plan +
   informe; `apply(actor, dump, *, zone)` → escribe el plan con los servicios
   de §2 en una transacción, `rebuild_usage`, devuelve el resultado y el mapa
   `id de PBG → UUID de Garage` (bicis, items, reglas, eventos, lecturas).
3. Comando `python manage.py garage_import_probikegarage <volcado.json> --owner <id> [--dry-run] [--mapping <salida.json>]`:
   sin `--dry-run` aplica; siempre imprime el informe (recuentos por tabla,
   categorías nuevas, avisos, errores) en español; código de salida ≠ 0 si hay
   errores (y entonces no escribe nada). `--mapping` guarda el mapa en un
   archivo fuera del repositorio (el usuario elige la ruta). Nunca registra
   notas ni nombres en el logger.
4. Comando `python manage.py garage_probikegarage_verify <volcado.json> --owner <id> [--mapping <mapa.json>]`
   (§4), que no escribe nada.
5. Pruebas `garage/tests_probikegarage_import.py` con un volcado **sintético**
   construido en la propia prueba (una bici, componentes activos y retirados,
   anidados, centinela «desde siempre», uso inicial, intervalos de cada tipo con
   y sin repetición, intervenciones con varios intervalos, con dos componentes
   y sin intervalo, nombres duplicados, salidas de verificación). Cubrir: la
   validación rechaza referencias rotas, solapes, versión distinta y Garage no
   vacío; `--dry-run` no escribe (contar INSERT/UPDATE/DELETE con
   `CaptureQueriesContext`); la aplicación es atómica (un fallo tardío
   simulado deja cero filas); los totales de uso tras `create_manual_ride` +
   `rebuild_usage` coinciden con lo esperado; `maintenance_due` tras importar
   ve la referencia de las intervenciones; `retire_inventory` después de los
   montajes; la vida útil heredable queda creada; la verificación informa
   diferencias y «sin diferencias».
6. Documentación: sección nueva en `docs/garage-data-sources.md` («ProBikeGarage
   como origen de inventario, 25 oct 2026»: qué entra, qué no y por qué),
   párrafo en `docs/garage-domain.md` (enmienda §13: tipos de intervención
   creados por nombre al importar) y TESTING.md (comando y recuento).
   `docs/garage-handoff.md`, `CLAUDE.md` y el estado los actualiza el
   orquestador.

## 4. Verificación contra el volcado (`garage_probikegarage_verify`)

Compara, para el propietario, en el instante actual:

- **Bicis**: salidas, km, horas y desnivel de Garage (salidas con esa bici) vs
  `bikes[].usage`.
- **Componentes** (por `id` de PBG mediante el mapa, o por nombre + categoría
  si no hay mapa): km, horas y salidas de **vida** (`summarize_item_usage`,
  `scope=lifetime`, que ya suma la lectura inicial) y desnivel (suma de
  `ItemUsage.elevation_gain_m`) vs `components[].usage`.
- **Reglas**: lo que falta según `maintenance_due` vs `service_intervals[].next`
  (misma unidad; `elapsed-time` en días con tolerancia de 1 día).
- **Salidas**: cuántas del volcado tienen fuente Strava en Garage
  (`ActivitySource.external_id == strava_id`), cuántas faltan (lista de
  `strava_id` y fecha) y cuántas tienen bici distinta.

Salida: una tabla por bloque con valor PBG, valor Garage y diferencia; al
final, «Sin diferencias» o el recuento de filas con diferencia. Tolerancias:
distancia ±0,5 % o ±100 m, tiempo ±60 s, desnivel ±1 %, salidas exactas. Antes
de sincronizar Strava, todo saldrá a 0 en Garage: el comando lo dice
(«0 de N salidas del volcado están en Garage: importa el histórico de Strava»).

## 5. Revisión de código independiente (agente Opus distinto)

Leer esta especificación y el código. Buscar: escrituras fuera de los servicios
o del bloqueo; centinelas mal resueltos; orden de creación que viole la
exclusión de solapes o el ciclo temporal; eventos duplicados o en el componente
equivocado en las intervenciones conjuntas; pérdida de notas; `is_estimated`;
tipos duplicados por mayúsculas; `--dry-run` que escriba; informe que filtre
datos personales al logger; la verificación comparando unidades distintas;
pruebas que dependan del volcado real. Hallazgos con severidad y prueba que lo
demuestre; corregirlos (el implementador o el revisor, según se acuerde) con
prueba de regresión, y anotar aquí §5 «Resultado».

## 6. Re-verificación (agente Opus distinto)

Comprobar cada corrección de §5, ejecutar la suite completa (`check`,
`makemigrations --check`, `inspect`), guardar `docs/validation/garage-043.json`
y anotar §6 «Resultado».

## 7. Decisiones tomadas por el orquestador (el usuario puede cambiarlas)

- **D1** Tabla de categorías de §2.2 (nuevas: Frenos, Rodamientos, Roldanas,
  Insertos tubeless, Otros; horquillas como «Horquilla de suspensión»).
- **D2** «Max life» (`repeat=false`) → vida útil de Garage, no una regla.
- **D3** Uso inicial → lecturas de vida **estimadas** («≈»), fuente «ProBikeGarage
  (uso inicial)», corte en el primer montaje.
- **D4** `elapsed-time` → días enteros (60 y 365).
- **D5** Salidas desde Strava (re-descarga), nunca desde la copia de PBG.
- **D6** «Desde siempre» de la horquilla → desde el montaje más antiguo de su
  bici (2024-03-13), con nota.
- **D7** Título de intervención distinto del tipo → se antepone a las notas.
- **D8** Intervención sin intervalo → tipo con el nombre del título (historial).
- **D9** Un solo uso sobre un Garage vacío; sin `--force`; mapa de ids en un
  archivo fuera del repo.
- **D10** Desnivel del uso inicial: omitido (sin migración). Si el usuario lo
  quiere, sería la 0013 (`UsageBaseline.metric` + CHECK) en otra tarea.
- **D11** Nombres duplicados de componentes se conservan.
- **D12** Sin marca/modelo/precio en los items (no vienen); las bicis sí reciben
  marca y modelo de `strava_bike`.

## 8. Fuera de alcance

Importar fotos, etiquetas de salida, aplazamientos, catálogo de PBG, informes;
importar varias veces o fusionar con un Garage con datos; OAuth por usuario
(garage-040); despliegue (garage-023).

## 9. Implementación (Opus, 25 oct)

Archivos: `garage/importers/probikegarage.py` (lectura, validación y plan puro),
`garage/services/probikegarage_import.py` (`preview`, `apply`, `verify`,
`read_mapping`), `garage/management/commands/garage_import_probikegarage.py`,
`garage/management/commands/garage_probikegarage_verify.py`,
`garage/tests_probikegarage_import.py` (65 pruebas) y la documentación de §3.6.
Sin migración (0001–0012; la 0013 sigue reservada). D1–D12 aplicadas tal cual.

Decisiones tomadas fuera de la spec (todas en el sentido conservador):

1. **La verificación compara en `exported_at`, no «ahora».** Las salidas
   posteriores al volcado y el paso del tiempo (`elapsed-time`) darían
   diferencias falsas; `verify(..., at=None)` admite otro instante y el comando
   lo imprime. Tolerancia del desnivel: ±1 % con un mínimo de 1 m (ProBikeGarage
   da enteros; Strava, decimales). En las reglas, la de distancia se mide sobre
   el umbral del intervalo (`next` puede estar cerca de 0). Sin mapa, los
   componentes se emparejan por nombre y categoría y los duplicados se separan
   por retirada y primer montaje; si siguen ambiguos, la fila sale como
   diferencia. Sólo cuentan las fuentes Strava activas (no retiradas a mano).
2. **Intervención sin intervalo cuyo título es el tipo de una regla del mismo
   componente.** Se sigue D8 (tipo = título), así que en Garage esa
   intervención reinicia la regla de su mismo tipo (regla general de §13 del
   dominio): aviso en el informe, nombrando la pieza y la regla. En el único caso
   observable del volcado real (§10, R043-11; pieza retirada), ProBikeGarage
   reinició además un intervalo repetible de otro título, que Garage no reinicia:
   ahí Garage reinicia menos (1 diferencia prevista en la verificación; precisado
   en la re-verificación, §12). En el volcado real hay
   dos, ambas anteriores a la última intervención con intervalo de esa regla:
   el estado actual no cambia, sólo la referencia en fechas intermedias.
3. **Un intervalo repetible titulado «Max Life»** (el volcado real tiene uno,
   de tiempo en movimiento, y otro «Check Max Life») sigue siendo una regla
   normal: D2 sólo afecta a `repeat=false`.
4. **Vida útil.** `set_lifespan` no recibe notas: las de los intervalos no
   repetibles se unen (una por línea) y se guardan con un segundo
   `save_maintenance` de la regla. Una vida útil sólo por salidas (`rides`, no
   la hay en el volcado) se crea con `save_maintenance` sobre el tipo de
   `lifespan._life_type`, porque `set_lifespan` no escribe `ride_count`. El tipo
   «Sustitución» se crea siempre con `_life_type` (mismas notas que crea
   `set_lifespan`).
5. **Uso inicial.** Un componente que nunca se montó y tiene uso inicial recibe
   la lectura con corte en `exported_at` (en ese instante ProBikeGarage contaba
   exactamente ese uso), con aviso, en vez de perderla. Un `initial_usage.rides`
   > 0 también se guardaría (`ride_count`); en el volcado es siempre 0.
6. **Retiradas.** Se aplican al final, en orden de fecha (objetos y bicis
   juntos): así un montaje abierto se cierra en la primera retirada que le
   afecta y nunca termina después de otra posterior. Un montaje abierto de una
   pieza (o pieza contenedora o bici) retirada se admite y se cierra al
   retirarla, con aviso; empezar en o después de la retirada, o terminar
   después, es error (lo que `_close_for_retirement` rechazaría).
7. **Intervenciones.** `target_type: bike` sin componentes ⇒ evento en la bici
   con el título como tipo (no hay en el volcado). Sin componentes listados, se
   usan el componente o el dueño del intervalo de `target_id`. Un intervalo
   listado de un componente que no está en la intervención es **error** (no se
   pierde en silencio el reinicio de una regla; el volcado real no tiene).
8. **Anidados.** Un ciclo en el grafo de anidados (aunque no coincida en el
   tiempo) es error: más estricto que la regla temporal de Garage, y el volcado
   no tiene. «Desde siempre» dentro de otra pieza ⇒ lo más antiguo entre los
   montajes de la pieza contenedora y los de sus otras piezas. Un `added_at`
   ausente se trata como el nulo. Si la fecha resuelta queda en o después del
   fin del montaje, es error.
9. **Validación añadida.** Ids repetidos; valores que no son texto como
   referencias (se informan como referencia rota, nunca `TypeError`); el
   prefijo de bici de una salida debe identificar una sola bici; dos bicis con
   el mismo `strava_bike.id`; longitudes de Garage (nombres ≤ 150, tipos y
   categorías ≤ 100); fecha nula en `serviced_at` o en una salida; JSON con
   `Decimal` (nunca float) y sin `NaN`/`Infinity`; volcado ≤ 20 MB en UTF-8.
   `next`, `usage` y las métricas de salidas sólo los lee la verificación: si
   no son números se avisa y no se comparan.
10. **Garage previo.** Categorías existentes (también archivadas, con aviso) y
    tipos se reutilizan por nombre canónico sin cambiar su icono. Un
    `StravaGear` ya creado por una sincronización se reutiliza y se vincula; un
    nombre vacío del volcado nunca borra el suyo. El importador funciona
    también después del histórico de Strava (vincular recalcula las salidas;
    probado).
11. **Mapa.** `{"format": "probikegarage-mapping", "version": 1, …}` con bikes,
    strava_gear, components, installations, service_intervals (los «Max life»
    combinados apuntan a la misma regla), services (lista de eventos) y
    baselines; sólo identificadores. El comando lo rechaza dentro del
    repositorio, nunca sobrescribe (`O_EXCL`), lo crea con permisos 0600, lo
    escribe tras el commit (si falla, lo dice: la importación ya está hecha) y
    lo ignora con `--dry-run`.
12. **`--zone` (por defecto UTC)** en los dos comandos, sólo para mostrar
    fechas; `preview(..., zone=UTC)` lo admite y `apply(..., zone)` lo exige como
    pide §3. Los avisos del plan puro van siempre en UTC.
13. **Coste.** Lecturas constantes (`preview`: 5 consultas, probado ≤ 6 con 3 y
    40 componentes). Cada escritura es una llamada de servicio que toma el
    bloqueo y valida con `full_clean` (Django lanza una consulta por CHECK o
    UNIQUE): ~120 consultas por componente con su montaje, regla, intervención
    y lectura, constantes por fila (probado con 5, 15 y 25). Una importación
    sintética del tamaño del volcado real, medida por el revisor con
    `connection.execute_wrapper` (§10, R043-9): 6.145 consultas (0,8 s) en un
    Garage vacío y 18.065 (~3,5 s) con 300 salidas de Strava ya importadas (cada
    montaje y cada retirada reconstruyen todas las salidas). La cifra «~9.000»
    anterior era el tope `queries_limit` de `CaptureQueriesContext`, no una medida.
14. **Informe y logger.** El informe (stdout) nombra tablas, ids, nombres,
    categorías y tipos nuevos; nunca notas. El logger `garage`
    (`garage.services.probikegarage_import`) recibe una línea INFO con el id
    del propietario y recuentos.

Resultado del `--dry-run` con el volcado real (base local de pruebas, 0 filas
escritas): 0 errores; 17 categorías nuevas, 2 bicis vinculadas a Strava, 50
objetos (19 retirados), 62 montajes (23 anidados, 1 «desde siempre», resuelto
al 13/03/2024 08:49 UTC), 30 tipos, 38 reglas, 21 vidas útiles, 184
intervenciones, 8 lecturas iniciales; 4 avisos (el «desde siempre», las dos
intervenciones del punto 2 y el desnivel inicial de un componente retirado).

Pruebas: 65 nuevas; suite completa 2683 + 45 subcasos en verde (199,95 s);
`check`, `makemigrations --check --dry-run` e `inspect` limpios.

## 10. Revisión independiente (Opus, 25 oct)

Revisor distinto del implementador; no se ha corregido nada del código revisado
(hashes SHA-256 de los nueve archivos revisados idénticos antes y después). Se
añade `garage/tests_probikegarage_review.py` (sintético, reutiliza los helpers de
`tests_probikegarage_import.py`): **7 pruebas que fallan con el código actual**,
una por hallazgo R043-1…R043-7; el implementador las hace pasar (o el orquestador
decide otra cosa y la prueba cambia con esa decisión). Ejecutado en 55434:
`tests_probikegarage_import.py` 65 pasan; junto con la de revisión, 65 pasan y 7
fallan por el motivo previsto. Con el volcado real sólo `--dry-run` (0 errores, 4
avisos, recuentos idénticos a §9) y `garage_probikegarage_verify` (sólo lectura;
«0 de 350 salidas…», 461 filas con diferencias, código 0); el propietario 1 sigue
con 0 filas. Lo que se dice del volcado real tras importar sale de una
**simulación pura** (`build_plan` + la resolución de montajes de Garage repetida
en un script fuera del repositorio, salidas asignadas por `gear_id`): no se ha
aplicado la importación.

Sin blockers ni importants. Los hallazgos son de la verificación, de casos que
el volcado real no tiene, de una semántica de ProBikeGarage sin decidir
(R043-11) y de documentación.

### Hallazgos

**R043-1 · minor · `garage/services/probikegarage_import.py` `_rule_rows` (535–560).**
El calendario de una pieza retirada se compara en `exported_at`, pero
ProBikeGarage congela `elapsed-time` en la retirada y Garage nunca lo detiene
(§14 del dominio). Resultado: diferencias falsas. Demostración:
`test_r043_1_…` (pastillas retiradas el 01/02, revisión el 20/01 cada 30 días:
ProBikeGarage 18 días, la verificación compara −34,08). En la simulación del
volcado real, los **3** intervalos `elapsed-time` que difieren son de piezas
retiradas y los tres cuadran exactamente al evaluar en la fecha de retirada.
Corrección: para `DAYS` de un objeto retirado en R < `at`, comparar con
`umbral − (R − referencia)` (o `maintenance_due(owner, at=R)` por instante de
retirada distinto); nada cambia en el dominio.

**R043-2 · minor · `_rule_rows` (552–560).** Una regla de una pieza que nunca se
montó («Sin datos» en Garage) siempre cuenta como diferencia, aunque
ProBikeGarage diga `next == value` (nada usado), que es justo lo que §2.5 da por
equivalente. En el volcado real son **2** vidas útiles. Demostración:
`test_r043_2_…`. Corrección: sin referencia, sin montajes y `next == umbral` ⇒
fila correcta con nota («sin montar»). Al corregirlo, `test_differences_are_reported`
pasa de 3 a 2 líneas con «← diferencia» y de 4 a 3 filas.

**R043-3 · minor · `_rule_rows` línea 558 y `_within` (333).** En las reglas de
distancia la tolerancia es el 0,5 % del **umbral** (§9.1): para una vida útil de
3.000 km son ±15 km, y una salida entera de diferencia en el uso desde la
referencia pasa como correcta. Demostración: `test_r043_3_…` (ProBikeGarage 120
km usados, Garage 110 km ⇒ hoy «correcta»). Corrección: tolerancia sobre el uso
medido, `max(100 m, 0,5 % × (umbral − next))`, como en los totales de
componentes; con `next` cerca de 0 el uso es casi el umbral, así que no se vuelve
demasiado estricta.

**R043-4 · minor · `garage/importers/probikegarage.py` `plan_events` (882–888).**
Una intervención que lista dos intervalos no repetibles («Max life») de la misma
pieza crea **dos** «Sustitución» idénticas en el mismo instante (D2 los combina en
una sola vida útil). El volcado real no lo tiene (ninguna intervención marca un
«Max life»). Demostración: `test_r043_4_…`. Corrección: un evento por
(intervención, componente, tipo canónico); las notas no cambian.

**R043-5 · minor · `resolve_since_always` (705–735).** La fecha de un montaje
anidado «desde siempre» depende del orden de `installations`: si su pieza
contenedora también es «desde siempre» y aparece después, sus candidatos se
descartan (aún `None`) y es **error**; en el orden inverso, válido. Demostración:
`test_r043_5_…`. Corrección: resolver primero los montajes en bici y después los
anidados por profundidad (o iterar hasta punto fijo). El volcado real tiene un
solo «desde siempre», en bici: no le afecta.

**R043-6 · minor · `plan_baselines` (890) / `plan_rules` (792).** El uso inicial
va a lecturas `lifetime` (D3), pero una vida útil (y cualquier regla) de Garage
sólo suma salidas desde su referencia: nunca lecturas `lifetime` (§14). Una pieza
con uso inicial y «Max life» queda en Garage con más vida útil que en
ProBikeGarage, sin aviso. En el volcado real: 2 piezas, ambas **retiradas**, y
ProBikeGarage es incoherente (en una su `next` incluye el uso inicial y en la otra
no), así que la verificación mostrará 1 diferencia. Demostración:
`test_r043_6_…` (pide un aviso). Corrección mínima: avisar por pieza («la vida
útil no cuenta el uso inicial») y anotarlo en `docs/garage-data-sources.md`.
Alternativa a decidir por el orquestador: una «Sustitución» en el primer montaje
con lecturas `service` (= uso inicial), que `maintenance_due` sí suma; inventa una
intervención, por eso no se propone por defecto.

**R043-7 · nit · `plan_events` (857).** Con `target_type: service_interval`, si la
intervención lista su componente pero no el intervalo, el intervalo destino no se
reinicia: el evento toma el título como tipo (y el aviso dice «no marcaba ningún
intervalo»). El volcado real siempre lista el destino. Demostración:
`test_r043_7_…`. Corrección: añadir siempre `target_id` a los intervalos listados.

**R043-8 · nit · `_item_rows` (514–532).** La verificación hace 3
`summarize_item_usage` por componente (bloqueo y ~17 consultas cada vez):
medido con `connection.execute_wrapper`, **2.568 consultas** para 50 componentes
(273 con 5, 1.293 con 25), 0,5 s. Es lectura y se ejecuta pocas veces: aceptable;
si se quiere, un único agregado de `ItemUsage` por objeto y las lecturas en una
consulta.

**R043-9 · nit · §9.13 y TESTING.md (garage-043).** «~9.000 consultas» coincide
con `queries_limit` de Django (9.000): `CaptureQueriesContext` deja de contar ahí,
así que la cifra es un mínimo, no una medida. Medido con `execute_wrapper` (prueba
temporal, borrada): 50 componentes del volcado escalado, **6.145** consultas en
un Garage vacío (0,8 s) y **18.065** (3,5 s) si ya hay 300 salidas de Strava
(cada `create_installation` y cada retirada reconstruyen todas las salidas).
Corregir las dos cifras; el orden de §2.8 (importar y después bajar el
histórico) es además el barato.

**R043-10 · minor (orquestador) · esta spec, §0 y §2.3–2.4.** Contiene nombres de
las bicis, sus `gear_id` de Strava, marcas y modelos de componentes y nombres de
piezas del volcado real, contra la regla de §0 («nunca copiarlos al repositorio…
ni a documentos»). Está sin seguimiento Git; redactarla (tipos y recuentos)
antes de cualquier commit. El código, las pruebas y los demás documentos de la
entrega no contienen nombres, notas ni ids del volcado (comprobado con un script
que busca nombres, notas, ids y `strava_id` reales); sólo coincide una expresión
genérica de pieza usada como nombre sintético en las pruebas (inofensiva).

**R043-11 · minor (decisión del orquestador) · `plan_events` y §13 del dominio.**
Qué hace ProBikeGarage con una intervención de componente **sin intervalos**. En
el volcado real hay 6 intervalos cuya referencia cambiaría si esa intervención
reiniciara; comparando su `next` con la simulación (evaluada hasta la retirada):
los 4 no repetibles («Max life») no se reinician (natural), el único repetible
que discrimina **sí** se reinició (su `next` sólo cuadra contando desde esa
intervención; el `stats_diff` de esa intervención coincide exactamente con la
diferencia) y el otro repetible no discrimina (sin salidas entre medias). Es una
sola observación, pero no hay ninguna en contra: lo coherente con los datos es
«sin intervalos listados ⇒ reinicia todos los intervalos repetibles de la
pieza». Garage, con D8, sólo reinicia la regla de mismo título (si existe). En el
volcado real afecta a 1 regla de una pieza retirada (1 diferencia en la
verificación) y a ninguna pieza activa; sí cambia el histórico de vencimientos.
Sin prueba nueva: es una decisión de mapeo. Opciones: (a) dejarlo y corregir el
texto de §13 y del aviso («en ProBikeGarage no la reiniciaba» no está
demostrado); (b) tratar esa intervención como si listara todos los intervalos
repetibles de sus componentes (un evento por regla, título delante de las notas,
como garage-035), además o en lugar del evento con el título.

### Desviación 2 de §9 (intervención sin intervalo con el título de una regla)

Aceptable como mapeo (mejor que un tipo distinto), pero su justificación no
está demostrada (ver R043-11). (1) Es la regla general de §13: la referencia es
el último evento del mismo destino y tipo; un tipo distinto («X (sin intervalo)»)
partiría el catálogo en casi-duplicados que el usuario nunca escribió, no
reiniciaría nada y contradiría D8. (2) El usuario les dio el mismo nombre: en
Garage el mismo tipo es el mismo mantenimiento. (3) En el volcado real las 2
intervenciones avisadas tienen después 33 y 11 intervenciones del mismo tipo en
la misma pieza: el estado actual no cambia, sólo el histórico de vencimientos en
fechas intermedias. (4) Lo que el informe y §13 afirman de ProBikeGarage («no la
reiniciaba») no se puede observar en esas dos, y el único caso observable del
volcado apunta a lo contrario (R043-11): si se confirma, Garage reinicia menos
que ProBikeGarage, no más, y el aviso debería decirlo así. Mejora opcional (nit):
que el aviso diga si el evento cambia la referencia en `exported_at`.

### Comprobado y correcto

- Escrituras: sólo servicios del dominio (ninguna escritura ORM directa en los
  cuatro módulos), una `transaction.atomic()` con `_lock_owner` y el estado
  releído bajo el bloqueo; `ImportFailed`/`ImportRejected` y cualquier excepción
  revierten todo (las dos pruebas de atomicidad son reales). `--dry-run`: cero
  INSERT/UPDATE/DELETE (prueba del comando) y 5 lecturas constantes.
- Centinelas: `retired_at`, `added_at`, `removed_at` y fechas obligatorias; «desde
  siempre» en bici = mínimo de los demás montajes y de la primera salida (el
  volcado real cuadra: la resolución de montajes de Garage, simulada, da para cada
  una de las 350 salidas exactamente los componentes que lista ProBikeGarage, y
  los 50 totales de uso inicial + salidas cuadran con `components[].usage`).
- Orden de montajes (bici, luego anidados), solapes `[inicio, fin)`, ciclo
  estático, retiradas al final por fecha y comprobación previa de lo que
  `_close_for_retirement` rechazaría.
- Intervenciones conjuntas: un evento por (componente, intervalo propio) sin
  duplicados entre `*_ids` y `target_*`; calas con el título; notas y título
  conservados (D7). Umbrales, unidades, días `round(value/86400)` ≥ 1, anclas,
  `set_lifespan(start=…)`, vidas útiles combinadas, tipos sin mayúsculas y la
  colisión `garage_rule_item_type_unique` detectada antes de escribir.
- Lecturas iniciales: métrica, `scope=lifetime`, corte en el primer montaje,
  `is_estimated=True`, fuente; total = lectura + salidas desde el corte, sin doble
  conteo (prueba con salidas manuales).
- Categorías: tabla = §2.2, iconos válidos (`assert` contra `ICON_KEYS`),
  reutilización por nombre canónico sin tocar el icono, `other` por palabra,
  aviso con tipos desconocidos. `StravaGear` + `link_gear` en los dos órdenes.
- Verificación: mismas unidades (m, s, m, salidas; días convertidos), comparación
  en `exported_at` (más correcta que «ahora»), emparejamiento sin mapa (los 5
  grupos de nombres duplicados del volcado real se separan por retirada), sin
  escrituras. En el volcado real, tras importar y bajar Strava, la simulación
  prevé 8 filas de reglas/componentes con diferencia, todas explicadas: R043-1 ×3,
  R043-2 ×2, R043-6 ×1, R043-11 ×1 y el desnivel inicial de D10 ×1 (más lo que
  Strava devuelva distinto, que es justo lo que la verificación debe enseñar).
- Comando: español, código ≠ 0 con errores, mapa fuera del repo, `O_EXCL`, 0600,
  escrito tras el commit; logger con id y recuentos (prueba). Documentación
  (§13, data-sources) coherente con el código (salvo la frase de R043-11); TESTING.md: 65 pruebas recogidas,
  22 rechazos y 2618 + 65 = 2683 cuadran.

## 11. Correcciones tras la revisión (Opus, 25 oct)

Decisiones del orquestador aplicadas tal cual. Las 7 pruebas de
`garage/tests_probikegarage_review.py` se conservan (mismo archivo y nombres) y
pasan; `tests_probikegarage_import.py` + `tests_probikegarage_review.py`: 72
pasan.

- **R043-1** (`_rule_rows`): para una regla de días de un objeto retirado en
  R < `at` (con referencia ≤ R), Garage se compara como `umbral − (R − referencia)`
  (`maintenance_due._elapsed_days`), con la nota «días hasta su retirada»; el
  dominio no cambia. Prueba: `test_r043_1_…`.
- **R043-2** (`_rule_rows`): sin referencia en Garage, pieza nunca montada y
  `next` igual al umbral (días: ±1) ⇒ fila correcta con la nota «sin montar:
  nada usado, como en ProBikeGarage». `test_differences_are_reported` pasa a 2
  líneas «← diferencia» y «3 filas con diferencias.», y comprueba la nota de esa
  fila. Prueba: `test_r043_2_…`.
- **R043-3** (`_rule_rows`, `_within`): la tolerancia de distancia de las reglas
  es `max(100 m, 0,5 % × (umbral − next))`, sobre el uso que midió
  ProBikeGarage (sustituye a lo dicho en §9.1). Prueba: `test_r043_3_…`.
- **R043-4** (`plan_events`): un evento por (intervención, componente, tipo
  canónico); dos «Max life» de la misma pieza dan una sola «Sustitución», con
  las mismas notas. Prueba: `test_r043_4_…`.
- **R043-5** (`resolve_since_always`): la profundidad de anidado se calcula
  antes y se resuelven primero los montajes en bici y luego los anidados por
  profundidad, sea cual sea el orden del volcado. Prueba: `test_r043_5_…`.
- **R043-6** (`plan_baselines`): un aviso por pieza con uso inicial y vida útil
  («tiene uso inicial y vida útil: la vida útil de Garage no suma la lectura
  inicial estimada (cuenta las salidas desde su referencia)»); no se inventa
  ninguna «Sustitución». Anotado también en `docs/garage-data-sources.md`.
  Prueba: `test_r043_6_…`.
- **R043-7** (`plan_events`): con `target_type: service_interval`, `target_id` se
  añade siempre a los intervalos listados. Prueba: `test_r043_7_…`.
- **R043-8**: no se cambia (opcional). La verificación sigue usando
  `summarize_item_usage`, como pide §4: tres llamadas por componente, solo
  lectura. Sustituirlas por un agregado repetiría la lógica de lecturas y
  cortes de ese servicio. Queda anotado.
- **R043-9**: cifras corregidas en §9.13 y TESTING.md con la medida del revisor
  (6.145 consultas y 0,8 s en un Garage vacío; 18.065 y ~3,5 s con 300 salidas de
  Strava ya importadas). «~9.000» era el tope `queries_limit`. La prueba de
  presupuesto mide menos de 9.000 consultas, así que su recuento es exacto.
- **R043-11** (opción a): solo texto. El aviso ahora dice «no marcaba ningún
  intervalo en «pieza»: en Garage reinicia su regla «tipo» (mismo tipo, regla
  general de las intervenciones)». Se corrigieron §13 del dominio y §9.2 de esta
  spec: ya no afirman nada de lo que hacía ProBikeGarage, y dicen que el único
  caso observable del volcado real es coherente. La prueba del aviso se ajustó.
- Documentación: `docs/garage-data-sources.md` describe ahora:
  - la tolerancia de distancia de las reglas;
  - los días de las piezas retiradas;
  - las reglas de piezas nunca montadas.

  `docs/garage-domain.md` §13 añade que varios «Max life» marcados en una
  intervención dan una sola «Sustitución».

Comprobado: `check` sin problemas; `makemigrations --check --dry-run` «No
changes detected»; `inspect` 0 bases residuales. `--dry-run` del volcado real:
recuentos idénticos a §9 y 0 errores. Avisos: 6, que son los 4 de antes con el
texto de R043-11 más 2 de R043-6, ambos de piezas retiradas. El propietario 1
sigue con 0 filas. No se ha vuelto a pasar la suite completa: le toca a la
re-verificación.

## 12. Re-verificación (Opus, 25 oct)

Agente distinto del implementador y del revisor. Mutación: se quitó cada
corrección por separado, se ejecutó su `test_r043_n` y se restauró con
`/bin/cp -f`, borrando antes los `.pyc` de los dos módulos (sin eso, una
mutación del mismo tamaño en el mismo segundo reutilizó el bytecode anterior y
dio un falso «passed»; se repitieron las siete). Tras cada restauración, SHA-256
idéntico en los seis archivos de código y pruebas.

| Hallazgo | Corrección localizada | Resultado |
|---|---|---|
| R043-1 | `probikegarage_import._rule_rows`: días de una pieza retirada en R < `at` con referencia ≤ R ⇒ `umbral − _elapsed_days(referencia, R)`, nota «días hasta su retirada» | **Verificado** (mutación: falla, −34,08 frente a 18) |
| R043-2 | `_rule_rows`: sin referencia, nunca montada y `next` = umbral (días ±1) ⇒ fila correcta «sin montar…» | **Verificado** (mutación: fallan `test_r043_2` y `test_differences_are_reported`). `next` negativo en una pieza sin montar sigue siendo diferencia (sondeado) |
| R043-3 | `_rule_rows` + `_within(scale=…)`: tolerancia de distancia `max(100 m, 0,5 % × (umbral − next))` | **Verificado** (mutación con el umbral como escala: falla) |
| R043-4 | `probikegarage._Planner.plan_events`: un evento por (intervención, componente, tipo canónico) | **Verificado** (mutación: dos «Sustitución»). Vida útil destino más otra vida útil listada: una sola (sondeado) |
| R043-5 | `resolve_since_always`: `nesting_depth` antes; pendientes ordenados por (bici 0, anidado profundidad + 1) | **Verificado** (mutación con el orden del volcado: error con el hijo primero). Tres niveles «desde siempre» en los dos órdenes: los tres desde la primera salida, profundidades 0/1/2, y la aplicación lo acepta (sondeado) |
| R043-6 | `plan_baselines`: aviso por pieza con uso inicial y vida útil | **Verificado** (mutación: falta el aviso). En el volcado real son 2 avisos, de las 2 piezas retiradas |
| R043-7 | `plan_events`: `target_id` de `service_interval` añadido a los listados | **Verificado** (mutación: tipo «Servicio» sin intervalo). Con el destino repetido en las dos listas: un solo evento (sondeado) |
| R043-8 | Sin cambio (anotado en §11) | **Verificado**: `_item_rows` sigue con tres `summarize_item_usage`, sólo lectura |
| R043-9 | §9.13 y TESTING.md: 6.145 consultas (0,8 s) y 18.065 (~3,5 s); «~9.000» como tope | **Verificado**: mismas cifras en los dos sitios. La prueba de presupuesto acota 25 copias a ≤ 25 × 130 + 120 = 3.370 < 9.000, así que su recuento es exacto |
| R043-10 | Spec redactada por el orquestador | **Verificado**: un script fuera del repositorio buscó en la spec, el código, las pruebas, TESTING.md, data-sources, dominio y el JSON de validación los nombres y campos `strava_bike` de las bicis, los `gear_id`, los nombres y notas de componentes, intervalos e intervenciones, todos los ids de ProBikeGarage y los 350 `strava_id`. Cero coincidencias de bicis, marcas, modelos, `gear_id`, ids, `strava_id` o notas. Sólo quedan títulos genéricos de intervalos e intervenciones (p. ej. «Max life», «Refresh kit», «Medición»), la nota «Ok», fechas, y una expresión genérica de pieza usada como nombre sintético en las pruebas |
| R043-11 | Opción a: aviso y §13 sin afirmar lo que hacía ProBikeGarage | **Verificado con una precisión (R043-12)**: el aviso del comando («…en Garage reinicia su regla «tipo» (mismo tipo, regla general de las intervenciones)») es correcto y coincide con la prueba y con data-sources |

**R043-12 · nit · texto (corregido).** §13 del dominio y §9.2 decían que el único
caso observable del volcado real «es coherente con ello», o sea, con reiniciar la
regla de mismo tipo. Resultado de una simulación propia, fuera del repositorio,
con la lista de componentes de cada salida, contado sólo en booleanos. Las 10
intervenciones sin ningún intervalo tocan 6 intervalos cuya referencia
cambiaría: 4 vidas útiles no reiniciadas, 1 repetible que no discrimina y 1
repetible que ProBikeGarage **sí** reinició. Ese último tiene un título distinto
del de la intervención, así que Garage no lo reinicia. Ahí Garage reinicia
menos, no lo mismo. Las mismas cifras que el revisor. Además, en las 3
intervenciones conjuntas ProBikeGarage no reinició el intervalo propio de las
calas, igual que Garage (§2.6.2). Los 2 avisos de mismo tipo tienen después 33 y
11 intervenciones con intervalo de esa regla (cuadra con §10). Texto corregido en
`docs/garage-domain.md` §13 y en §9.2; el código y el aviso no cambian.

**Casos límite sin defecto.** Intervención posterior a la retirada de su pieza:
el dominio la admite y la verificación compara en `exported_at`, con lo que
sale como diferencia. Es lo prudente: no se sabe qué haría ProBikeGarage, y el
volcado real no tiene ninguna. Las pruebas de sondeo fueron temporales y se
borraron; no hace falta regresión nueva, porque no hubo defecto de código.

**Ejecutado (55434, PostgreSQL 18.6):**

- `check`: «System check identified no issues (0 silenced).»
- `makemigrations --check --dry-run`: «No changes detected» (0001–0012).
- Suite completa: **2690 passed, 45 subtests passed in 219.22s**, es decir
  2683 + las 7 de revisión.
- `inspect`: 0 filas (sin bases residuales).
- `--dry-run` del volcado real con `--owner 1` (`pbg-dryrun`): 0 errores, 6
  avisos y recuentos idénticos a §9/§11. Los avisos: 1 «desde siempre», 2 de
  mismo tipo, 2 de R043-6 y 1 de desnivel inicial. El propietario 1 sigue con 0
  filas en las 11 tablas de Garage contadas.

Informe: `docs/validation/garage-043.json`. La importación real no se ha
aplicado.
