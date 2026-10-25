# Diseño garage-037: desnivel positivo (pendiente de activar)

Fecha: 18 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-037`.
**Sólo diseño: no implementar hasta que el usuario lo active** («también me
interesa lo de la falta de desnivel en las salidas … aunque eso lo podemos hacer
luego?», 17 oct). Independiente de Strava (garage-030, aplazada).

## 1. Qué falta

Las salidas, el uso por objeto, las reglas y las estadísticas no tienen desnivel.
ProBikeGarage lo muestra en cada bici y componente, lo usa como tipo de intervalo
(«Desnivel positivo», con Premium) y en sus estadísticas. El FIT de Garmin lo
trae en la sesión: campo nativo 22 `total_ascent` (metros, entero sin signo de
16 bits; puede faltar o ser inválido, 0xFFFF).

## 2. Opciones y elección propuesta

| Tema | Opciones | Propuesta |
|---|---|---|
| Dónde se guarda | a) sólo en `Ride`; b) en `RideValues` (salida y fuente FIT) y en `ItemUsage` | **b)**: como distancia y tiempo, con procedencia por campo (`fit`/`manual`), correcciones manuales que sobreviven a la reimportación y uso por objeto materializado. |
| Tipo | entero o Decimal | `DecimalField(20, 3)` en metros, como `distance_m`, para reutilizar `exact_usage_value` y los límites. |
| Salidas ya importadas | a) desconocido; b) reimportar con versión nueva del parser | **a) + b)**: sin dato el desnivel es desconocido (nunca 0). Reimportar el mismo FIT con `PARSER_VERSION` nuevo completa el campo sin tocar correcciones manuales; Garage no guarda el FIT bruto, así que hace falta el archivo original. |
| Salidas manuales | — | Campo opcional «Desnivel positivo (m)». |
| Reglas | — | `MaintenanceRule.elevation_gain_m` y `MaintenanceSnooze.elevation_gain_m`, lo primero que llegue como los demás umbrales; cobertura parcial «≥». |
| Estadísticas | — | Total y por bici del período, desnivel del material, «m» en el gráfico mensual como serie aparte (nunca segundo eje). |
| Exportación | a) versión 2; b) versión 1 ampliada | **b)**: columnas nuevas aditivas en `rides`, `sources`, `maintenance_rules`, `snoozes`; documentado. |

## 3. Cambios previstos

- Migración aditiva 0010: `AddField` nulo en `Ride`, `ActivitySource`,
  `ItemUsage`, `MaintenanceRule`, `MaintenanceSnooze` y sus restricciones de
  rango. Nunca en Neon (Docker Compose `web` migra al arrancar).
- `importers/fit.py`: leer el campo 22 de la sesión; inválido → None;
  `PARSER_VERSION` nuevo. `ride_values.METRIC_FIELDS` incluye `elevation_gain_m`.
- `services/usage.py`: materializar el desnivel por objeto y salida.
- `maintenance_due`: métrica nueva; `presentation`: unidad «m», textos.
- Formularios: salida manual, regla (m), vida útil y posponer.
- Estadísticas, ficha de bici y de componente, Inicio («2.795 km · 31.200 m»).
- Pruebas: parser (válido, ausente, 0xFFFF), procedencia y reimportación,
  materialización, reglas y aplazamientos por desnivel, exportación,
  presupuestos de consultas.

## 4. Riesgos

- Es la tarea más grande de las ideas de ProBikeGarage (toca importación,
  materialización, reglas, estadísticas y exportación).
- Desnivel de distintos dispositivos no es comparable con exactitud
  (barómetro frente a GPS): se muestra como dato del FIT, sin corregir.
- Sin reimportar, el histórico queda «desconocido»: los totales serán un mínimo.

## 5. Estado (18 oct 2026)

Se implementa dentro de la fase 3 de Strava (desnivel y potencia): decisiones y
migración 0012 en `.claude/specs/2026-10-18-garage-strava-fase3-spec.md`, que
sustituye a este diseño.
