# Exportación personal de Garage — versión 1

`GET /garage/export/` ofrece JSON (`/garage/export/json/`) y ZIP con tablas CSV
(`/garage/export/csv/`). Requiere usuario autenticado activo; incluso un superusuario
recibe sólo su Garage. Todas las respuestas usan caché privada desactivada.

El documento JSON es la representación exacta: `format: garage-export`, `version: 1`,
`exported_at`, `units`, `omitted` y `tables`. UUID estables relacionan categorías,
bicis, objetos, montajes repetidos, lecturas, tipos/intervenciones/reglas,
aplazamientos de avisos (`snoozes`, garage-034: regla, inicio, fin y cantidades),
intervalos de retiro cerrados y retiro vigente (`retired_at` de bicis y objetos),
versiones de perfiles y memberships, excepciones, salidas,
fuentes FIT mínimas y referencias de fotos. No contiene identificador de usuario.
Las fechas son UTC ISO 8601 con seis cifras de microsegundos y `Z`; fechas civiles
usan YYYY-MM-DD. Decimales son cadenas exactas; unidades de métricas están en metros,
segundos y número de salidas (desnivel en metros, potencia en vatios y energía en
kJ desde la fase 3 de garage-030); `value` de una lectura usa la unidad de su `metric`.
Importes conservan moneda ISO 4217 de su fila y dos decimales.

La tabla `snoozes` se añadió el 17 oct 2026 sin cambiar `version: 1`: es una
ampliación aditiva (un lector anterior puede ignorarla) y no altera las demás
tablas ni sus columnas. `ended_at` nulo indica un registro abierto, no que el
aplazamiento siga activo: agotarse o dejar de valer (otra referencia) se calcula.
`reference_event_id` es la intervención que era referencia al posponer y puede
no existir ya; `rule_id` siempre es una regla propia exportada.

Ampliación aditiva de garage-030 (18 oct 2026, sin cambiar `version: 1`): `sources`
admite `source_kind: strava` y añade las columnas `external_id` (id de la
actividad de Strava; nulo en FIT), `gear_id` (bici de Strava observada; vacío en
FIT) y `possible_duplicate`; esas columnas aparecen también en `sources.csv`.
La tabla nueva `strava_gear` (`gear_id`, `name`, `retired`, `bike_id`) guarda
qué bici de Garage representa cada bici de Strava. `field_provenance` puede
decir `strava` con su `source_id`; la bici con procedencia `strava` se valida
contra el vínculo de `strava_gear` de su fuente. Nunca se exportan la cuenta de
Strava, sus permisos, tokens ni los avisos del webhook (`omitted`).

Ampliación aditiva de garage-041 (18 oct 2026, sin cambiar `version: 1`):
`categories` añade al final la columna `icon`, también en `categories.csv`. Es
la clave del icono elegido (`chain`, `tire`, `brake_lever`…, lista en
`garage/icons.py`; minúsculas y guion bajo) o la cadena vacía cuando la
categoría no tiene icono propio y se deduce del nombre al mostrarla. Un lector
anterior puede ignorarla; restaurar debe aceptar claves que no conozca como
vacías, porque la lista puede crecer sin cambiar el formato.

Ampliación aditiva de garage-030 fase 3 (18 oct 2026, sin cambiar `version: 1`):
desnivel y potencia. `rides` y `sources` añaden `elevation_gain_m`,
`average_power_w`, `max_power_w`, `weighted_power_w` y `energy_kj`;
`maintenance_rules` y `snoozes`, `elevation_gain_m` (umbral o cantidad de
desnivel). En los CSV van **al final**: `rides.csv` conserva sus columnas
anteriores en las mismas posiciones y añade las cinco detrás de
`excluded_fields`; `sources.csv` las añade detrás de `elapsed_time_s` (que era
la última) y las dos de mantenimiento detrás de `notes`. `units` nuevas:
`elevation_gain_m: metres`, `average_power_w`/`max_power_w`/`weighted_power_w:
watts`, `energy_kj: kilojoules`. En las salidas siguen la regla de siempre:
con procedencia `manual`, `fit` o `strava` se exportan; desconocidas se omiten
y figuran en `excluded_fields` (también las salidas guardadas antes de la
migración, cuya `field_provenance` aún no tiene esas claves). `weighted_power_w`
es la potencia normalizada del FIT o la ponderada de Strava, según su fuente.
`ItemUsage` sigue omitido: su desnivel se reconstruye desde las salidas, así
que no hay tabla de uso que ampliar. Un lector anterior puede ignorar todo esto.

Las lecturas previas incluyen UUID, objeto, métrica, ámbito, corte, `value`,
intervención vinculada, marca de estimación, notas y la procedencia declarada
(`source`) exactamente como se escribió. `source` es una etiqueta que introduce el
propio usuario: se exporta tal cual, no filtra ni transforma el valor y no certifica
el origen del dato. Garage sólo crea lecturas desde sus formularios; ningún importador
escribe lecturas previas (decisión del usuario del 11 de octubre de 2026).

La presencia de una clave de `manual_overrides` distingue corrección explícita
(incluso NULL) de ausencia. Se valida el codec cerrado de correcciones y procedencia,
la igualdad con el campo efectivo y que cada fuente FIT o Strava referenciada esté
activa, sea de esa clase y pertenezca a esa misma salida.
`field_provenance` conserva únicamente kind/source_id/updated_at validados y
normalizados (`source_id` como UUID canónico en minúsculas, `updated_at` en UTC `Z`).
Los valores de campos unknown se omiten, figuran en `excluded_fields` y no se
convierten en manuales. Por tanto la recuperación puede ser parcial. Dentro de
`manual_overrides`, `field_provenance` y `excluded_fields` la bici se llama `bike`;
su valor efectivo es la columna `bike_id` de la salida.
Fuentes retiradas conservan UUID/ride_id/hash/índice/versión del parser/fechas,
pero no observaciones; no deben reactivarse automáticamente al restaurar.

Las fotos incluyen UUID, destino, dimensiones, bytes, checksum y `content_path`
relativo de la aplicación, protegido por autenticación y autorización por usuario.
No hay binarios, buckets, claves de almacenamiento, jobs ni enlaces firmados.
Estas referencias sólo sirven mientras la foto y la cuenta existan en la aplicación.
No se descarga almacenamiento ni se contactan servicios externos para exportar.

No se exportan usuarios, credenciales, tokens, configuración, datos del legado
Strava, GPS, salud, seriales de sensores ni FIT bruto. Seriales y notas propios
introducidos en inventario sí se conservan. Las allowlists son explícitas; añadir
campos a un modelo no amplía automáticamente el formato. Una referencia ajena o
un JSON corrupto rechaza toda la descarga con 409 genérico, sin identificar
registros ni revelar valores. No se sigue una relación ajena para serializarla.
Para diagnosticarlo, el servidor registra un aviso con la tabla, el UUID propio de
la fila y la clase de error; nunca valores ni identificadores ajenos.

El snapshot se carga y valida bajo una transacción y el mismo bloqueo del
propietario que las escrituras autorizadas; la conversión a JSON o ZIP se hace después
sobre ese snapshot ya materializado. Hay consultas por tabla, no por fila.
Límite de 100 000 filas en total, comprobado al cargar cada lote; exceso produce
413 y ninguna descarga parcial. La construcción es en memoria; el límite de filas
no limita bytes de notas y no promete capacidad ilimitada. Escrituras SQL que
ignoren el protocolo de bloqueo no forman parte de la consistencia prometida.

El ZIP contiene un CSV UTF-8 por tabla y `manifest.json` con versión, unidades,
limitaciones, columnas y número de filas. Todas las celdas se entrecomillan;
comas, comillas y saltos de línea siguen el estándar CSV. NULL se representa con
`\N`; objetos/listas usan JSON compacto. Campos omitidos y NULL confluyen en la
misma celda `\N`, aunque `excluded_fields` permite distinguirlos en las salidas.
Texto con fórmula potencial (=,+,-,@ tras whitespace) o tab/CR en el whitespace inicial recibe
un apóstrofo delante. Esta transformación, el NULL sentinel y las conversiones
que haga una hoja de cálculo impiden prometer restauración exacta desde CSV;
una cadena propia `\N` o un apóstrofo original puede ser ambigua. JSON es la autoridad.

No hay importador automático ni backup completo del servicio. `ImportRun` se omite:
el progreso, selección y errores de un trabajo no pueden reanudarse desde esta copia.
`ItemUsage` y su marca de inicialización se omiten: pueden calcularse nuevamente
con salidas, montajes, retiros, perfiles y excepciones exportados. Esa reconstrucción
produce la resolución actual de esas fuentes; no garantiza reproducir materializaciones
históricas que hayan quedado congeladas tras cambios de perfiles o estén obsoletas.
No convierte el histórico observado en completo, ni recupera campos omitidos,
fotos eliminadas o originales FIT. Restaurar deberá validar relaciones, precedencia,
intervalos y políticas propias de la versión destino antes de escribir datos.
