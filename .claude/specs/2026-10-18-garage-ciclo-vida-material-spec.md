# garage-042 · Ciclo de vida del material visible (18 oct 2026)

Feedback de UI del usuario en las pruebas locales de la demo: quiere ver de un
vistazo, como en ProBikeGarage, qué material está **montado**, cuál está
**disponible** (comprado y guardado, o desmontado de una bici), cuál está
**en uso** sin montar (casco, zapatillas, luces) y cuál **retirado**. Decisiones
del usuario: «Retirado» se queda como nombre; un juego de pastillas es una sola
ficha (sin cantidades); el motivo al retirar queda fuera (tarea futura).

**Sin migración**: todo se deriva de `Installation`, `UsageProfile`/`UsageProfileItem`,
`UsageBaseline`, `acquisition_anchor_at` y `retired_at`. La siguiente migración
sigue reservada como 0013 y no se crea aquí.

## 1. Estados y su derivación (en el instante `now`, UTC aware)

Una única función de servicio (por ejemplo `garage/services/lifecycle.py`,
`item_lifecycles(owner, items, *, at)` → dict `item_id → ItemLifecycle`) es la
única fuente del estado y de su texto; lista, ficha e Inicio la usan o, si Inicio
conserva su cálculo, sus textos salen de las mismas constantes.

| Estado | Condición | Texto (fechas con `{% local_date %}`) |
|---|---|---|
| `retired` | `retired_at is not None and retired_at <= at` (prevalece) | «Retirado el 12 sep 2026» |
| `mounted` | hay `Installation` del item con `started_at <= at` y (`ended_at is None` o `ended_at > at`) | en bici: «En Gravel desde el 3 mar 2026»; dentro de otra pieza: «Sobre Rueda trasera · Gravel desde el …» (bici raíz resuelta como hoy en la ficha con `services.parts.placement`/`home.mount_resolver`; sin bici raíz: «Sobre Rueda trasera desde el …») |
| `in_use` | no retirado, no montado, y alguna `UsageProfileItem` cuyo perfil está vigente (`started_at <= at` y `ended_at` nulo o `> at`) | «En uso · Gravel · Ciclismo de montaña, Cualquier bici» (mismos contextos y orden que Inicio) |
| `available` | el resto | «Disponible»; **«Sin estrenar»** si además nunca tuvo `Installation`, ni `UsageProfileItem` (ninguna versión), ni `UsageBaseline`, ni `acquisition_anchor_at` |

`ItemLifecycle`: `state`, `unused: bool` (sin estrenar), `text: str`, y lo que
necesite la plantilla (bici/pieza/fecha) sin repetir lógica en HTML.
Una retirada programada en el futuro (`retired_at > at`) no es «retirado» (igual
que `_retired` en `services/home.py`). Un montaje que acaba hoy ya no es montado.
Tras «Desmontar», la pieza es «Disponible», nunca «Sin estrenar».

## 2. Lista Material (`inventory_list`, sólo `kind == 'item'`)

- Chips: **Montados** (`state=mounted`) · **Disponibles** (`available`) · **En uso**
  (`in_use`) · **Retirados** (`retired`) · **Todos** (`all`, por defecto como hoy).
  `active` sigue aceptado sin chip (alias de «no retirados», enlaces antiguos);
  cualquier otro valor → `all`.
- Filtro en la base de datos (`Exists` sobre montajes abiertos y perfiles
  vigentes) para que la paginación de 20 sea correcta. «Disponibles» = no
  retirado, sin montaje abierto y sin perfil vigente.
- Fila: línea secundaria «Categoría · texto de estado». El chip «Retirado» se
  mantiene como está. Sin N+1: resolver en bloque los montajes abiertos, perfiles
  vigentes, nombres de bici/pieza y bici raíz de la página (prueba con
  `django_assert_num_queries`/`assertNumQueries` acotado).
- `query` de la paginación ya conserva `state` y `q`. Bicis y categorías no cambian.
- Vacío: «No hay resultados.» como hoy; el enlace «Crear el primero» sólo con
  `all` y sin búsqueda.

## 3. Coherencia en otras pantallas

- Inicio, «Equipación y material sin montar»: «Guardado» → «Disponible» o «Sin
  estrenar»; «En uso · …» como hoy. Título de la sección sin cambios.
- Ficha de material (`item_detail.html`, `lede`): «Sin montar» → «Disponible» /
  «Sin estrenar» / «En uso · contextos»; montado y retirado como hoy.
- `_part_lives.html` («Cuánto dura cada uno»): «Sin montar» → «Disponible».
- No tocar bicis, categorías, formularios ni modelos.

## 4. Pruebas (pytest, PostgreSQL 55434 vía `tools/handoff/garage_test_pg.py`)

- Servicio: cada estado; retirada futura; montaje terminado en `at`; perfil
  terminado; pieza anidada con bici raíz y sin ella; «Sin estrenar» frente a
  «Disponible» tras desmontar, tras una lectura previa, tras un perfil pasado.
- Vista: cada chip devuelve lo correcto; `active`/valor inválido; paginación
  conserva el filtro; textos de fila; nada de otro propietario; consultas acotadas.
- Actualizar las pruebas existentes que fijen «Sin montar»/«Guardado»
  (`tests_mobile_lists.py`, `tests_mobile_home.py`, pantallas de la ficha).
- Suite completa en verde, `manage.py check`, `makemigrations --check --dry-run`
  sin cambios, `inspect` del clúster con 0 filas residuales.

## 5. Fuera de alcance

Motivo al retirar (necesitaría la 0013), cantidades, renombrar «Retirado»,
cambios en bicis o categorías, reordenar la lista.

## 6. Decisiones tomadas en la implementación (18–19 oct 2026)

Afinan los §1–§3 y prevalecen sobre ellos donde difieran:

- **Una sola fuente**: `garage/services/lifecycle.py` (`ItemLifecycle`,
  `item_lifecycles(owner, items, *, at, unmounted)`, `filter_state(queryset,
  state, *, at)`, `mount_resolver`, constantes de los chips) y la etiqueta
  `{% life_text %}` de `garage_ui`, que añade la fecha en la zona del usuario y
  escapa los nombres. Lista, Inicio, ficha y «Cuánto dura cada uno» la usan
  también para lo montado («Sobre Rueda trasera · Gravel desde el …» en las
  piezas anidadas, igual en la ficha que en la lista) y lo retirado.
- **«Sin estrenar»** cuenta también las inclusiones por excepción de una salida
  (`UsageOverride` incluir, salidas empezadas hasta `at`). Una intervención
  (`ServiceEvent`) no es uso: una cadena puede encerarse antes de estrenarla.
  Todo se evalúa hasta el instante `at`: un montaje, perfil, lectura o inicio
  de uso programados en el futuro aún no estrenan.
- **Retirada programada** (`retired_at > at`): la pieza conserva su estado y el
  texto termina con «· se retira el <fecha>» en lista, Inicio, ficha y categoría;
  en Detalles, «Estado: Activo · se retira: …». El chip «Retirado» y el filtro
  «Retirados» sólo para lo ya retirado. En Material, `active` significa «no
  retirado ahora»; Bicis y Categorías conservan su comportamiento anterior.
- **Contextos de «En uso»**: ordenados alfabéticamente, con la etiqueta corta de
  `garage/sports.py` (único `sport_label`, usado por el filtro y el servicio):
  «En uso · Cualquier bici, Gravel · MTB». Inicio y la lista coinciden.
- **Lugar «sin montar» en las filas de «Requiere atención»** (Inicio y Taller):
  sin cambios; indica el lugar, no el estado, y es la misma palabra del título
  de la sección (hallazgo R042-5, rechazado con motivo).
- **Consultas**: Material ≤ 7 consultas fijas; ficha suelta ≤ 44, montada ≤ 47;
  categoría ≤ 28; ninguna crece con el número de filas (pruebas de presupuesto).

## 7. Revisión de código (18 oct 2026)

Revisor independiente (Opus, sólo lectura) sobre el diff real: 8 hallazgos,
1 important, 2 minor, 5 nit, y 6 huecos de spec.

1. **R042-1 (important)** «Sin estrenar» ignoraba las inclusiones por excepción
   de una salida: un objeto con km salía «Sin estrenar». Corregido dentro del
   mismo EXISTS, con prueba.
2. **R042-2 (minor)** La ficha decía «Retirado el <fecha futura>» con una
   retirada programada, en contra del §1. Corregido: estado + «se retira el …».
3. **R042-3 (minor)** «Cuánto dura cada uno» decía «Disponible» también a lo
   que está en uso o sin estrenar. Corregido con el servicio (≤ 2 consultas).
4. **R042-4 (nit)** Ficha «En …» frente a lista «Sobre …» en piezas anidadas.
   Corregido: la ficha usa el servicio; `root_bike` eliminado del contexto.
5. **R042-5 (nit)** «sin montar» como lugar en las alertas. **Rechazado**: es el
   lugar, lo comparte Taller y coincide con el título de la sección.
6. **R042-6 (nit)** Cambios no pedidos en el chip «Retirado» y en `active`.
   Corregido avisando «se retira el …»; el resto aceptado y recogido en §6.
7. **R042-7 (nit)** Lógica duplicada: `_root_bike` frente a `mount_resolver`,
   dos `sport_label`. Corregido: un solo `mount_resolver` en `lifecycle.py`,
   un solo `sport_label` en `sports.py`; EXISTS filtran por propietario.
8. **R042-8 (nit)** Cobertura: filtro frente a servicio sólo en «ahora»; sin
   presupuesto de consultas para la ficha suelta. Corregido: 8 instantes y
   nueva prueba de presupuesto.

Corrección (Opus): 7 arreglados, 1 rechazado; suite 2618 + 45.

## 8. Re-verificación (19 oct 2026)

Verificador independiente (Opus): los 8 hallazgos comprobados en código y
pruebas (`ready: true`). Suite completa **2618 passed, 45 subtests, 183,91 s**;
`check` limpio; `makemigrations --check` «No changes detected»; `inspect` 0
filas; migraciones 0001–0012, ninguna nueva; nada en staging. Observaciones
sin corregir, anotadas en Beads:

- (menor, anterior a garage-042) Con una retirada programada, las acciones de la
  ficha leen `object.retired_at` sin mirar la fecha: muestran «Reactivar» en
  lugar de «Retirar» y ocultan «Montar» y «Añadir pieza». Funciona, porque
  «Reactivar» cancela la retirada programada. Pendiente de decidir.
- (nit) El ejemplo de contextos del §1 queda sustituido por el del §6.
