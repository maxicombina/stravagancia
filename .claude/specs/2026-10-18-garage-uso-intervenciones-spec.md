# Especificación garage-036: uso en cada intervención y comparar piezas

Fecha: 18 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-036`.
Origen: análisis de ProBikeGarage (`docs/research/2026-10-17-probikegarage-rea.md`),
hueco 5 («foto del uso con su diferencia en cada intervención») y la idea
pendiente «comparar cuánto duró cada componente». Usuario ausente: «ante la
duda, documenta las opciones y elige una». **Sin modelos ni migraciones.**

## 1. Punto de partida

`services.statistics` ya calcula, por objeto o bici, un bloque de uso por cada
intervención: desde ella hasta la siguiente del mismo tipo (o hasta ahora), con
lecturas service, cobertura parcial («≥») y estimaciones. Hoy sólo aparece en
el informe detallado de Estadísticas; la ficha y el detalle de una intervención
no lo muestran. ProBikeGarage guarda en cada servicio el uso acumulado y la
diferencia con el anterior.

## 2. Decisiones

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Qué cifra | a) uso acumulado de la pieza al hacerla (ProBikeGarage); b) uso desde la anterior del mismo tipo; c) ambas | **b)** y «desde entonces» para la última. Es lo que se usa para decidir (cuánto duró una cadena, cada cuánto se lubrica) y no depende de conocer toda la vida previa. El acumulado de toda la vida ya está en la ficha («Con lecturas previas…»). |
| Cálculo | a) guardar una foto al registrar; b) calcular al mostrar | **b)**: sin migraciones y siempre coherente si se corrigen salidas o montajes; reutiliza los bloques de `statistics`. |
| Honestidad | — | Igual que en el resto: km/h/salidas observados son un mínimo («≥») salvo lecturas; desconocido si el uso no está calculado; días exactos. |
| Dónde | — | Detalle de la intervención: «Desde la anterior <tipo> (fecha): …» y «Hasta la siguiente (fecha): …» o «Desde entonces: …». Listas de intervenciones de la ficha de componente y de bici: la cifra corta («a ≥ 3.240 km de la anterior»). |
| Comparar piezas | a) página nueva; b) en la ficha de la categoría | **b)**: «Comparar» en la ficha de la categoría (Cadenas, Cubiertas…): cada objeto con su uso total conocido (lecturas + observado), días desde que empezó a usarse y estado (montado, sin montar, retirado). Orden por uso. Retirados incluidos: son los que ya terminaron su vida. |

## 3. Servicio

`garage/services/service_usage.py`:

- `event_usage(actor, event, *, at=None)`: para una intervención propia devuelve
  `previous` (la anterior del mismo destino y tipo, o None), `before` (bloque de
  uso desde la anterior hasta esta; None si es la primera), `after` (desde esta
  hasta la siguiente o hasta `at`) y `next` (la siguiente o None). Usa
  `statistics(actor, item=… o bike=…, started_to=at)` y sus bloques
  `interventions`; sin escrituras.
- `category_comparison(actor, category, *, zone, at=None)`: por objeto de la
  categoría, km (`reading`: lifetime, acquisition o sólo observado), días
  (`days_kind`: montado, inicio de uso o compra) y estado. Ordenado por km de
  mayor a menor, desconocidos al final.
- `EventUsage` incluye `upcoming` (siguiente programada), `future` y
  `retired_at` (el «después» termina en el retiro).

## 4. Pantallas

- `service_event.html`: sección «Uso» con dos filas (antes y después), cifras
  con «≥» cuando son mínimos y la nota de cobertura.
- `item_detail.html` y `bike_detail.html`: sub-línea de cada intervención con
  «a los ≥ 3.240 km de la anterior» (km para objetos y bicis; si no hay km,
  días).
- `detail.html` de categoría: sección «Comparar» con filas por objeto: nombre,
  estado, km (≥), días de uso; enlace a cada ficha.

## 5. Pruebas

Bloques antes/después con tipos distintos que no se mezclan, primera intervención
sin anterior, la última hasta ahora, lecturas service (valor exacto) frente a
observado (≥), uso sin calcular (desconocido), bici frente a objeto, ajena 404,
comparar con retirados, sin uso y orden; GET sin escrituras y presupuesto de
consultas. Suite completa, capturas y revisión independiente.

## 6. Revisión independiente (18 oct) y cambios

Especificación y código revisados juntos: 4 importantes y menores, corregidos
con pruebas.

- **Intervenciones con fecha futura**: no se enlazan con las pasadas. Una futura
  dice «Programada para el …: aún sin uso»; si la siguiente está programada, la
  anterior dice «Hasta hoy (la siguiente está programada para el …)»; las listas
  de la bici no les ponen cifra.
- **Comparar**: la cifra lleva «≈» con lectura estimada y «≥» si es un mínimo
  (`complete` de `statistics`), redondeada hacia abajo cuando es mínimo; sólo se
  muestran km y días (no horas ni salidas: decisión para que quepa en el móvil).
- **Días**: tiempo montado (períodos recortados al retiro o a hoy); el material
  que no se monta (casco, zapatillas) cuenta desde el inicio de uso o la compra,
  y se dice cuál; sin dato, no hay días. Título «Cuánto dura cada uno».
- **Español**: «a ≥ 3.240 km de la anterior», «No hay ninguna intervención
  «…» anterior», días enteros sin redondear hacia arriba.
- **Orden**: empates por fecha de creación y UUID, como `statistics`.
- `bike_spans` repite la rama de bici de `statistics` para no calcular todo el
  material en la ficha de la bici (una consulta más). `category_comparison` usa
  `statistics(category=…)`, que lee todo el uso del propietario: aceptable a la
  escala de uso personal.

Re-verificación (18 oct): las ocho correcciones verificadas; menores añadidos:
el «después» termina en el retiro de la pieza («Hasta su retiro, el …») y la
comparación usa una lectura «desde mi adquisición» si no hay de toda la vida.
