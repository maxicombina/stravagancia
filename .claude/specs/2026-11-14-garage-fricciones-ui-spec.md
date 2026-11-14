# garage-047 · Fricciones de UI (14 nov 2026)

> **Estado: borrador con las rondas 1 y 2 de la crítica aplicadas** (R1-01 a R1-16 y
> R2-01 a R2-09, registro en §10). Escrita sobre la rama `garage-047-fricciones`, nacida de `garage-050-anillos` en
> `9a2b2a1` («Anillos» terminado y sin fusionar; no se fusiona). Sólo se ha escrito este
> archivo: ni código, ni plantillas, ni pruebas, ni Beads, ni git.

Origen: `bd show garage-047`. Son fricciones que vieron los agentes al cargar a mano la
réplica de ProBikeGarage (1 nov), más el feedback del propio usuario sobre la página del
histórico y cuatro añadidos del 14 nov. **Regla del usuario (3 nov), literal:**
«arréglalas apenas puedas, el orden me da igual. anótalas cuando las arregles, que
repasaremos antes de ir a prod». Por eso cada fricción se resuelve con la opción
recomendada, sin preguntar, y queda anotada. Las decisiones que el usuario debe ver en
el repaso (garage-052) llevan la marca **[052]**.

**Rutas.** Las que llevan carpeta son relativas a la raíz del repositorio. Las que no:
los `*.py` sin carpeta están en `garage/`, salvo los de servicio, que están en
`garage/services/` (por ejemplo `home.py`, `lifecycle.py`, `retirement.py`,
`installations.py`, `strava_sync.py`, `rides.py`, `ownership.py`, `baselines.py`,
`snoozes.py`, `usage_profiles.py`, `categories.py`, `parts.py`, `workshop.py` y
`statistics.py`; la lista completa es `ls garage/services/`);
`garage_ui.py`, en `garage/templatetags/`; `garage.css` y `garage.js`, en
`garage/static/garage/`; las plantillas (`*.html`), en `garage/templates/garage/`.

**Sin migración.** Ninguna fricción la necesita. Dos tentaciones la crearían y se
evitan a propósito: cambiar `Meta.ordering` de los modelos (F10) y cambiar las
etiquetas de los `choices` de `UsageBaseline` o `ImportRun` (F05, F21). Las etiquetas en
español van en formularios, filtros y plantillas. La siguiente migración sigue siendo
la `0013`.

---

## 1. Fricciones numeradas

Cada viñeta del alcance es una fricción. La correspondencia literal con el texto de
Beads está en §9.

| F | Origen en garage-047 | Fricción (resumen) | Estado en `9a2b2a1` | Bloque |
|---|---|---|---|---|
| F01 | Datos, 1 | Zona horaria escondida al final; el resumen no cambia; la barra tapa el campo | Sigue. La barra no tapa la zona mientras esté al final; en su sitio nuevo (D11) sí la taparía, y B6 lo evita | B6 |
| F02 | Datos, 2 | Nombres repetidos indistinguibles en los selectores de objeto; retirados sin marca | Sigue | B5 |
| F03 | Datos, 3 | Fechas precargadas con «ahora» al segundo | Sigue | B6 |
| F04 | Datos, 4 | Retirar no dice qué cierra ni cuándo se rechaza; sin «guardando…» | Sigue | B8 |
| F05 | Datos, 5 | Registrar lectura en metros y segundos; lecturas en inglés y en bruto en la ficha | Sigue | B9a, B9b |
| F06 | Datos, 6 | «Sustitución» en Nueva regla la convierte en vida útil sin decirlo | Sigue | B3 |
| F07 | Textos, 1 | Etiquetas y errores en inglés | Sigue (y más de lo que decía Beads) | B2 |
| F08 | Textos, 2 | Sin mensaje al guardar tipo, regla e intervención | Sigue | B3 |
| F09 | Textos, 3 | Títulos en plural, «---------», Categoría casi al final | Sigue (también «Editar bicis», Reemplazar, el filtro de Estadísticas y las excepciones de una salida) | B2 |
| F10 | Textos, 4 | Orden alfabético sensible a acentos y mayúsculas | Sigue | B4 |
| F11 | Textos, 5 | Garaje vacío dice «Todo tu material está montado.» | Sigue | B13 |
| F12 | Textos, 6 | No se ve qué usuario tiene la sesión | Sigue | B13 |
| F13 | Textos, 7 | Placeholder «EUR» parece un valor | Sigue | B2 |
| F14 | Ficha, 1 | Retirar y Montar escondidos en Detalles; tres enlaces de montar | Sigue | B11 |
| F15 | Ficha, 2 | Montajes sólo con fecha; horas sin zona | Sigue | B11 |
| F16 | Ficha, 3 | Padre retirado: «Sin piezas montadas dentro» sin más | Sigue | B11 |
| F17 | Ficha, 4 | Días de una regla redondeados hacia abajo por los dos lados | Sigue | B12 |
| F18 | Ficha, 5 | «a ≥ 0 km de la anterior» sin salidas | Sigue | B12 |
| F19 | Ficha, 6 | Crear categoría: radio sin marcar; Guardar falló a un clic | **Ya resuelta / no se reproduce** | — |
| F20 | Ficha, 7 | Nueva regla: «Contar desde» y umbrales bajo el pliegue y la barra | Sigue | B7 |
| F21 | Feedback del usuario | Página del trabajo del histórico: «¿cómo sé si falta?»; segundo trabajo | Sigue | B14 |
| F22 | Añadido (a) | `floatformat:3` («Km: 2795.000») y otros formatos en bruto | Sigue (más sitios, también horas con microsegundos en Estadísticas) | B10 |
| F23 | Añadido (b) | Tamaño táctil de «Corregir lectura» | **Ya resuelta por Anillos** (medida) | — |
| F24 | Añadido (c) | Salidas: «Sólo las que están por revisar» con bici da siempre lista vacía | Sigue | B1 |
| F25 | Añadido (d) | Carácter nulo en la búsqueda: error 500 | Sigue (también en Material, Bicis y Categorías) | B1 |

**Total: 25.** Ya resueltas: F19 y F23. Ninguna sale de los bloques por requerir al
usuario (§6).

---

## 2. Cómo se comprobó

- **Código** leído en `9a2b2a1`, con las líneas citadas en cada F.
- **Demo de esta copia** (puerto 8769, base `stravagancia_test_demo_047`, usuario
  ficticio `demo`): páginas pedidas por HTTP con sesión y medidas con un navegador sin
  cabeza a **390×706**, el alto que cita Beads.
- **Escrituras:** ninguna. Se enviaron dos formularios **inválidos a propósito** (una
  categoría sin nombre y un montaje que se solapa) para leer sus errores; los dos se
  rechazaron y se comprobó después que no quedó nada guardado.
- **Base de datos:** una sola consulta de sólo lectura con valores literales, para ver
  la intercalación (`C`) y cómo ordena (F10).
- **Ronda 1 de la crítica (§10):** se reprodujo cada hallazgo antes de aplicarlo. Con
  CDP en la demo 8769, sin enviar nada (F01, F20); con consultas de sólo lectura con
  valores literales en el clúster local de pruebas, que tiene `es-x-icu` (F10); con un
  formulario sin guardar en un shell con `settings_test` (F07); y leyendo HTML y código
  (el resto).
- **Ronda 2 de la crítica (§10):** igual, se reprodujo cada hallazgo antes de aplicarlo.
  Un POST **inválido a propósito** más en la demo 8769 (una categoría con un nombre que ya
  existe): se rechazó, y después la lista seguía con una sola categoría de ese nombre.
  En un shell con `settings_test` y la base 047, sin guardar nada: los mensajes de
  `DateField`, del carácter nulo y de `ExactUsageDecimalField`, y el camino de un error
  del servicio al guardar (simulado sobre un formulario válido, sin llamar al servicio).
  Consultas de sólo lectura a `pg_collation` y una consulta con una intercalación que
  no existe (F10). El resto, leyendo código.
- **Lo que la demo no permite ver**, y por eso se comprueba en código y se cubrirá con
  pruebas: nombres repetidos (la demo no los tiene), lecturas de uso (no hay
  ninguna), trabajos de importación (no hay), un padre retirado con piezas anteriores
  y una regla de calendario como cifra principal.

---

## 3. Decisiones (D1–D25)

Cada una trae la alternativa descartada en su F (§4).

- **D1 · Alcance.** 25 fricciones. F19 y F23 no se tocan: sólo se vuelven a mirar en
  las capturas finales (§8).
- **D2 · Carácter nulo (F25).** Se quita de la búsqueda y se busca el resto, en las
  cuatro listas con buscador (Salidas, Material, Bicis y Categorías). **[052]**
- **D3 · Píldora de pendientes (F24).** Con una bici elegida, no se ofrece. Si llega
  por URL con las dos cosas, la lista vacía explica por qué. **[052]**
- **D4 · Errores en español (F07).** Se reutiliza `SpanishWebMixin`
  (`maintenance_forms.py:89-97`) en los formularios web de inventario, montajes y
  lecturas, y se amplía su diccionario `SPANISH` con los mensajes de modelos, servicios
  y validadores que esos formularios pueden mostrar, también los de montajes y del ancla
  de adquisición. `FIELD_MESSAGES` gana los códigos de decimales (`max_decimal_places`,
  `max_digits`, `max_whole_digits`) y el del carácter nulo, e `INVALID` gana `DateField`.
  Todo `__init__` que cree campos después de `super().__init__()` llama a
  `spanish_fields(self)` al final, como ya hacen `lifespan_forms.py:83` y
  `snooze_forms.py:65`. Cada error sale **una sola vez** y nunca uno falso (R2-01). No se
  toca el admin.
- **D5 · Títulos, opción vacía y orden (F09).** Títulos en singular, «—» como opción
  vacía de los selectores de formulario, «Elige una categoría» en Categoría, y Categoría
  justo detrás de Nombre. En los filtros de Estadísticas, «Todas» o «Todos». **[052]**
- **D6 · Moneda (F13).** Se quita el placeholder; la ayuda ya pone el ejemplo.
- **D7 · Mensajes al guardar (F08).** Un mensaje en cada guardado de tipo, regla e
  intervención (textos en F08). **[052]**
- **D8 · «Sustitución» en reglas (F06).** La opción lo dice en su texto y, al guardar,
  el mensaje confirma que es la vida útil. No se bloquea. **[052]**
- **D9 · Orden alfabético (F10).** Intercalación ICU española (`es-x-icu`) en las
  consultas, sin tocar `Meta.ordering`. Lo que se ordena en memoria conserva el orden de
  la base: sale de una consulta ya ordenada y sólo se reordena con ordenaciones estables
  por otras claves, o por la posición en esa consulta. No se reimplementa ICU en Python.
  Una clave `name_key` sólo donde no hay consulta ordenada a mano, documentada como
  aproximación. Una comprobación de sistema de Django avisa, antes de servir páginas, si
  la base no tiene `es-x-icu` (R2-09). **[052]** (riesgo de despliegue en §6).
- **D10 · Selectores de objeto (F02).** Etiqueta «Nombre · Categoría · dónde está», los
  retirados al final y marcados. Si dos etiquetas siguen iguales, se añade una fecha.
  Sin buscador. **[052]**
- **D11 · Zona horaria (F01).** El desplegable va justo detrás del último campo de fecha
  y hora, y su resumen dice qué cambia: «Horas en Europe/Madrid · Cambiar».
  `garage.js` lo actualiza al escribir y, al abrirlo, lo desplaza lo justo para que la
  barra fija no lo tape. Sigue cerrado y con la zona del navegador. **[052]**
- **D12 · «Ahora» por defecto (F03).** Al minuto, con la ayuda «Por defecto, ahora. Si
  fue antes, cámbialo.» sólo donde el valor de partida es «ahora»: no al editar un
  montaje, que trae su inicio guardado (R2-06). No se deja vacío. **[052]**
- **D13 · Nueva regla más corta (F20).** Los umbrales van de dos en dos con el
  `.field-row` que ya existe; se quita la ayuda «Número de salidas.». **[052]**
- **D14 · Retirar (F04).** La página dice qué montaje cierra y qué instante, como
  mínimo, exige su historial, contando también lo que lleva dentro si se ofrece
  retirarlo. Es una condición necesaria, no una promesa: el servidor sigue mandando.
  «Guardando…» con `garage.js` y sin `disabled`, en los `form.form` POST y en los que
  llevan la marca `data-busy`: «Sincronizar ahora», «Continuar importación» de Strava y
  los atajos de posponer (R2-07). **[052]**
- **D15 · Lecturas (F05).** Se escriben en km, horas o salidas con un campo nuevo; el
  valor exacto en metros o segundos se sigue aceptando. En la ficha, en español y
  formateadas. Las palabras salen de una sola fuente; el traslado va en un bloque
  aparte, sin cambios visibles (B9a), antes del cambio de comportamiento (B9b). **[052]**
- **D16 · Formatos heredados (F22).** Los filtros españoles que ya existen sustituyen a
  `floatformat` y a los decimales en bruto. «Evaluado a», los «ahora» de Estadísticas
  (`report.end`, `block.end`) y las horas que guarda el servidor con `now()` (última
  sincronización, creación de un trabajo, inicio de un aplazamiento y vigencias «desde
  ahora») se muestran al minuto (R2-03). El «Restante» de los detalles técnicos redondea
  los días como el anillo (D20).
- **D17 · Acciones de la ficha (F14).** Una tarjeta «Más acciones», visible, con
  Retirar/Reactivar y, si está montado, Desmontar, Reemplazar y «Añadir un montaje
  pasado». Se quita «Montar / remontar» del desplegable. La bici gana su «Retirar»
  visible. **[052]**
- **D18 · Horas de los montajes (F15).** La cronología muestra la hora cuando no es
  medianoche (`local_bound`) y una nota dice la zona. **[052]**
- **D19 · Piezas anteriores (F16).** Sin piezas ahora pero con historia, se nombran
  las que llevaba. **[052]**
- **D20 · Días que quedan (F17).** Se redondean hacia arriba, como ya hace el
  aplazamiento (`presentation.py:282-283`), en el anillo, en la fila y en los detalles
  técnicos del Taller. **[052]**
- **D21 · «≥ 0 km» (F18).** Un «≥ 0 km» no informa: si la cifra **mostrada** de un
  mínimo es «0», se muestran los días. **[052]**
- **D22 · Garaje vacío (F11).** Cuatro textos según el caso.
- **D23 · Sesión (F12).** «Has entrado como …» bajo «Cerrar sesión», en Más. **[052]**
- **D24 · Histórico (F21).** Estado destacado en una frase que dice qué hacer. No se
  crea un segundo trabajo de Strava si hay uno sin terminar (se va a él); la
  comprobación va en el servicio, bajo el cerrojo del dueño. Se pide confirmación sólo
  si un trabajo completado **cubre de verdad** esa fecha: empezó en ella o antes, es de
  la conexión actual con Strava y terminó hace como mucho `SYNC_DAYS` días, lo que
  «Sincronizar ahora» alcanza. Un trabajo sin terminar gana al aviso: la vista lo mira
  antes y lleva a él sin pedir confirmación (R2-08). **[052]**
- **D25 · Errores en español en el resto de formularios web (F07, ampliación; añadida
  durante la implementación, 14 nov).** La revisión de B2 (B2-R2-03, §10.1) encontró
  mensajes en inglés en formularios web fuera de la lista de D4: excepción de una
  salida, perfil nuevo, salida manual y su corrección, Estadísticas con la zona vacía,
  vista previa, ejecución y reanudación del FIT, foto y el lote de bicis. D4 los dejaba
  fuera y la aceptación de B2 («ningún formulario web») los incluía. Gana la aceptación:
  mismo `SpanishWebMixin` y mismas reglas que D4 (cada error una sola vez, nunca uno
  falso, el admin no se toca). Va en su propio bloque, **B2b**. **[052]**

---

## 4. Fricción por fricción

Formato: estado y evidencia · causa · recomendada · descartadas · textos · pruebas ·
llamadores (grep) · riesgos. Las pruebas se escriben **antes** del arreglo y salen del
comportamiento, no de la implementación. Son de dos clases:
- **nuevas**: fallan hoy y se ven fallar antes del arreglo;
- **guardas**: pasan hoy y tienen que seguir pasando (lo que el arreglo no debe
  romper). Se ven pasar antes y después; no se fuerza un fallo artificial.

### F01 · Zona horaria escondida

- **Estado: sigue.**
  - **Con la zona al final, la barra no la tapa.** Medido en Nueva regla a 390×706, con
    el desplegable abierto y la página al final: el campo de zona queda en 353–403 px y
    la barra en 479–555 px. La barra es `sticky` dentro del formulario
    (`garage.css:323`) y termina con él.
  - **En su sitio nuevo (D11), la taparía.** Reproducido con CDP en la demo 8769 a
    390×706: con el `details.zone` movido detrás de «Contar desde» y la página
    desplazada hasta dejar el resumen justo encima de la barra (resumen en 489–536 px,
    barra en 540–616 px), al abrirlo la caja de la zona queda en 568–618 px, debajo de
    la barra. El punto central de la caja devuelve el botón de la barra
    (`elementFromPoint`). El `scroll-padding-bottom` (186 px, `garage.css:61`) sólo
    actúa al enfocar, y una caja tapada no se puede enfocar tocándola.
  - **Sigue también:**
    - en `form.html` el `<details class="zone">` va cerrado y **al final**, detrás de
      Notas (`form.html:13-17`). En `lifespan.html` ya va detrás de «Cuenta desde» y de
      sus dos notas opcionales (líneas 20-24);
    - el resumen lo pinta el servidor y **no cambia** al escribir otra zona.
      Comprobado: tras escribir `America/Chicago`, el resumen seguía con la zona del
      navegador.
  - Que venga con la zona del navegador (`local_forms.localize`, cookie `garage_tz`)
    es lo correcto y no cambia.
- **Causa:** `form.html:11` saca `time_zone` del bucle de campos y lo pinta después de
  todo. `garage.js` no hace nada con él.
- **Recomendada (D11):**
  1. Un único ayudante de presentación del formulario (por ejemplo, el filtro
     `form_layout` en `garage_ui.py`) devuelve los campos visibles en grupos (F20 lo
     reutiliza para las filas). Marca dónde va la zona: **justo detrás del último campo
     `LocalDateTimeField` visible**, o al final si no hay ninguno. `form.html` lo usa.
     `lifespan.html` no la mueve: ya va detrás de «Cuenta desde», y sus dos notas
     opcionales hablan de ese campo; sólo cambia el resumen.
  2. Resumen: «Horas en {zona} · Cambiar». La zona va en un `<span data-zone-name>`.
  3. `garage.js` (sólo mejora):
     - al escribir en `time_zone`, copia el texto recortado al `<span>`. Vacío → «—»;
     - en el evento `toggle` de un `details.zone`, si queda abierto, llama a
       `scrollIntoView({block: 'nearest'})` sobre el propio `details`. Respeta el
       `scroll-padding` que ya existe y no enfoca el campo, así que no abre el teclado.
       Probado en el DOM de la demo con el caso de arriba: la caja pasa a 331–520 px,
       por encima de la barra (540 px).
     Sin JS, el desplegable se abre igual y se desplaza a mano.
  4. Con errores en la zona, el desplegable sale abierto, como hoy.
- **Descartadas:**
  - dejar la zona siempre visible: un campo de texto más en cada formulario, para algo
    que casi nunca cambia;
  - poner la zona en la etiqueta de cada fecha: no se actualiza sin JS y alarga las
    etiquetas a 320 px;
  - un `<select>` de zonas: unas 600 opciones.
- **Textos:** «Horas en Europe/Madrid · Cambiar».
- **Pruebas nuevas (fallan hoy):**
  - `test_the_zone_follows_the_last_date_field`. En Montar, el `details.zone` va
    inmediatamente después del campo «Final»; en Registrar mantenimiento, después de
    «Fecha y hora»; en Nueva regla, después de «Contar desde»; en Crear material,
    después de «Inicio del uso desde adquisición».
  - `test_the_zone_summary_says_what_it_changes`: con la cookie `garage_tz=Europe/Madrid`,
    el resumen es «Horas en Europe/Madrid · Cambiar», también en Vida útil.
  - `test_a_bound_invalid_zone_is_repeated_escaped`: formulario enlazado con una zona
    inválida que contiene `<`; el desplegable sale abierto y el resumen dice «Horas en
    …» con lo escrito, escapado.
  - Hay que **actualizar** `tests_mobile_workshop.py:118`, que fija el texto anterior.
    Es el cambio buscado.
- **Guardas (pasan hoy):**
  - `test_without_date_fields_the_zone_goes_last` (un formulario sin campos de fecha:
    la zona, al final);
  - `test_the_lifespan_zone_stays_after_its_start` (Vida útil no la mueve).
- **Sin ejecutor de JS:** el desplazamiento al abrir se comprueba con CDP (B6, §8),
  midiendo la caja frente a la barra. No se añade una guarda que busque
  `scrollIntoView` en el texto de `garage.js`: sólo repetiría la implementación.
- **Llamadores:** `form.html` lo usan `views.form_page` (todas las páginas de
  inventario, montajes, lecturas e histórico) y `maintenance_views.maintenance_edit`;
  `lifespan.html`, `lifespan_views.py`. `details.zone` en CSS: `garage.css:542-544` y
  la guarda `tests_ui_guards.py:555`.
- **Riesgos:**
  - `_together.html` (`form.html:12`) queda detrás de la zona en Registrar
    mantenimiento. Se acepta: es un bloque aparte, con su propio título;
  - sin JS, la zona abierta en su sitio nuevo puede quedar bajo la barra hasta que se
    desplace la página. Se acepta: es una mejora progresiva, como el resto de
    `garage.js`.

### F02 · Nombres repetidos indistinguibles en los selectores de objeto

- **Estado: sigue** (código; la demo no tiene nombres repetidos). Las opciones son
  `str(item)` = el nombre (`models.py:43-44`). Las listas son `scoped_inventory(...,
  Item)`, con los retirados mezclados y sin marca:
  - `maintenance_forms.py:197-200`: Objeto de reglas e intervenciones;
  - `web_forms.py:225-226`: Montar;
  - `web_forms.py:263`: Objeto entrante de Reemplazar;
  - `web_forms.py:312-313`: Transferir.

  Comprobado en la demo: «Objeto de destino» de Montar es una lista plana de nombres.
  `part_forms.PartChoice` (`part_forms.py:11-13`) ya añade la categoría: es el
  precedente.
- **Recomendada (D10):** un campo `ItemChoiceField` (y su pareja para bicis) en un
  módulo nuevo, por ejemplo `garage/choices.py`:
  - **etiqueta:** «{nombre} · {categoría} · {dónde}». «Dónde» sale de
    `lifecycle.item_lifecycles` (un lote, como mucho tres lecturas) y es «en {bici}»,
    «sobre {objeto}», «en uso», «disponible», «sin estrenar» o «retirado»;
  - **orden:** el de la base con `by_name` (F10), y después una ordenación **estable**
    que sólo lleva los retirados al final. Así cada grupo conserva el orden de la base,
    el mismo de la lista de Material, sin una clave Python de nombre;
  - **si dos etiquetas coinciden**, se les añade una fecha en la zona del usuario:
    «desde el {d}» si está montado, «retirado el {d}» si está retirado, «comprado el
    {d}» o, sin compra, «alta del {d}». La zona se la pasa `localize()` al campo, igual
    que hoy pasa los widgets. Si aun así coinciden, «(2)», «(3)»… en el orden de la
    lista;
  - **bicis:** «{nombre}», o «{nombre} · retirada» al final.

  Se aplica a los cuatro sitios de arriba. Lecturas (`BaselineWebForm`) tiene el
  objeto fijo y deshabilitado: no cambia.
- **Descartadas:**
  - un buscador en el selector: necesita JS propio o una dependencia;
  - `<optgroup>` por bici: `ModelChoiceField` no lo da y repetiría el «dónde»;
  - quitar los retirados: sería «quitar algo que se usa», porque registrar historia en
    una pieza retirada es legítimo.
- **Textos:** «Cadena 11v · Cadenas · en Carretera», «Sillín B · Sillines · disponible»,
  «… · retirado el 3 mar 2025».
- **Pruebas nuevas (fallan hoy):**
  - `test_an_item_option_names_its_category_and_place`;
  - `test_retired_items_go_last_and_say_so`;
  - `test_two_equal_labels_get_a_date` (dos objetos con el mismo nombre y la misma
    categoría, uno montado y otro retirado, y otro par los dos disponibles);
  - `test_identical_labels_are_numbered`;
  - `test_the_label_dates_follow_the_viewer_zone` (fecha cerca de medianoche en Madrid
    frente a UTC).
- **Guardas (pasan hoy):**
  - `test_item_options_cost_the_same_queries_with_5_or_25_items` (presupuesto fijo);
  - `test_a_retired_option_still_saves` (registrar una intervención en un retirado
    sigue funcionando);
  - `test_editing_keeps_the_stored_choice` (un montaje antiguo sobre un retirado
    conserva su valor);
  - `test_options_follow_the_material_list_order`: con «sram gx», «Sram GX» y «SRAM
    GX», y con «camara», «Camara» y «Cámara», los no retirados del selector salen en
    el mismo orden que la lista de Material. Hoy pasa porque las dos usan la base; tiene
    que seguir pasando cuando las dos usen `es-x-icu`.
- **Llamadores:** los cuatro formularios de arriba; sus vistas son `views.py:310-385` y
  `maintenance_views.py:127-190`. `localize()` (`local_forms.py:55`) lo llaman
  `views.local`, `maintenance_views.py:154`, `lifespan_views.py:37`,
  `statistics_views.py:83,101` e `history_views.py:30,49`.
- **Riesgos:** en el selector nativo de iOS, una etiqueta larga se corta con puntos
  suspensivos. Por eso la fecha sólo aparece cuando hace falta.

### F03 · Fechas precargadas con «ahora» al segundo

- **Estado: sigue.** En la demo, Retirar y Montar salen con un valor como
  `2026-11-14T11:30:32` y `step="1"`. Causa:
  - `TemporalActionForm` (`web_forms.py:202`) e `InstallationWebForm`
    (`web_forms.py:234`) usan `microsecond=0`, sin quitar los segundos;
  - `LocalDateTimeInput` pone `step="1"` cuando hay segundos (`local_forms.py:45-46`).

  Registrar mantenimiento (`maintenance_views.py:135`) y Añadir pieza
  (`part_forms.py:26-27`) ya van al minuto.
- **Recomendada (D12):**
  - las dos precargas, al minuto (`second=0, microsecond=0`);
  - ayuda en el campo «Instante del cambio» y en «Inicio» de Montar: «Por defecto,
    ahora. Si fue antes, cámbialo.». En `InstallationWebForm`, **sólo cuando
    `installation is None`** (alta), también en un POST de alta con errores:
    `views.installation_edit` (`views.py:310-325`) usa el mismo formulario para «Editar
    montaje de …», y ahí `started_at` viene del período guardado (`web_forms.py:227-232`),
    no de «ahora». Un `help_text` fijo del campo diría algo falso al editar (R2-06);
  - Añadir pieza hereda la ayuda y ya no necesita su propio redondeo (se puede dejar:
    no es parte de esta F).
- **Descartadas:**
  - dejarlo vacío y obligatorio: el caso más común, «ahora», obliga a teclear una fecha
    entera en el móvil;
  - precargar la fecha de compra: no aplica a Retirar ni a Mover.
- **Pruebas nuevas (fallan hoy):** `test_now_is_offered_to_the_minute`, con el reloj
  fijado en `10:31:27`: el valor encaja con `AAAA-MM-DDTHH:MM`, sin segundos ni `step`
  en Retirar, Desmontar, Reemplazar, Transferir y Montar.
  `test_the_default_says_it_is_now`.
- **Guardas (pasan hoy), casos límite:**
  - zona con cambio de hora (`localize` ya se niega a convertir una hora repetida);
  - un formulario enlazado conserva lo enviado, con segundos si los traía;
  - editar un montaje conserva sus segundos guardados;
  - `test_editing_a_mount_does_not_say_now`: «Editar montaje de …», en GET y en un POST
    con errores, no muestra «Por defecto, ahora.» (pasa hoy porque aún no hay ayuda; la
    ayuda nueva no debe llegar ahí).
- **Llamadores:** `TemporalActionForm` lo usan `views.installation_action` (close),
  `ReplacementWebForm`, `RetireWebForm`, `TransferWebForm` y `part_forms.PartWebForm`;
  `InstallationWebForm`, `views.installation_edit`.
- **Riesgos:** retirar «ahora» (redondeado hacia abajo) algo montado hace menos de un
  minuto se rechaza por el historial. Es raro, y el error ya es español
  (`retirement.py:38-41`).

### F04 · Retirar no dice qué cierra; sin «guardando…»

- **Estado: sigue.**
  - La explicación es fija: «Se cerrarán los montajes abiertos compatibles con este
    instante.» (`views.py:291-292`). La ayuda de `with_parts` lista las piezas de
    dentro (`web_forms.py:285-291`), pero no el montaje del propio objeto.
  - La regla de rechazo (`installations.py:191-199`: un montaje que empieza en o
    después del instante, o que termina después) sólo se descubre al guardar.
  - `garage.js` no hace nada al enviar un formulario.
- **Recomendada (D14):**
  1. Un servicio de lectura en `retirement.py`, por ejemplo `retirement_preview(actor,
     obj, *, at)`, que devuelva:
     - el montaje abierto del propio objeto (bici u objeto padre e inicio);
     - el **límite propio**: el mayor de los inicios y finales de los montajes que
       `_close_for_retirement` revisa para el objeto (como objeto, como padre o como
       bici). Retirar exige un instante posterior a todos los inicios y no anterior a
       ningún final;
     - el **límite con lo de dentro**, sólo si la página ofrece `with_parts`: el mismo
       cálculo sobre todo el alcance de `_scope(owner, obj, at)`, porque
       `retire_with_parts` llama a `retire_one` para cada pieza de dentro
       (`retirement.py:56-75`) y cada una pasa su propio `_close_for_retirement`, que
       también mira los montajes cuyo padre es esa pieza (`installations.py:191-199`).
       Una pieza de segundo nivel montada después del límite propio rechaza la
       retirada con `with_parts`.

     El límite es una condición **necesaria**, no suficiente: un período inactivo ya
     registrado (`retirement_overlap`, `models.py:128`, `ownership.py:247`) rechaza con
     otra regla, y el historial puede cambiar entre la lectura y el envío. Por eso el
     texto no promete que baste, y el error del servidor, ya en español y con el nombre
     de lo que bloquea (`retirement.py:38-52`), sigue mandando.
  2. `views.retire` compone la explicación con `datetime_text` (zona del usuario) y la
     conserva al reenviar con errores.
  3. `garage.js`: en el envío de un `form.form` con `method=post` (no el de tema) **o de
     un formulario con la marca `data-busy`**, el botón que envió pasa a
     `aria-disabled="true"`, gana la clase `busy` y, si su texto empieza por «Guardar»,
     dice «Guardando…». Otro envío del mismo formulario se cancela. En `pageshow` con
     `persisted` se deshace. **No** se usa `disabled`: un botón deshabilitado durante el
     envío deja de mandar su `name`/`value`.
  4. **`data-busy`** (un atributo, sin cambio de aspecto ni de clase) en los POST sin
     `form.form` donde un doble toque hace daño (R2-07):
     - «Sincronizar ahora» (`strava.html:27`): el POST más lento (hasta `REQUEST_SECONDS`
       = 25 s) y hasta `SYNC_MAX_CALLS` = 14 peticiones a Strava (`strava_sync.py:68-80`).
       `sync_now` sólo toma el cerrojo para escribir, así que dos toques lanzan dos
       sincronizaciones y gastan cuota dos veces;
     - «Continuar importación» de Strava (`history_run.html:3`): un segundo envío no
       duplica salidas, pero vuelve a llamar a Strava (`ensure_account` y la misma
       página) antes de ver, bajo el cerrojo, que el cursor ya avanzó
       (`strava_sync.py:555-576`);
     - los atajos de posponer (`snooze.html:32`, `form.presets`): un segundo toque cierra
       el aplazamiento recién creado y abre otro igual (`snoozes.py:68-71`), y deja en el
       historial uno de milisegundos.
- **Descartadas:**
  - comprobar la fecha en el cliente: duplicaría la regla del servidor;
  - una página de confirmación intermedia: un paso más para algo que se puede
    reactivar.
- **Textos:**
  - «Se cerrará su montaje actual: en Gravel desde el 12 ene 2026, 9:00.» (o «sobre
    Rueda trasera gravel desde el …»);
  - sin montaje: «No está montado: no se cierra ningún montaje.»;
  - con historia: «Tiene que ser posterior al 12 ene 2026, 9:00: antes choca con su
    historial de montajes.»;
  - con `with_parts` y un límite de dentro más tardío: «Si retiras también lo que lleva
    montado, posterior al 3 feb 2026, 18:00.»;
  - se mantiene «El historial permanece disponible.»;
  - en el botón: «Guardando…».
- **Pruebas nuevas (fallan hoy):**
  - `test_retiring_names_the_mount_it_closes`, para un objeto montado en bici, uno
    anidado y uno suelto;
  - `test_retiring_states_the_earliest_instant` (con montajes cerrados que terminan
    después de abrirse otros; con un único montaje abierto);
  - `test_the_limit_counts_what_goes_inside`: una pieza de segundo nivel montada
    después del límite propio del padre. Con `with_parts` ofrecido, la página da el
    límite más tardío, y un POST con `with_parts` marcado y un instante entre los dos
    límites se rechaza con el error de siempre;
  - `test_the_preview_survives_a_rejected_post` (POST con instante anterior al límite:
    400 o 200 con el error español de siempre y la misma explicación);
  - `test_a_bike_lists_nothing_of_its_own` (la bici dice que no tiene montaje propio;
    sus piezas siguen en la ayuda de `with_parts`);
  - `test_slow_or_repeating_posts_are_marked_busy`: en la página de Strava (con cuenta y
    dueño), en la de un trabajo de Strava en pausa y en Posponer, el formulario de
    «Sincronizar ahora», el de «Continuar importación» y el de los atajos llevan
    `data-busy`; el de «Cancelar trabajo», no.
- **Guardas (pasan hoy):**
  - sin historia, ninguna frase de límite;
  - `test_the_busy_state_never_disables_the_submitter`, estática, en
    `tests_ui_guards.py` (`garage.js` no asigna `disabled` a botones de envío). Para el
    JS no hay ejecutor de pruebas en el repositorio: el comportamiento se verifica con
    CDP (§8). Sigue siendo el único `<script>`, con `defer` (`tests_mobile_shell.py`).
- **Llamadores:** `views.retire` (`views.py:264-292`); `retire_with_parts`, `retire_one`
  y `mounted_in` (`retirement.py`); `_scope` (`parts.py`); `_close_for_retirement`, sólo
  desde `ownership.update_inventory`. Los `form.form` con `method=post` (grep de las
  plantillas) están en `form.html`, `lifespan.html`, `strava.html:35,53,65`,
  `history_run.html:5`, `history_execute.html`, `history_preview.html`,
  `photo_form.html`, `snooze.html`, `source_merge.html`, `usage_ride.html` y
  `more.html` (el de tema, que se excluye). Todos ganan el estado ocupado. Con
  `data-busy`: `strava.html:27`, `history_run.html:3` y `snooze.html:32`. Los POST sin
  `form.form` salen de `grep -n '<form' garage/templates/garage/*.html | grep -i post`.
- **Riesgos:**
  - el límite se calcula al abrir la página: si otra pestaña cambia el historial,
    manda el servidor;
  - «Guardando…» con una respuesta 400 que vuelve a pintar la página no deja nada
    pegado, porque es otra carga;
  - «Continuar importación» de Strava (`history_run.html:3`) no lleva la clase `form`.
    La ronda 1 la dejaba fuera porque un segundo envío no duplica salidas (el cursor se
    comprueba bajo el cerrojo, `strava_sync.py:575-578`). Pero sí gasta cuota de Strava:
    ahora lleva `data-busy` (R2-07);
  - **se quedan fuera, con su motivo,** los demás POST sin `form.form`: Reactivar
    (`item_detail.html:95`, `bike_detail.html:80`; reactivar algo ya activo no cambia
    nada, `ownership.py:224-225`), Eliminar (`form.html:27`, `photo_list.html:7`),
    «Quitar vida útil» (`lifespan.html:32`), «Dejar de posponer» (`snooze.html:25`),
    «Quitar» una excepción y «No es un duplicado» (`usage_ride.html:29`, `:45`),
    «Cancelar trabajo» (`history_run.html:3`, `:5`), «Crear las categorías habituales»
    (`_starter.html:4`: se salta las que ya existen bajo el cerrojo, `categories.py:112`)
    y «Cerrar sesión» (`more.html:25`). Son acciones de un paso, sin llamada a Strava, y
    un segundo envío no crea un registro nuevo: como mucho, lo rechaza o no hace nada. El
    formulario de revisión de una salida (`ride_review.html:16`) tiene su propio JS
    (`data-review`) y tampoco se toca.

### F05 · Registrar lectura en bruto; lecturas en inglés en la ficha

- **Estado: sigue.** Visto en la demo (Registrar lectura de Cadena 11v):
  - «Valor (metros, segundos o salidas)», un `input type=number` con `step=0.001`;
  - métricas «Distancia (metros)» y «Movimiento (segundos)»;
  - «Item» y «Service event» (F07);
  - opciones de intervención con el instante ISO en UTC: «Lubricación: Cadena 11v ·
    2026-10-25T19:00:00+00:00» (`models.py:263-264`, `:290-291`).

  En la ficha (`item_detail.html:101`):
  - `get_metric_display` y `get_scope_display` dan «Moving time (seconds)» y «Lifetime»
    (`models.py:481-489`);
  - `{{ reading.value }}` sale en bruto, «298800.000»;
  - `{{ reading.source }}` sale como «manual».

  Lo mismo en `service_event.html:23` (métrica) y en `statistics_metrics.html:3`
  (ámbito y procedencia). La demo no tiene lecturas: el texto de la ficha se comprobó
  pintando el mismo marcado.
- **Recomendada (D15):**
  1. **Una sola fuente de las palabras**, en `presentation.py`:
     - métricas: «Distancia», «Tiempo en movimiento», «Salidas»;
     - ámbitos: «Toda la vida», «Desde mi adquisición», «Desde una intervención
       concreta»;
     - procedencias: «Lectura manual propia», «Lectura manual de Garmin»; otra
       procedencia, tal cual.

     `web_forms.py:32-34` (`SCOPES`, `METRICS`, `SOURCE_CHOICES`) pasa a construirse
     desde ahí. **Este traslado es el bloque B9a**: mueve las tres listas con sus textos
     de hoy, sin cambiar nada visible y sin tocar pruebas. Lo demás es B9b. Las
     métricas del formulario llevan la unidad: «Distancia (km)», «Tiempo en movimiento
     (horas)», «Salidas».
  2. `BaselineWebForm` gana el campo **`amount`**, un `DecimalInput` con coma decimal,
     **en km, horas o salidas**. Se guarda multiplicado por 1000, 3600 o 1 y validado
     con `exact_usage_value`. Es el patrón de `MaintenanceRuleWebForm`
     (`maintenance_forms.py:298-418`: `UNITS`, `_shown`, `keep_exact`):
     - si se envía `value` (exacto) sin `amount`, se sigue aceptando como hoy;
     - al corregir, `amount` se precarga si la conversión es exacta con 6 decimales como
       mucho. Si no, se muestra el campo exacto con la etiqueta «Valor exacto (metros o
       segundos)».
  3. **Intervención:** la etiqueta de la opción es «{tipo} · {fecha y hora local}»
     (`datetime_text`), y la opción vacía, «—».
  4. **Ficha, intervención y estadísticas:** filtros nuevos en `garage_ui.py`
     (`reading_metric`, `reading_value`, `reading_scope` y `reading_source`). El valor
     usa `km`, `hours` o `num`, con «≈» si es estimada.
- **Descartadas:**
  - cambiar el significado de `value` a km u horas: un formulario abierto antes del
    cambio y enviado después guardaría 298 800 h;
  - cambiar los `choices` del modelo: migración;
  - un campo por métrica, como «Material usado»: aquí una lectura es una sola métrica.
- **Textos:**
  - campo: «Valor», con la ayuda «En km, horas o salidas, según la métrica. Con coma
    decimal: 83,5. Cero es una lectura conocida.»;
  - error de salidas: «Las salidas son un número entero.»;
  - error de precisión: «Ese tiempo no se puede guardar exacto (milisegundos): usa menos
    decimales.» (el de `UNITS`);
  - Intervención: «Intervención», con la ayuda «Sólo para «Desde una intervención
    concreta».»;
  - ficha: título «Tiempo en movimiento», línea «83 h · Toda la vida · 1 ene 2026,
    1:00», y «Procedencia: Lectura manual propia».
- **Pruebas nuevas (fallan hoy):**
  - `test_a_reading_is_written_in_km_hours_or_rides` («83» h → 298 800 s; «2.840,5» km
    → 2 840 500 m; «12» salidas → 12);
  - `test_a_fraction_of_a_ride_is_refused`;
  - `test_an_inexact_time_is_refused`;
  - `test_correcting_shows_km_or_hours_when_exact` y
    `test_correcting_an_inexact_value_keeps_the_exact_field` (con la etiqueta «Valor
    exacto (metros o segundos)»);
  - `test_intervention_options_show_the_local_date` (sin `+00:00`);
  - `test_the_item_page_shows_readings_in_spanish` (ni «Lifetime», ni «Moving time», ni
    «298800.000»);
  - `test_the_intervention_and_statistics_pages_name_the_metric_and_scope_in_spanish`.

  Casos límite: cero conocido («0 km»); el valor máximo admitido; una procedencia
  desconocida (se muestra tal cual, escapada); una lectura estimada («≈»).
- **Guardas (pasan hoy):** `test_the_exact_value_is_still_accepted` (POST antiguo con
  `value`). En B9a, la suite entera sin tocar ninguna prueba es la guarda del traslado.
- **Llamadores:**
  - `BaselineWebForm`: `views.baseline_edit` (`views.py:388-405`);
  - `SCOPES`: `UsedItemWebForm` (`web_forms.py:147`) y `BaselineWebForm`
    (`web_forms.py:328`); `METRICS`: sólo `BaselineWebForm` (`web_forms.py:330`);
    `SOURCE_CHOICES`: sólo `UsedItemWebForm` (`web_forms.py:149`). La `source` de
    `BaselineWebForm` es el `CharField` libre del modelo;
  - `get_metric_display` y `get_scope_display` en plantillas: `item_detail.html:101`,
    `service_event.html:23` y `statistics_metrics.html:3`.
- **Riesgos:** las pruebas que fijen `Distancia (metros)` o `Movimiento (segundos)` se
  actualizan con el cambio. No hay ninguna en las rutas buscadas, pero se repasa con
  grep en el bloque.

### F06 · «Sustitución» en Nueva regla convierte la regla en vida útil

- **Estado: sigue.**
  - `is_life` (`lifespan.py:23-25`): una regla de objeto del tipo «Sustitución» es su
    vida útil y se muestra como «Vida útil».
  - El selector «Tipo» de Nueva regla dice sólo «Sustitución» (demo).
  - Al guardar no hay mensaje (F08).
- **Recomendada (D8):**
  - en `MaintenanceRuleWebForm`, la etiqueta de la opción cuyo nombre coincide con
    `LIFE_TYPE` con **la misma regla que `is_life`** (`strip()` y minúsculas,
    `lifespan.py:25`) pasa a ser «Sustitución (en un objeto, es su vida útil)». La
    comparación sale de una sola función, para que la etiqueta y `is_life` no se
    separen;
  - al guardar una regla de objeto con ese tipo, el mensaje de F08 lo dice;
  - el valor enviado no cambia.
- **Descartadas:**
  - impedirlo y mandar a «Vida útil»: quitaría un camino que funciona;
  - una ayuda fija bajo «Tipo»: ruido para el resto de tipos.
- **Textos:** opción «Sustitución (en un objeto, es su vida útil)»; mensaje «Guardada
  como vida útil de {objeto}: se ve como «Vida útil» en su ficha.»
- **Pruebas nuevas (fallan hoy):**
  - `test_the_life_type_option_says_it_is_the_useful_life`;
  - `test_saving_a_life_rule_says_so`;
  - `test_a_type_named_in_other_case_or_spacing_counts` («sustitución» y
    « Sustitución », con espacios alrededor).
- **Guardas (pasan hoy):** `test_a_bike_rule_of_that_type_is_ordinary` (sin el mensaje
  de vida útil).
- **Llamadores:** `MaintenanceRuleWebForm` (`maintenance_views.KINDS`); `LIFE_TYPE` e
  `is_life` (`lifespan.py`, `garage_ui.rule_name`, `maintenance_views._together`).
- **Riesgos:** ninguno de datos.

### F07 · Etiquetas y errores en inglés

- **Estado: sigue, y es más amplio.** Visto en la demo:
  - Nuevo tipo de intervención: «Name» y «Notes». `ServiceTypeForm` no tiene
    `labels` (`maintenance_forms.py:237-242`).
  - Registrar lectura: «Item» y «Service event». `LABELS` no los tiene
    (`web_forms.py:23-31`).
  - Montar con solape: «This item is already installed during this period.»
    (`installations.py:19-23`). El ciclo y la posición ocupada van igual
    (`installations.py:20-22`, `:97`).
  - Crear categoría sin nombre: «This field is required.» y «Enter a nonempty name.».
    Los formularios de inventario no usan `SpanishWebMixin` (`LANGUAGE_CODE` es
    `en-us`).
  - **Ni siquiera `SpanishWebMixin` basta** (reproducido en un shell con
    `settings_test`, sin guardar nada):
    - `FIELD_MESSAGES` (`maintenance_forms.py:37-39`) no tiene los códigos de
      `DecimalValidator` (`max_decimal_places`, `max_digits`, `max_whole_digits`). Un
      formulario con el mixin y el campo de precio del modelo, con un precio de tres
      decimales, da «Ensure that there are no more than 2 decimal places.». Pasa en
      Crear material (Precio). **El valor de Registrar lectura no pasa por ahí** (R2-04):
      `ExactUsageDecimalField.to_python` (`forms.py:171-174`) llama a
      `exact_usage_value` antes de los validadores, así que con cuatro decimales da «The
      value must be exactly representable with three decimal places.», y con 18 cifras
      enteras, «Enter a finite nonnegative value within the supported range.»
      (reproducidos en un shell); el `DecimalValidator` nunca llega;
    - `INVALID` (`maintenance_forms.py:41-42`) sólo cubre `DecimalField`, `IntegerField`
      y `DateTimeField`: un `DateField` inválido da «Enter a valid date.». Le pasa a
      «Fecha de compra» y ya hoy a `StravaImportForm.after`, que tiene el mixin. Un
      `CharField` con un carácter nulo da «Null characters are not allowed.»
      (reproducidos en un shell, R2-01);
    - quedan en inglés mensajes de montajes que los formularios web pueden mostrar
      (R2-01: los dos primeros, reproducidos por la crítica en la demo 8769 con POST
      rechazados que no guardaron nada; todos, confirmados en el código):
      - Reemplazar o Transferir con un «Instante del cambio» fuera del montaje que sale:
        «Choose an instant strictly inside the outgoing installation.»
        (`installations.py:161`, código `invalid_transition`). Sale como error general
        porque `show_errors` (`views.py:28-33`) manda a `None` el campo `started_at`,
        que esos formularios no tienen;
      - Montar con una «Posición exclusiva» que no es una clave (por ejemplo, con
        mayúsculas y un espacio): «Use a lowercase ASCII position key.»
        (`installations.py:77`, `invalid_slot`). `InstallationWebForm` y
        `TransferWebForm` no tienen `clean_slot`; `PartWebForm` sí, y en español
        (`part_forms.py:35-38`);
      - Desmontar un período que otra pestaña ya cerró: «This installation is already
        closed; edit it explicitly to correct history.» (`installations.py:142`,
        `installation_closed`, también al campo `ended_at`, que el formulario no tiene);
      - Editar material moviendo el inicio del uso desde adquisición con lecturas «Desde
        mi adquisición»: «Correct acquisition readings before removing their anchor.» y
        «The acquisition anchor cannot follow an existing acquisition reading.»
        (`baselines.py:136`, `:138`);
    - **un error del servicio al guardar se pinta dos veces** (R2-01). Reproducido en un
      shell con un formulario de categoría válido y el error de nombre repetido, sin
      llamar al servicio: `OwnedInventoryForm.save` lo añade con `_update_errors`
      (`forms.py:93-96`) y la vista lo vuelve a añadir con `show_errors`
      (`views.py:248`). Resultado: `{'name': [«You already have…», «You already have…»]}`.
      Le pasa a todo error que el servicio lance al guardar inventario (el ancla de
      adquisición de arriba, una carrera con otra pestaña) y a las lecturas
      (`forms.py:228-231`, `views.py:399`);
    - **y uno falso.** Visto al reproducir R2-01 en la demo 8769: crear una categoría con
      un nombre que ya existe muestra «You already have a category with this name.» **y**
      «Enter a nonempty name.». El conflicto sale en `OwnedInventoryForm.clean`
      (`validate_category_name`), que quita `name` de `cleaned_data`; `_post_clean` crea
      entonces la instancia sin nombre y `Category.clean` (`models.py:71`) se queja de un
      nombre vacío que nadie escribió. Con el mixin sería «Ya tienes una categoría con
      ese nombre.» seguido de «Escribe un nombre.»;
    - quedan en inglés mensajes del modelo de lecturas: «Only service readings require
      an intervention.» (`models.py:552`), «Choose an intervention on this own item.»
      (`:556`) y «The reading cannot precede the intervention.» (`:558`); y de
      `validators.py:36-49`: «The number of rides must be an integer.», «The value must
      be exactly representable with three decimal places.» y «Enter a finite
      nonnegative value within the supported range.»;
    - `UsedItemWebForm` crea sus campos `previous_*` después de `super().__init__()`
      (`web_forms.py:140-151`). Con el mixin en `ItemWebForm`, `spanish_fields` correría
      antes de que existan, y seguirían con «Enter a number.».
- **Recomendada (D4):**
  - etiquetas: «Nombre» y «Notas» en el tipo; «Objeto» e «Intervención» en la lectura;
  - `SpanishWebMixin` en `CategoryWebForm`, `BikeWebForm`, `ItemWebForm`,
    `UsedItemWebForm`, `TemporalActionForm` y sus hijas, `InstallationWebForm` y
    `BaselineWebForm`. Se importa de `maintenance_forms`, como ya hace
    `strava_forms.py:7`;
  - entradas nuevas en `SPANISH` para los mensajes que esas páginas pueden mostrar:
    solape, posición ocupada, ciclo, «exactamente un destino», «no puede contenerse», fin
    anterior al inicio, montaje fuera de la retirada, nombre vacío, categoría repetida,
    precio sin moneda, «elige uno de tus…», los de lecturas (procedencia, antes de la
    adquisición, confirmar adquisición, lectura repetida, intervención y ámbito), los
    de `exact_usage_value` y, de R2-01, los de montajes (`invalid_transition`,
    `invalid_slot`, `installation_closed`) y los dos del ancla de adquisición. `SPANISH`
    va por el texto del mensaje, como hoy; el código no cambia;
  - `installation_action` (`views.py:330-385`) pasa los errores del servicio en
    `started_at` y `ended_at` al campo `at` antes de `show_errors`, como ya hace
    `usage_views.py:50-52` con `started_at`. Así el error de un instante fuera del
    montaje sale junto a «Instante del cambio» y no como error general;
  - `FIELD_MESSAGES` gana `max_decimal_places`, `max_digits`, `max_whole_digits` y
    `null_characters_not_allowed`. `Field.run_validators` sustituye el mensaje de un
    validador por el de `error_messages` con el mismo código y conserva sus parámetros,
    así que `%(max)s` funciona;
  - `INVALID` gana `(forms.DateField, "Introduce una fecha válida.")`. `DateTimeField` no
    hereda de `DateField`, así que el orden de la tupla no cambia nada;
  - **un error, una vez** (R2-01):
    - `show_errors` no añade un error que el formulario ya muestra en ese campo (mismo
      código y mismo texto, comparado después de traducir). Es el caso del camino de
      guardado de inventario y lecturas, que ya lo añadió con `_update_errors`. No se
      quita `_update_errors` de `save`: su comentario dice que deja la carrera visible
      también para otros llamadores;
    - en `OwnedInventoryForm`, un error de `Model.clean` no se añade a un campo que ya
      tiene un error del propio formulario: ese campo se validó vacío porque su valor no
      llegó a la instancia. Así, un nombre repetido dice sólo «Ya tienes una categoría con
      ese nombre.»;
  - `UsedItemWebForm.__init__` llama a `spanish_fields(self)` al final, tras crear sus
    campos. Es la regla general: todo `__init__` que cree campos después de
    `super().__init__()` lo hace, como ya `lifespan_forms.py:83` y
    `snooze_forms.py:65`.
- **Descartadas:**
  - `LANGUAGE_CODE = "es"`: cambiaría el legado de Stravagancia y el admin;
  - traducir en los modelos: son mensajes del dominio que también ve el admin.
- **Textos** (inglés → español):
  - «This item is already installed during this period.» → «Este objeto ya está
    montado en ese período.»;
  - «This position is occupied during this period.» → «Esa posición ya está ocupada en
    ese período.»;
  - «These installations form a cycle during a common period.» → «Esos montajes forman
    un ciclo en un período común.»;
  - «Choose exactly one destination.» → «Elige exactamente una bici o un objeto de
    destino.»;
  - «An item cannot contain itself.» → «Un objeto no puede ir montado dentro de sí
    mismo.»;
  - «The end must be later than the start.» → «El final debe ser posterior al inicio.»;
  - «The installation must finish by this resource's retirement.» → «El montaje debe
    terminar antes de que se retire.»;
  - «The installation overlaps recorded inactivity.» → «El montaje coincide con un
    período en el que estaba retirado.»;
  - «Enter a nonempty name.» → «Escribe un nombre.»;
  - «You already have a category with this name.» → «Ya tienes una categoría con ese
    nombre.»;
  - «Enter both a purchase amount and its currency, or neither.» → «Indica precio y
    moneda, o ninguno de los dos.»;
  - «Choose one of your own categories.» / «… items.» → «Elige una de tus categorías.»
    / «Elige uno de tus objetos.»;
  - «Declare the reading's source.» → «Indica la procedencia de la lectura.»;
  - «The reading cannot precede acquisition.» → «La lectura no puede ser anterior a la
    adquisición.»;
  - «Confirm the acquisition instant before recording this scope.» → «Confirma antes el
    inicio de la adquisición para este ámbito.»;
  - la restricción de lectura repetida → «Ya hay una lectura de esa métrica y ámbito en
    ese instante: corrígela.»;
  - «Only service readings require an intervention.» → «La intervención va con el
    ámbito «Desde una intervención concreta», y sólo con él.»;
  - «Choose an intervention on this own item.» → «Elige una intervención de este mismo
    objeto.»;
  - «The reading cannot precede the intervention.» → «La lectura no puede ser anterior
    a la intervención.»;
  - «The number of rides must be an integer.» → «Las salidas son un número entero.»;
  - «The value must be exactly representable with three decimal places.» → «El valor
    exacto admite como máximo 3 decimales.»;
  - «Enter a finite nonnegative value within the supported range.» → «Escribe un valor
    positivo o cero, dentro del máximo admitido.»;
  - «Choose an instant strictly inside the outgoing installation.» → «El cambio tiene que
    caer dentro del montaje actual: después de su inicio y, si tiene final, antes de
    él.»;
  - «Use a lowercase ASCII position key.» → «Usa minúsculas, números y guion bajo, por
    ejemplo rear_wheel.» (el texto de `part_forms.clean_slot`, con el ejemplo de la
    ayuda de Montar; las claves en inglés son una decisión abierta de Anillos, §7, y no
    cambian);
  - «This installation is already closed; edit it explicitly to correct history.» →
    «Ese montaje ya está cerrado: corrígelo con «Editar período».»;
  - «Correct acquisition readings before removing their anchor.» → «Hay lecturas «Desde
    mi adquisición»: corrígelas antes de quitar este inicio.»;
  - «The acquisition anchor cannot follow an existing acquisition reading.» → «El inicio
    del uso desde adquisición no puede ser posterior a una lectura «Desde mi
    adquisición» ya registrada.».

  Mensajes de campo, por `spanish_fields`: los de hoy (obligatorio, número…) y
  `max_decimal_places` → «Como máximo %(max)s decimales.», `max_digits` → «Como máximo
  %(max)s cifras.», `max_whole_digits` → «Como máximo %(max)s cifras antes de la coma.»,
  `null_characters_not_allowed` → «No se admiten caracteres nulos.»; `invalid` de un
  `DateField` → «Introduce una fecha válida.».
- **Pruebas nuevas (fallan hoy):**
  - `test_service_type_labels_are_spanish`;
  - `test_reading_labels_are_spanish`;
  - `test_an_overlapping_mount_says_so_in_spanish`;
  - `test_a_cycle_says_so_in_spanish`;
  - `test_an_occupied_position_says_so_in_spanish`;
  - `test_an_empty_category_name_says_so_in_spanish` («Este campo es obligatorio.», sin
    «Escribe un nombre.» al lado: hoy salen los dos, por la misma causa que el falso de
    R2-01);
  - `test_a_repeated_category_says_so_in_spanish` (sólo «Ya tienes una categoría con ese
    nombre.»);
  - `test_a_price_without_currency_says_so_in_spanish`;
  - `test_too_many_decimals_say_so_in_spanish`: precio con tres decimales en Crear
    material → «Como máximo 2 decimales.» (código de `DecimalValidator`); valor con
    cuatro decimales en Registrar lectura → «El valor exacto admite como máximo 3
    decimales.» (el de `exact_usage_value`, no el del validador: R2-04); valor con 18
    cifras enteras → «Escribe un valor positivo o cero, dentro del máximo admitido.»;
  - `test_reading_errors_are_spanish` (procedencia vacía; ámbito «Desde una
    intervención concreta» sin intervención; intervención con otro ámbito; lectura
    anterior a su intervención; salidas fraccionarias por el valor exacto);
  - `test_previous_readings_say_so_in_spanish` (texto no numérico en «Kilómetros previos
    conocidos» de Crear material usado);
  - `test_mount_errors_are_spanish` (R2-01): Reemplazar y Transferir con un instante
    anterior al inicio del montaje que sale (el error, junto a «Instante del cambio»);
    Montar con «Posición exclusiva» = «Rueda X»; Desmontar un período ya cerrado por
    otra pestaña. Ninguno guarda nada;
  - `test_dates_and_null_characters_say_so_in_spanish`: una fecha de compra inválida en
    Crear material, una fecha inválida en «Importar histórico desde» y un carácter nulo
    en Notas;
  - `test_acquisition_anchor_errors_are_spanish`: Editar material moviendo el inicio del
    uso desde adquisición detrás de una lectura «Desde mi adquisición», y quitándolo con
    lecturas;
  - `test_each_error_is_shown_once` (R2-01): el caso anterior del ancla (un error del
    servicio al guardar) y un nombre de categoría repetido muestran cada mensaje **una
    sola vez**, y el repetido no muestra «Escribe un nombre.»;
  - `test_no_web_form_page_shows_a_known_english_message`, que envía cada caso anterior
    y busca los textos ingleses de la lista, más «Ensure that», «Enter a number»,
    «Enter a valid date», «Null characters», «position key», «strictly inside»,
    «already closed» y «acquisition anchor».
- **Llamadores:** las clases citadas (`views.KINDS`, `views.retire`,
  `views.installation_*`, `views.baseline_edit`, `parts_views.part_create`);
  `SpanishWebMixin` ya lo usan `maintenance_forms.py` y `strava_forms.py`;
  `spanish_fields` y `FIELD_MESSAGES`, también `lifespan_forms.py` y
  `snooze_forms.py`, que heredan los códigos nuevos sin cambio. `show_errors` tiene 17
  llamadas en `views.py`, `history_views.py`, `strava_views.py` y `usage_views.py`: no
  repetir un error no cambia ninguna de ellas cuando el error no estaba ya.
- **Riesgos:**
  - `SpanishWebMixin.add_error` también traduce los errores que entran por
    `_update_errors` y `show_errors`. Es lo buscado; se comprueba que no cambia códigos
    de error;
  - un `DateField` con su propio mensaje de `invalid` lo conserva (`spanish_fields` sólo
    sustituye los mensajes por defecto);
  - el admin no usa estos formularios.

### F08 · Sin mensaje al guardar tipo, regla e intervención

- **Estado: sigue.** `maintenance_edit` redirige sin `messages.success`
  (`maintenance_views.py:166-168`). Sólo hay mensaje cuando la misma visita registra
  otras («Registradas también: …»). Categorías, bicis, material y lecturas sí lo tienen
  (`views.py:250`, `:401`).
- **Recomendada (D7):** un mensaje por tipo de objeto, también al editar:
  - «Tipo de intervención guardado.»;
  - «Regla guardada.» (con vida útil, el texto de F06);
  - «Intervención guardada.», seguido de « Registradas también: …» si las hay, en un
    solo mensaje.
- **Descartadas:** «Guardado correctamente.» para todo: no dice qué.
- **Pruebas nuevas (fallan hoy):** `test_saving_a_service_type_confirms_it`,
  `test_saving_a_rule_confirms_it` y `test_saving_an_intervention_confirms_it`, en
  creación y en edición; `test_one_message_with_the_others_registered` («Intervención
  guardada. Registradas también: …», un solo mensaje).
- **Guardas (pasan hoy):** una intervención **rechazada** no deja mensaje.
- **Llamadores:** `maintenance_views.maintenance_edit` y `_together_message`.
- **Riesgos:** ninguno.

### F09 · Títulos en plural, «---------», Categoría al final

- **Estado: sigue.** Visto en la demo:
  - títulos: «Crear categorías», «Crear bicis» y también **«Editar bicis»**
    (`views.py:257`: `label.lower()` de `KINDS`, que es plural);
  - «---------» en Montar (Bici y Objeto de destino), Registrar lectura (Objeto e
    Intervención), Transferir, Crear material (Categoría) y Reemplazar (Objeto
    entrante, `web_forms.py:253`). Fuera de los formularios de alta, también en el
    filtro de Estadísticas (Bici, Categoría y Objeto, `statistics_forms.py:10-12`: tres
    en la demo) y en «Excepción» de una salida (`usage_forms.py:96`, Objeto);
  - en Crear material, Categoría va la última, detrás de Moneda (`forms.py:116`).
- **Recomendada (D5):**
  - un nombre singular por clase en `views.py` («bici», «material», «categoría») para
    «Crear …» y «Editar …»;
  - `empty_label="—"` en los selectores de destino (Montar y Transferir), en Objeto e
    Intervención de Registrar lectura y en Objeto de la excepción de una salida; «Elige
    un objeto» en Objeto entrante de Reemplazar, que es obligatorio; y «Elige una
    categoría» en Categoría, como el «Elige un tipo» de `maintenance_forms.py:200`;
  - el filtro de Estadísticas **entra**: «Todas» en Bici y Categoría, «Todos» en Objeto,
    porque ahí vacío significa «sin filtro»;
  - `order_fields` con Categoría tras Nombre en `ItemWebForm` y `UsedItemWebForm`.
- **Pruebas nuevas (fallan hoy):**
  - `test_create_and_edit_titles_are_singular` (`<h1>` y `<title>`, las tres clases);
  - `test_no_django_empty_option_is_shown`: ninguna de estas páginas contiene
    «---------»: Crear material, Crear material usado, Montar, Transferir, Reemplazar,
    Registrar lectura, Nueva regla, Registrar mantenimiento, Estadísticas y la ficha de
    una salida (excepciones);
  - `test_statistics_filters_say_all` («Todas» y «Todos» como opción vacía);
  - `test_category_comes_right_after_the_name`.
- **Llamadores:** `views.inventory_edit`; los formularios de F02; `ItemWebForm` y
  `UsedItemWebForm` (`views.KINDS`, `urls.py:30`); `StatisticsForm`
  (`statistics_views.py:83,101`); `OverrideWebForm` (`usage_views.py`).
- **Riesgos:** ninguno.

### F10 · Orden alfabético sensible a acentos y mayúsculas

- **Estado: sigue.**
  - Las bases locales usan la intercalación `C` (consultado en la demo 047). Con
    valores literales, `ORDER BY` da «Cubierta < Cámara < Zapatillas < absoluteBLACK <
    Ébano».
  - Con `COLLATE "es-x-icu"` da «absoluteBLACK < Cámara < Cubierta < Ébano < Nube <
    Ñandú < Zapatillas».
  - En memoria, `name.lower()` (`home.py:134`) también pone «Cámara» detrás de
    «Cubierta».
  - **ICU no es «sin mayúsculas ni acentos y ñ tras n».** Comprobado con valores
    literales en el clúster local de pruebas (que tiene `es-x-icu`, como la demo): ICU
    desempata por acento y mayúscula antes que por nada más («camara < Camara <
    Cámara», «sram gx < Sram GX < SRAM GX») y ordena la puntuación a su manera
    («Rueda (x) < Rueda x < Rueda_x < Rueda-x < Rueda1 < Ruedax»). Una clave Python que
    quite mayúsculas y acentos y ponga la ñ tras la n empata las tres «camara» (decide
    el `pk`) y da «Rueda (x) < Rueda x < Rueda-x < Rueda1 < Rueda_x < Ruedax». Con
    nombres repetidos en mayúsculas distintas, justo el caso de F02, el orden en
    memoria y la numeración «(2)», «(3)» no coincidirían con la lista de Material.
- **Recomendada (D9):** un módulo `garage/ordering.py` con:
  - `by_name(queryset, field="name")` → `order_by(Collate(field, "es-x-icu"), "pk")`;
  - **regla para lo que se ordena en memoria:** si la lista sale de una consulta, esa
    consulta usa `by_name`, y en Python sólo se aplican ordenaciones **estables** por
    otras claves (por ejemplo, `gear.sort(key=lambda e: not e.in_use)` sobre `loose`,
    que sale de `all_items` ya ordenado), o se ordena por la posición en esa consulta
    (`rank = {obj.pk: i for i, obj in enumerate(ordered)}`), sin consultas nuevas;
  - `name_key(text)`, sólo donde no hay una consulta ordenada a mano. Es una
    **aproximación documentada**: mayúsculas y acentos no cuentan, la «ñ» va tras la
    «n», y los empates van por `pk`. Coincide con ICU en nombres que difieren en sus
    letras base, **si esas letras son a–z, «ñ» o letras que Unicode descompone en base
    más acento** (B4-R1-01, §10.1: ø, ł, æ, œ, ı… van tras la «z», e ICU las pone junto a
    o, l, «ae», «oe»; no se copia ICU, D9); en los que sólo difieren en mayúsculas,
    acentos o puntuación, no (ICU desempata por ellos, y `name_key` por `pk`).

  Se aplica a:
  - la lista de Material, Bicis y Categorías (`views.py:77`);
  - los `queryset` de los selectores de bici, objeto, categoría y tipo (formularios de
    F02 y F09, `forms.py:59`, `:191`, `strava_forms.py:30`, `parts.py:171`,
    `statistics_forms.py:21`, `history_forms.py:86,94`, `usage_forms.py`);
  - Inicio (`home.py:98`, `:103`; `:134` pasa a una ordenación estable por «en uso»);
  - las ordenaciones secundarias de estadísticas, revisión de salidas, Taller, uso y
    piezas: `statistics_views.py:111-114`, `services/statistics.py:171-172`,
    `ride_review.py:177`, `:226-232`, `workshop.py:55` (hoy `Lower("name")`), `:64-65`,
    `maintenance_due.py:245`, `usage_views.py:65`, `:107` (hoy por el nombre tal cual),
    `:132` (`item__name`), `service_usage.py:187`, `parts.py:53`, `:70` y
    `strava_views.py:57` (bicis de Strava). Cada una, con la regla de arriba: consulta
    con `by_name` y orden estable o por posición, o `name_key` si no hay consulta;
  - **dos ordenaciones sin `.name` ni `order_by` (R2-05):**
    - `lifecycle.py:162`: `tuple(sorted(labels))` ordena con el `sorted()` de Python las
      etiquetas `context_label(bike_name, sport_type)` de «En uso · Gravel, Carretera»,
      que salen en Material, en Inicio y en la ficha. Con «Ébano» y «Gravel» da hoy
      «Gravel, Ébano». Pasa a `sorted(labels, key=name_key)`: las etiquetas son
      compuestas («Gravel · MTB», «Cualquier bici») y no hay una consulta ordenada que
      reutilizar (ordenar la consulta por `profile__bike__name` dejaría «Cualquier bici»,
      de bici nula, al final);
    - `presentation.py:355-359`: `by_severity` desempata por `str(item.target)`, el
      nombre del objeto o la bici (`models.py:43-44`). Decide el orden de los desgastes
      con el mismo estado y la misma proporción (por ejemplo, todos los «sin datos») en
      el Taller (`workshop.py:59`), Inicio (`home.py:120`) y las fichas de pieza y de
      bici (`views.py:146`, `:152`, `:199`). Pasa a `name_key(str(item.target))`.

  **Aceptación por grep (B4):** cada `order_by(` con un campo de nombre; cada
  `.name.lower()`, `name.lower()` o clave con `.name` en una ordenación; y cada
  `sorted(`, `.sort(`, `min(` o `max(` con clave **o sin ella** sobre una colección de
  nombres, de etiquetas hechas con nombres o de `str()` de un modelo cuyo `__str__` es
  su nombre, en `garage/*.py`, `garage/services/*.py` y `garage/templatetags/*.py`,
  fuera de las pruebas, queda convertido o en una lista de
  excepciones del propio bloque, con su motivo. Se recorre la salida entera de `grep -n
  "sorted(\|\.sort(\|order_by("`, no sólo la de los patrones con `.name` (R2-05).
  Excepciones ya vistas: `categories.py:79` (normaliza para comparar nombres, no ordena),
  `maintenance_forms.py:250`, `maintenance_views.py:115` y `lifespan.py:25` (comparan
  con `LIFE_TYPE`), `review_views.py:50` (claves de bici, no nombres) y los `sorted()`
  de códigos de moneda (`models.py:105`, `:299`, `statistics.py:153`); el resto de esa
  salida ordena por fechas, `pk`, índices o claves internas, y la lista del bloque lo
  dice línea a línea. Los `queryset` que dependen de `Meta.ordering` (`models.py:55`,
  `:93`, `:239`) y se pintan como lista o selector pasan a `by_name`; los que no se
  pintan, se quedan.

  **Comprobación de sistema (R2-09).** Si la base no tiene `es-x-icu`, PostgreSQL
  responde «collation … does not exist» (reproducido con una intercalación inexistente
  en la base 047: `ProgrammingError`). Como `by_name` está en Inicio, en las listas y en
  todos los selectores, todas esas páginas darían 500, no un orden peor. Por eso B4
  añade `garage/checks.py`, registrado en `GarageConfig.ready()` (hoy Garage no registra
  ninguna comprobación):
  - recorre sólo los alias de `databases` que Django le pasa. `migrate` se los pasa
    (`get_check_kwargs`, Django 5.2) y `manage.py check --database default` también; un
    `manage.py check` sin `--database` y `runserver` no tocan la base, como hoy;
  - en cada alias PostgreSQL, consulta `pg_collation` (`collname = 'es-x-icu'`) y, si
    falta, devuelve un `Error` (`garage.E001`) con un mensaje que dice qué falta y que
    las páginas de Garage fallarían;
  - garage-023 (despliegue) añade `manage.py check --database default` a su receta, por
    si el despliegue ya no ejecuta `migrate` (§6).
- **Descartadas:**
  - `Meta.ordering`: migración;
  - la extensión `unaccent`: migración y extensión;
  - ordenar todo en Python: la lista de Material pagina en la base;
  - reimplementar ICU en Python o usar `locale.strxfrm`: lo primero es una dependencia
    (PyICU) o una copia incompleta de sus reglas; lo segundo depende de los locales
    instalados en cada máquina.
- **Pruebas nuevas (fallan hoy):**
  - `test_names_sort_as_in_spanish` (lista de Material con los siete nombres de
    arriba, y lo mismo en Bicis y Categorías);
  - `test_selects_sort_as_in_spanish`;
  - `test_home_gear_sorts_as_in_spanish`;
  - `test_case_variants_sort_the_same_everywhere`: con «sram gx», «Sram GX» y «SRAM
    GX» creados en un orden de `pk` distinto del de ICU, la lista de Material, Inicio y
    los selectores dan la misma secuencia que `by_name`;
  - `test_name_key_agrees_with_the_database_at_base_letters`: la misma secuencia con
    `by_name` y con `sorted(key=name_key)` para nombres que difieren en sus letras
    base (los siete de arriba, «nzz» y «Ñandú»);
  - `test_name_key_ties_case_variants_by_pk`: documenta la aproximación con «camara»,
    «Camara» y «Cámara»;
  - `test_pages_of_twenty_follow_the_new_order` (los 20 primeros y la página 2);
  - `test_in_use_contexts_sort_as_in_spanish` (R2-05): un objeto en dos perfiles de uso
    abiertos, de las bicis «Ébano» y «Gravel», dice «En uso · Ébano, Gravel» en
    Material, en Inicio y en su ficha;
  - `test_equal_wear_sorts_targets_as_in_spanish` (R2-05): dos objetos «Ébano» y
    «Gravel» con reglas sin datos salen en ese orden en el Taller;
  - `test_a_missing_collation_is_a_system_error` (R2-09): con la consulta a
    `pg_collation` sustituida para que no encuentre nada, la comprobación devuelve
    `garage.E001`; sin `databases`, no consulta nada.
- **Guardas (pasan hoy):** `test_equal_names_keep_a_stable_order` (empate por `pk`);
  `test_the_local_cluster_passes_the_collation_check` (`call_command("check",
  "--database", "default")` contra el clúster de pruebas, que tiene `es-x-icu`, no
  falla; hoy pasa porque aún no hay comprobación, y tiene que seguir pasando con ella).
- **Llamadores:** los de la lista. `scoped_inventory` no cambia (lo usan 100+ sitios).
- **Riesgos:**
  - **no verificable en local:** que la base de producción tenga `es-x-icu`. Neon
    compila PostgreSQL con ICU según su documentación, pero no se ha comprobado. Va en
    §6, para el despliegue (garage-023). Si falta, la comprobación de sistema lo para en
    `migrate` o en `check --database default`, antes de que las páginas den 500 (R2-09);
    no lo arregla;
  - las pruebas corren en el clúster local, que sí lo tiene (consultado en la base 047:
    `es-x-icu`, `es-ES-x-icu` y `und-x-icu`, con intercalación `C` por defecto).

### F11 · Garaje vacío dice «Todo tu material está montado.»

- **Estado: sigue.** `index.html:76-77` pinta ese texto cuando `home.gear` está vacío.
  Eso ocurre si todo está montado, pero también si no hay material, si todo está
  retirado, o si hay piezas montadas y el resto retiradas, sin ninguna suelta
  (`home.py:109-110`: `loose` excluye montadas y retiradas).
- **Recomendada (D22):** `Home` gana un dato (por ejemplo, `items_state`) calculado con
  la lista `all_items` y el conjunto `mounted` que ya existen, sin consulta extra.
  Cuatro textos, según haya material, montado y retirado (sin nada suelto):
  - sin material: «Aún no tienes material. Añadir material.» (enlace a `item-create`);
  - sólo retirado: «Todo tu material está retirado.» (enlace «Ver los retirados» a
    `?state=retired`);
  - montado y nada retirado: «Todo tu material está montado.»;
  - montado y el resto retirado: «Todo tu material activo está montado.» (con el mismo
    enlace «Ver los retirados»).

  Una retirada programada en el futuro aún no cuenta como retirada (`_retired(item,
  at)`, como hoy).
- **Pruebas nuevas (fallan hoy):** `test_an_empty_garage_offers_to_add_material`,
  `test_only_retired_material_says_so` y
  `test_mounted_and_retired_says_all_active_is_mounted`.
- **Guardas (pasan hoy):** `test_all_mounted_keeps_its_text`; sin consultas nuevas
  (presupuesto de `tests_mobile_home.py`).
- **Llamadores:** `home_snapshot` lo usan `views.index` y sus pruebas.
- **Riesgos:** ninguno.

### F12 · No se ve qué usuario tiene la sesión

- **Estado: sigue.** Más tiene «Cerrar sesión» (`more.html:25`), pero no el usuario.
- **Recomendada (D23):** dentro del botón, como las demás filas del menú:
  `<small>Has entrado como {{ user.get_username }}</small>`. El procesador de contexto
  de autenticación ya está.
- **Descartadas:** el usuario en la barra superior: ocupa sitio en todas las pantallas
  y la barra se pliega a 6 px sin botones.
- **Pruebas nuevas (fallan hoy):** `test_more_says_who_is_signed_in` (y escapado, con
  un nombre con `<`).
- **Riesgos:** ninguno.

### F13 · Placeholder «EUR» en Moneda

- **Estado: sigue.** `maintenance_forms.py:277` pone `placeholder: "EUR"`. Sin moneda
  anterior, la caja parece rellena. La ayuda ya dice «Código ISO, por ejemplo EUR.».
- **Recomendada (D6):** quitar el placeholder; nada más.
- **Pruebas nuevas (fallan hoy):** `test_currency_has_no_placeholder`, sin moneda
  previa.
- **Guardas (pasan hoy):** con moneda previa, la precarga sigue siendo la última usada.
- **Riesgos:** ninguno.

### F14 · Retirar y Montar escondidos en Detalles; tres enlaces de montar

- **Estado: sigue.** En la ficha de pieza:
  - «Retirar»/«Reactivar» y «Montar / remontar» van dentro de `<details class="more">`,
    que sale cerrado (`item_detail.html:93-104`, `:95`, `:99`);
  - con la pieza sin montar hay tres enlaces a `installation-create`: cabecera de
    Montajes (`:60`), Detalles (`:99`) y barra de acciones (`:108`);
  - montada, «Desmontar» y «Reemplazar» sólo están en Detalles, en cada período
    (`periods.html:1`);
  - en la ficha de bici, «Retirar» también está en Detalles (`bike_detail.html:80`).
- **Recomendada (D17):**
  - una tarjeta visible `section.sec.card` «Más acciones», justo antes de Detalles,
    con una fila `.actions`:
    - activa: «Retirar»;
    - retirada: «Reactivar» (el formulario POST de hoy);
    - montada: «Desmontar» y «Reemplazar» del montaje actual, y «Añadir un montaje
      pasado»;
    - retirada: «Añadir un montaje pasado»;
  - se quitan de Detalles «Montar / remontar» y la fila de Retirar/Reactivar;
  - «Registrar lectura» se queda en Detalles, pero junto a «Lecturas de uso»;
  - la bici gana la misma tarjeta con «Retirar»/«Reactivar».

  Resultado:

  | Estado de la pieza | Enlaces a montar |
  |---|---|
  | Sin montar y activa | 2: cabecera y barra, el patrón de Anillos («Registrar» + «Registrar mantenimiento») |
  | Montada | 1: «Añadir un montaje pasado» |
  | Retirada | 1: «Añadir un montaje pasado» |

  La regla de hoy para una retirada **programada** («Reactivar» si hay `retired_at`) no
  cambia. Es la decisión pendiente de garage-042 §8.
- **Descartadas:**
  - abrir Detalles por defecto: la ficha se hace enorme;
  - meterlo todo en la barra de acciones: no cabe a 320 px (ya lleva «Registrar
    mantenimiento» y «Mover»).
- **Textos:** «Más acciones», «Retirar», «Reactivar», «Desmontar», «Reemplazar»,
  «Añadir un montaje pasado».
- **Pruebas nuevas (fallan hoy):**
  - `test_retire_is_visible_without_opening_details` (fuera de `details.more`; pieza y
    bici);
  - `test_mount_links_by_state` (2, 1 y 1, como en la tabla);
  - `test_a_mounted_piece_offers_unmount_and_replace_outside_details`;
  - `test_registering_a_reading_sits_with_the_readings`.

  Hay que **ajustar** `tests_mobile_item.py:226,233` si comparan el marcado completo.
- **Guardas (pasan hoy):** presupuesto de consultas de la ficha sin cambios: ≤ 44
  suelta (`tests_lifecycle.py:393`) y ≤ 47 montada (`tests_mobile_item.py:196`).
- **Llamadores:** `item_detail.html` y `bike_detail.html` (vista
  `views.inventory_detail`); `periods.html` lo incluyen los dos.
- **Riesgos:**
  - a 320 px, una fila con tres enlaces se parte en dos líneas; cada enlace mantiene
    sus 44 px (`garage.css:536`). Se mira en las capturas;
  - es una tarjeta más en la ficha.

### F15 · Montajes sólo con fecha; horas sin zona

- **Estado: sigue.**
  - La cronología usa `local_date` (`item_detail.html:62`): «24 jun 2026 → hoy».
  - Detalles usa `local_datetime`: «24 jun 2026, 9:00 → sin final». Sale en la zona
    del navegador y no la nombra.
- **Recomendada (D18):**
  - la cronología, con `local_bound` (`garage_ui.py:283-293`): la fecha si es
    medianoche local; si no, fecha y hora;
  - una nota al pie de Montajes y otra bajo «Historial completo de montajes»: «Horas
    en la zona Europe/Madrid.» (de `user_tz`, ya en el contexto).
- **Descartadas:** poner la zona en cada línea: repite lo mismo y no cabe a 320 px.
- **Textos:** «Horas en la zona Europe/Madrid.»
- **Pruebas nuevas (fallan hoy):**
  - `test_the_timeline_shows_the_time_when_it_is_not_midnight`, con un montaje a las
    9:00 de Madrid y otro a medianoche, y la zona cambiada por la cookie;
  - `test_the_zone_of_the_times_is_named`.
- **Riesgos:** la línea de la cronología se alarga. Se mira a 320 px.

### F16 · Padre retirado: «Sin piezas montadas dentro» sin más

- **Estado: sigue.** `item_detail.html:75` dice «Sin piezas montadas dentro.» cuando no
  hay piezas ahora, aunque las hubiera antes. La historia está en Detalles, «Material
  montado sobre este objeto» (`:103`).
- **Recomendada (D19):**
  - si no hay piezas ahora pero `children` tiene períodos cerrados: «Sin piezas
    montadas ahora. Antes llevaba: {X} (hasta el {d}), {Y} (hasta el {d}).»;
  - como mucho 5 objetos distintos, los más recientes, enlazados a su ficha, y «y N más
    en Detalles» si hay más;
  - `children` pasa a ser una lista en `views.inventory_detail` (`views.py:116`), así
    que se lee una sola vez para las dos secciones;
  - sin historia, el texto de hoy, que fija `tests_parts.py:204`.
- **Pruebas nuevas (fallan hoy):**
  - `test_a_parent_without_parts_names_the_ones_it_had` (retirado y también activo);
  - `test_at_most_five_and_how_many_more`;
  - `test_a_part_that_came_back_is_listed_once`.
- **Guardas (pasan hoy):** `test_children_are_read_once` (el presupuesto de la ficha no
  sube); sin historia, el texto de hoy (`tests_parts.py:204`).
- **Riesgos:** ninguno.

### F17 · Días de una regla redondeados hacia abajo por los dos lados

- **Estado: sigue** (código).
  - `WearMetric.value_text` y `remaining_text` usan `quantity`, que para
    `calendar_days` redondea hacia abajo si no se pide `up` (`presentation.py:58-59`,
    `:156-171`).
  - Con 184,6 días de 365, salen «184 días de 365» y «180 quedan»: suman 364.
  - El aplazamiento ya redondea los días hacia arriba (`presentation.py:282-283`).
- **Recomendada (D20):** en `remaining_text`, `calendar_days` se redondea hacia arriba
  siempre. El valor transcurrido sigue hacia abajo. Así suman el umbral, como en
  ProBikeGarage («181»). La misma regla vale para el «Restante» de los detalles
  técnicos del Taller (F22): el filtro de F22 redondea hacia arriba los días que
  quedan, para que el anillo y los detalles no digan 181 y 180 de la misma regla
  (`quantity("calendar_days", 180.4)` da «180» y, con `up`, «181»).
- **Pruebas nuevas (fallan hoy):**
  - `test_days_left_and_days_gone_add_up_to_the_threshold` (184,6 de 365 → 184 y 181;
    184 exactos → 184 y 181);
  - `test_half_a_day_left_is_one_day` (364,5 → «1»);
  - `test_technical_details_round_days_left_up` (180,4 días que quedan → «181» en el
    anillo y en «Restante» de los detalles técnicos). Va en B10, que crea el filtro.
    **B12 va antes que B10** (R2-02): la cifra del anillo sale de
    `WearMetric.remaining_text` (`presentation.py:169-171`), que hasta B12 redondea los
    días hacia abajo (una regla de calendario no es una cota inferior). Con B10 antes,
    la mitad de esta prueba que mira el anillo fallaría al cerrar B10. Así, el filtro de
    B10 reutiliza la regla que B12 ya dejó en `remaining_text`, sin copiarla.
- **Guardas (pasan hoy):** `test_a_due_calendar_rule_is_unchanged` (vencida: el exceso
  no cambia).
- **Llamadores:** `remaining_text` lo usan `big`, `snooze_left` (sólo para no-días) y
  las plantillas de anillo y fila (`_ring.html`, `_wear_row.html`, `item_detail.html`);
  `display_remaining`, `maintenance_alerts.html:7`. Las pruebas de km
  (`tests_mobile_home.py:244-245`) no cambian.
- **Riesgos:** una regla puede pasar de «0» a «1» en su último día. Es lo buscado.

### F18 · «a ≥ 0 km de la anterior» sin salidas

- **Estado: sigue** (código; la demo tiene salidas). `span_short`
  (`garage_ui.py:335-341`) devuelve la parte en km aunque sea «≥ 0 km»: un mínimo de
  cero que no dice nada.
- **Recomendada (D21):** si la distancia es un mínimo (no completa, no estimada) y su
  **cifra mostrada** es «0», `span_short` devuelve los días. Se decide con el texto ya
  redondeado, no con el valor: `quantity` redondea un mínimo hacia abajo con un decimal
  por debajo de 100 (`presentation.py:60-63`), así que 0,04 km se pinta «≥ 0 km» aunque
  el valor no sea 0. Un 0 completo (una lectura que dice 0) se conserva: «a 0 km».
- **Pruebas nuevas (fallan hoy):**
  - `test_no_rides_between_shows_days`: dos intervenciones sin salidas entre ellas →
    «a 30 días de la anterior»;
  - `test_a_minimum_shown_as_zero_shows_days`: un mínimo de 0,04 km → los días; uno de
    0,1 km → «a ≥ 0,1 km».
- **Guardas (pasan hoy):**
  - `test_known_zero_km_is_kept`;
  - `test_km_are_shown_when_there_are_some` («a ≥ 47 km»).
- **Llamadores:** `span_short` en `item_detail.html:83` y `bike_detail.html:70`.
  `span_text` (pantalla de la intervención) no cambia.
- **Riesgos:** ninguno.

### F19 · Crear categoría: radio sin marcar y Guardar a un clic

- **Estado: ya resuelta / no se reproduce.**
  - El radio «Según el nombre» se pinta `checked` (`_icon_grid.html:6`); en la demo,
    `input[name=icon]:checked` es `id_icon_0`.
  - A 390×706, el punto central de «Guardar» devuelve el propio botón
    (`elementFromPoint`).
  - La nota de Beads ya sospechaba un artefacto de la herramienta.
- **Acción:** ninguna. Se vuelve a mirar en las capturas finales (§8).

### F20 · Nueva regla: «Contar desde» y umbrales bajo el pliegue y la barra

- **Estado: sigue.** Medido a 390×706 en Nueva regla:

  | Elemento | Posición |
  |---|---|
  | Barra de acciones | 540–616 px |
  | Caja de «Distancia (km)» | 541–591 px: empieza bajo la barra |
  | Calendario | 854 px |
  | Desnivel | 974 px |
  | «Contar desde» | 1114 px |
  | Documento | 1711 px |

  Cada umbral ocupa una fila entera con su ayuda.
- **Recomendada (D13):**
  - con el mismo ayudante de F01, el formulario declara filas de dos campos
    (`field_rows`): (Distancia, Tiempo) y (Salidas, Días). Se pintan con el
    `.field-row` que ya existe (`garage.css:587-591`, `lifespan.html:13`). Desnivel va
    solo;
  - si un campo falta (un valor exacto en metros), el otro va solo;
  - se quita la ayuda «Número de salidas.» (`maintenance_forms.py:323`).
- **Descartadas:**
  - una barra no fija en este formulario: rompe la regla de Anillos;
  - «Contar desde» antes de los umbrales: sigue bajo la barra (Tipo acaba en ~496 px);
  - ocultar la Bici al venir de un objeto: quita una opción.
- **Pruebas nuevas (fallan hoy):**
  - `test_rule_thresholds_go_two_by_two`;
  - `test_a_row_keeps_its_errors` (un error en Días, dentro de su fila).
- **Guardas (pasan hoy, porque aún no hay filas):** `test_an_exact_field_goes_alone`.

  **Criterio de captura:** a 390×706, la caja de «Contar desde» sube **al menos
  170 px** (hoy en 1114 px). Medido con un prototipo en el DOM de la demo 8769, con el
  `.field-row` real de `garage.css`, las filas (Distancia, Tiempo) y (Salidas, Días) y
  sin la ayuda «Número de salidas.»: la caja pasa de 1114 a 938 px (Δ = 176) y el
  documento, de 1711 a 1535 px. La primera fila mide 100 px y la segunda 121 px (la
  ayuda de Días va en dos líneas a media anchura).
- **Descartada también:** acortar «Tiempo en movimiento (horas)» a «Tiempo (horas)».
  Daría Δ = 198 px (medido), pero «en movimiento» distingue el tiempo que cuenta del
  tiempo total de la salida; no compensa 22 px.
- **Llamadores:** el ayudante de F01; `MaintenanceRuleWebForm`.
- **Riesgos:** «Tiempo en movimiento (horas)» va en dos líneas **ya a 390 px** (50 px
  de etiqueta frente a 28 px de la de Distancia) y fija el alto de la primera fila. A
  320 px, igual. `.field-row` ya alinea las cajas (`tests_ui_guards.py:351-369`).

### F21 · Página del trabajo del histórico: «¿cómo sé si falta?»; segundo trabajo

- **Estado: sigue** (código; la demo no tiene trabajos).
  - `history_run.html:2` pone el estado en medio de una línea («Strava · En pausa ·
    …»).
  - `:3` y `:5` terminan con «Un trabajo completado sólo acredita…; la completitud del
    histórico permanece desconocida».
  - La página «Histórico propio» repite la idea en su panel de cobertura:
    «Completitud del histórico: **desconocida**» (`history_index.html:18`).
  - `strava_import` (`strava_views.py:154-169`) crea siempre un trabajo nuevo, aunque
    haya otro en pausa o uno completado desde la misma fecha. No toma ningún cerrojo
    antes de `start_strava_import`: sólo `create_import_run` va bajo `_lock_owner`
    (`rides.py:47-50`).
  - **«Sincronizar ahora» sólo pide los últimos `SYNC_DAYS` = 7 días**
    (`strava_sync.py:67`, `:377`; `strava.html:28` lo dice: «Pide los últimos 7
    días»). Un histórico completado hace tres semanas, sin sincronizar después, deja
    un hueco que sólo cubre volver a importar. Y «Quitar lo sincronizado»
    (`strava_sources.py:603-623`) borra las fuentes y el `StravaAccount`, pero no los
    `ImportRun`: un completado antiguo seguiría «cubriendo» la fecha aunque sus datos ya
    no estén. La siguiente importación crea la cuenta de nuevo con un `connected_at`
    nuevo (`strava_sync.py:157-186`).
- **Recomendada (D24):**
  1. **Estado destacado:** arriba de la página, un `.pending` con el color del estado
     (`st-current` completado, `st-review` sin terminar, `st-due` con error) y la frase
     de «Textos». La línea de contadores se queda debajo. Se quita la frase confusa de
     las dos ramas, Strava y FIT. En «Histórico propio», la primera frase del panel de
     cobertura se cambia por la de «Textos», que dice qué no se puede saber y dónde
     mirar.
  2. **Sin trabajos repetidos (Strava), en el servicio:** `start_strava_import`, antes
     de `ensure_account` (que puede llamar a Strava), mira bajo `_lock_owner` si hay un
     trabajo de Strava `pending`, `running`, `paused` o `failed`. Si lo hay, no crea
     otro ni llama al cliente: lanza una excepción propia (por ejemplo,
     `UnfinishedImport`) con el más reciente. La comprobación **se repite** en la misma
     transacción y bajo el mismo cerrojo que crea el trabajo, para que dos peticiones
     casi simultáneas (doble toque sin JS o dos pestañas) no creen dos: la segunda
     espera al cerrojo, ve el trabajo de la primera y lo devuelve. La vista captura la
     excepción y redirige a ese trabajo con un mensaje.
  3. **Si uno completado ya cubre la fecha, se pide confirmación.** Un trabajo cubre la
     fecha pedida `f` sólo si se cumplen las cuatro cosas:
     - es de Strava y está completado;
     - `requested_from` ≤ `f`;
     - `created_at` ≥ `connected_at` de la cuenta actual (descarta los anteriores a
       quitar lo sincronizado y volver a conectar). Sin cuenta, nada cubre;
     - terminó hace como mucho `SYNC_DAYS` días: `updated_at` ≥ ahora − `SYNC_DAYS`. El
       `updated_at` de un completado es el de su último guardado, el que lo completó:
       `resume_strava_import` sale antes con un completado (`strava_sync.py:551-552`).
       Así, lo que llegó a Strava después lo trae «Sincronizar ahora».

     Entonces el formulario vuelve con el aviso y la casilla «Importar de nuevo
     igualmente», y sólo con ella marcada se crea. Si no, no se pide nada. Esta
     comprobación es un aviso, no integridad: va en la vista, y una carrera entre dos
     envíos sólo puede saltarse el aviso, no duplicar salidas.

     **Orden en la vista (R2-08):** antes del aviso de «cubierto», la vista hace una
     consulta de sólo lectura de trabajos de Strava sin terminar (los mismos estados del
     punto 2). Si hay uno, redirige a él con el mensaje de bloqueo, sin pedir
     confirmación ni llamar al servicio. Si no, sigue con el aviso. El servicio sigue
     siendo la garantía bajo el cerrojo (punto 2). Sin este orden, con un completado
     reciente que cubre la fecha y otro trabajo en pausa a la vez (por ejemplo, uno
     empezado después desde una fecha anterior), la vista pediría confirmar algo que el
     servicio nunca iba a crear.
  4. **Página de Strava:** si hay uno sin terminar, una nota con enlace sobre el
     formulario.
- **Descartadas:**
  - bloquear también el repetido completado: el usuario puede querer repetirlo
    (después de quitar lo sincronizado, por ejemplo);
  - «cubierto» sólo con `requested_from` ≤ `f`: frenaría con un aviso falso la única
    forma de cubrir el hueco que deja un completado de hace más de `SYNC_DAYS` días o
    de una conexión anterior;
  - la comprobación de trabajos sin terminar sólo en la vista: sin cerrojo, dos envíos
    casi simultáneos crean dos trabajos;
  - cambiar los `choices` de `ImportRun.State`: migración (`RUN_STATES`,
    `garage_ui.py:68-76`, ya traduce).
- **Textos:**

  | Rama | Estado | Frase |
  |---|---|---|
  | Strava | completado | «Completado: Garage pidió a Strava tus salidas desde el {inicio} hasta el {fin}. Desde entonces, «Sincronizar ahora» trae sólo los últimos {SYNC_DAYS} días.» ({inicio}: `requested_from`, como fecha con la regla de `local_bound`; {fin}: `updated_at`, al minuto (F22); {SYNC_DAYS}: la constante, no un 7 escrito) |
  | Strava | pendiente, en curso o en pausa | «Faltan páginas: pulsa «Continuar importación». Lo ya guardado se conserva.» |
  | Strava | con error | «Se detuvo por un error: pulsa «Continuar importación» para reintentar. Lo ya guardado se conserva.» |
  | Strava | cancelado | «Cancelado: se conserva lo ya importado. Para traer el resto, empieza otro trabajo desde Strava.» |
  | FIT | completado | «Completado: se procesaron todas las sesiones elegidas.» |
  | FIT | sin terminar | «Faltan sesiones: vuelve a elegir el archivo y pulsa «Continuar importación».» |
  | FIT | con error | «Se detuvo por un error: …» (como Strava) |
  | FIT | cancelado | «Cancelado: se conservan las sesiones ya guardadas.» |

  Mensajes y avisos:
  - al bloquear: «Ya hay un trabajo de importación sin terminar: continúalo aquí o
    cancélalo para empezar otro.»;
  - si ya está cubierto: «Ya importaste el histórico desde el {fecha} (trabajo
    completado el {fecha}). Repetirlo no duplica salidas, pero gasta cuota de Strava;
    para traer las nuevas basta «Sincronizar ahora». Si aun así quieres repetirlo,
    marca «Importar de nuevo igualmente».» (la primera {fecha}, `requested_from` como
    fecha; la segunda, `updated_at` al minuto con `datetime_text`, F22);
  - nota en la página de Strava: «Hay un trabajo sin terminar desde el {fecha}:
    continúalo.» ({fecha}: `requested_from`, como fecha);
  - panel de cobertura de «Histórico propio», en lugar de «Completitud del histórico:
    desconocida.»: «Garage no puede saber si falta una salida que no le llegó por
    ninguna fuente. De Strava, el estado de cada trabajo (en «Trabajos recientes») dice
    qué se pidió y hasta cuándo.». El resto del panel no cambia.
- **Pruebas.** Sin HTTP real: se sustituye el cliente en su capa HTTP
  (`strava_client.requests.get` y `refresh_access_token`), como ya hace
  `tests_strava_views.py`, y se cuentan sus llamadas. `start_strava_import` ya no se
  sustituye en las pruebas del bloqueo, porque el bloqueo vive dentro.
  - **Nuevas (fallan hoy):**
    - `test_the_run_page_leads_with_its_state` (los cuatro estados y las dos ramas);
    - `test_the_confusing_sentence_is_gone` (también en «Histórico propio»);
    - `test_an_unfinished_run_blocks_a_new_one` (302 al trabajo, sin trabajo nuevo y
      sin llamar al cliente; con dos sin terminar, al más reciente);
    - `test_the_service_returns_the_unfinished_run`: dos llamadas seguidas a
      `start_strava_import`; la segunda lanza `UnfinishedImport` con el trabajo de la
      primera, sin crear otro ni llamar al cliente;
    - `test_a_recently_covered_date_asks_for_confirmation` (un completado de hace 2
      días desde una fecha anterior: 400 con el aviso; con la casilla, se crea);
    - `test_an_unfinished_run_wins_over_the_coverage_warning` (R2-08): un completado de
      hace 2 días que cubre la fecha y un trabajo en pausa a la vez. Sin la casilla y
      con ella marcada: 302 al trabajo en pausa con el mensaje de bloqueo, sin el aviso
      de «cubierto», sin trabajo nuevo y sin llamar al cliente;
    - `test_the_strava_page_points_to_the_unfinished_run`.
  - **Guardas (pasan hoy, porque hoy nada pide confirmación ni bloquea):**
    - `test_an_earlier_date_needs_no_confirmation`;
    - `test_a_cancelled_run_does_not_block`;
    - `test_a_run_completed_long_ago_needs_no_confirmation` (hace 10 días, con
      `SYNC_DAYS` = 7);
    - `test_a_run_from_an_earlier_connection_needs_no_confirmation` (creado antes del
      `connected_at` actual, como tras quitar lo sincronizado);
    - `test_a_fit_run_does_not_count_for_strava`.

  Casos límite: la fecha en la zona del usuario (medianoche local); el borde exacto de
  `SYNC_DAYS` (reloj fijado); sin cuenta de Strava.

  Hay que **actualizar** `tests_mobile_lists.py:221` y `tests_history.py:306`, que fijan
  «Completitud del histórico:». Es el cambio buscado.
- **Llamadores:** `strava_import` y `_page` (`strava_views.py`); `StravaImportForm`
  (`strava_forms.py:12-25`); `history_run.html` (`history_views.import_run`);
  `history_index.html` (`history_views.history`); `start_strava_import`
  (`strava_sync.py:525-538`), al que sólo llama `strava_import`; `create_import_run`
  (`rides.py:288-313`), compartido con FIT, que no cambia. Las transiciones permiten
  cancelar un trabajo con error (`rides.py:323-329`).
- **Riesgos:**
  - **no verificable en local** contra Strava real. Lo prueba el usuario cuando
    importe (§8);
  - **no verificable con las pruebas de siempre:** dos peticiones concurrentes de
    verdad. Las pruebas cubren el caso seguido; el concurrente queda cubierto por el
    diseño (comprobación y creación bajo el mismo cerrojo) y se dice así al cerrar.

### F22 · Formatos heredados (`floatformat:3`) y valores en bruto

- **Estado: sigue, en más sitios.** Visto en la demo:
  - Taller → detalles técnicos: «2744.000 / 2500.000 · Queda como máximo: 0.000»
    (`maintenance_alerts.html:7`);
  - «Evaluado a 14 nov 2026, 11:30:59,596356» (`:6`: `local_datetime` de un «ahora»
    con microsegundos);
  - **Estadísticas, con microsegundos en 25 sitios** de la página de la demo, por
    ejemplo «→ 14 nov 2026, 12:06:09,685248». Salen de `local_datetime` con
    `report.end` y `block.end`, que son el «ahora» del cálculo: «Período observado … →
    …» (`statistics.html:79`), «Totales acumulados a …» (`:85`) y las cabeceras de
    «Montajes en el período» y «Períodos entre intervenciones» (`:87-88`);
  - Estadísticas: «Km: 2795.000», «Horas en movimiento: 107.501», «Salidas: 39.000»
    (`statistics_metrics.html:1`);
  - costes con `floatformat:2/4` (`statistics.html:90`);
  - compra en la ficha: «32.90 EUR» (`item_detail.html:97`; también
    `bike_detail.html:82`);
  - **más horas con microsegundos, que la demo no enseña** (R2-03): `_datetime_text`
    añade «,ffffff» siempre que los hay (`garage_ui.py:254-255`), y estas horas las
    guarda el servidor con `now()`:
    - «Última sincronización» (`strava.html:16`): `account.last_sync_at`, de `_record`
      (`strava_sync.py:199-200`);
    - la fecha de cada trabajo en Strava (`strava.html:43`) y en «Histórico propio»
      (`history_index.html:42`): `run.created_at`, `auto_now_add` (`models.py:30`);
    - «Aplazamiento desde el …» en el Taller (`maintenance_alerts.html:10`):
      `snooze.started_at`, de `_when(None)` (`snoozes.py:31-34`);
    - las vigencias de un perfil de uso (`usage_profile.html:12`): «Desde ahora (hora del
      servidor al guardar)» llama al servicio con `at=None`, que usa `now()`
      (`usage_forms.py:88`, `:92`; `usage_profiles.py:57-59`).

    En la demo, Strava está «sin sincronizar» e «Histórico propio» dice «No hay trabajos
    de importación.»: por eso esas páginas dan 0 horas con microsegundos, frente a 25 en
    Estadísticas y 8 en el Taller (contadas en la demo 8769).

  Las lecturas de la ficha son F05.
- **Recomendada (D16):**
  - filtro `figure` en `garage_ui.py` (`quantity(name, value)`) y `figure_max` (hacia
    arriba, para «Queda como máximo»), con el nombre de la métrica, que ya traen esos
    objetos. Para `calendar_days`, el «Restante» de `figure` redondea hacia arriba, con
    la regla de F17 (`remaining_text`), para que el anillo y los detalles técnicos den
    la misma cifra;
  - una variante al minuto de `local_datetime` (por ejemplo, `{% local_datetime value
    "minute" %}`): corta segundos y microsegundos del texto, conserva el instante exacto
    en `<time datetime>` y la misma regla de la hora repetida. Se usa en «Evaluado a», en
    los cuatro sitios de Estadísticas de arriba (`report.end`, `block.start`,
    `block.end`) y en los cinco de R2-03: `strava.html:16`, `strava.html:43`,
    `history_index.html:42`, `maintenance_alerts.html:10` y `usage_profile.html:12` (las
    dos cotas de la vigencia). En una cabecera, un final real con segundos también se
    muestra al minuto; el valor exacto sigue en `datetime`;
  - `datetime_text` (las etiquetas que se componen en Python) gana la misma opción al
    minuto. Los textos nuevos de F21 la usan: {fin} y «trabajo completado el {fecha}»
    van al minuto, y {inicio} y «desde el {fecha}» (`requested_from`, una medianoche
    local) van como fecha, con la regla de `local_bound`;
  - costes con `money` y `num:4`;
  - compra con `money`.
- **Pruebas nuevas (fallan hoy):**
  - `test_technical_details_use_spanish_figures` («2.744 / 2.500», sin «2744.000»);
  - `test_evaluated_at_is_to_the_minute`;
  - `test_statistics_detail_has_no_microseconds` (período, totales y cabeceras de los
    dos desplegables);
  - `test_statistics_detail_uses_spanish_figures` («Km: 2.795», «Salidas: 39»);
  - `test_costs_use_a_decimal_comma`;
  - `test_purchase_price_uses_a_decimal_comma` (pieza y bici);
  - `test_technical_details_round_days_left_up` (de F17);
  - `test_server_times_are_to_the_minute` (R2-03): con una cuenta de Strava sincronizada,
    un trabajo de Strava, un aplazamiento y una versión de perfil «desde ahora», creados
    con el reloj fijado en un instante con microsegundos, Strava, «Histórico propio», el
    Taller y el perfil de uso muestran esas horas sin segundos;
  - guarda final, nueva: `test_no_screen_shows_microseconds`, **con datos de prueba**,
    no con la demo (R2-03): la cuenta, el trabajo, el aplazamiento y la versión de
    arriba, más una regla vencida y salidas para Estadísticas, creados con `now()` sin
    fijar. Recorre las 12 pantallas de §8, Strava, «Histórico propio», la página del
    trabajo, el perfil de uso y las extra de los bloques, y ninguna contiene una hora que
    encaje con `\d:\d{2}:\d{2},\d{6}`. Las capturas finales (§8) miran lo mismo en la
    demo.
- **Llamadores:** `maintenance_alerts.html` (`maintenance.html:88`);
  `statistics_metrics.html` (`statistics.html:84-88`); `statistics.html:79-88`;
  `item_detail.html`, `bike_detail.html`; `strava.html`, `history_index.html` y
  `usage_profile.html` (R2-03); `local_datetime` (decenas de plantillas: la variante es
  un argumento opcional, y sin él nada cambia); `datetime_text` (las etiquetas de
  intervención de F05 y los textos de F21).
- **Riesgos:**
  - los detalles técnicos pierden decimales a propósito. El valor exacto sigue en la
    exportación;
  - una versión histórica de un perfil escrita con segundos se ve al minuto; el instante
    exacto sigue en `<time datetime>` y en su formulario de edición.

### F23 · Tamaño táctil de «Corregir lectura»

- **Estado: ya resuelta por Anillos** (commit `5caedd5`, revisión F1).
  - `.page .actions > a:not([class])` da 44 px (`garage.css:536`), y
    `tests_mobile_item.py:263-275` fija el marcado.
  - **Medido:** con el marcado de `item_detail.html:101` dentro de la ficha real y su
    CSS, el enlace mide 112×44 px a 390 px.
- **Acción:** ninguna. Captura con una lectura real en §8 (la demo no tiene lecturas).

### F24 · «Sólo las que están por revisar» con una bici elegida

- **Estado: sigue.**
  - `pending_rides` exige `bike__isnull=True` (`home.py:20-22`), y la lista filtra
    después por la bici (`usage_views.py:95`): siempre vacía.
  - La píldora se ofrece igual con bici (`usage_rides.html:6`, `usage_views.py:113`).
- **Recomendada (D3):**
  - con una bici elegida no se pinta la píldora;
  - si llegan las dos cosas por URL, el vacío dice: «Las salidas por revisar no tienen
    bici: quita el filtro de {bici} para verlas.»;
  - el chip de la bici sigue quitándola y conserva `pending`.
- **Descartadas:** ignorar la bici con `pending`: el chip de la bici diría una cosa y
  la lista haría otra.
- **Pruebas nuevas (fallan hoy):**
  - `test_no_pending_pill_with_a_bike`;
  - `test_pending_and_bike_explain_the_empty_list`.
- **Guardas (pasan hoy):** `test_pending_pill_without_a_bike`.
- **Llamadores:** `ride_filters` y `ride_list_url` (`usage_views.py:69-77`); la ficha
  de bici enlaza a Salidas con `?bike=` (`bike_detail.html:57`).
- **Riesgos:** ninguno.

### F25 · Carácter nulo en la búsqueda: error 500

- **Estado: sigue, en cuatro listas.** Un carácter nulo en el parámetro de búsqueda da
  500 en Salidas, Material, Bicis y Categorías. Histórico no tiene buscador y responde
  200. Es anterior a Anillos.
  - **Causa:** `q` llega sin limpiar a `name__icontains` (`usage_views.py:82,97`;
    `views.py:64,69`), y PostgreSQL no admite el carácter nulo en un literal.
  - Los formularios no tienen el problema: `CharField` ya lo rechaza.
- **Recomendada (D2):**
  - un ayudante común, por ejemplo `search_text(request)` en `views.py`: lee `q`, quita
    los caracteres nulos, recorta a 200 y quita espacios;
  - lo usan las dos vistas;
  - un nombre no puede contener un carácter nulo, así que buscar el resto es lo que se
    habría encontrado.
- **Descartadas:**
  - responder 400: el buscador es una caja de texto, no una API;
  - devolver vacío: parecería que no hay nada.
- **Pruebas nuevas (fallan hoy):**
  - `test_a_null_character_in_the_search_is_ignored` (las cuatro listas: 200, el mismo
    resultado que sin él, y la caja sin el carácter);
  - `test_a_search_of_only_null_characters_is_no_search`;
  - `test_the_200_character_cap_counts_after_cleaning`.
- **Llamadores:** `views.inventory_list` (tres clases) y `usage_views.ride_list`. Los
  enlaces de paginación usan `query` (`views.py:91`, `usage_views.py:111`), que ya sale
  del `q` limpio.
- **Riesgos:** ninguno.

---

## 5. Bloques

Orden por dependencias: lo compartido antes de usarlo y el error 500 lo primero. **La
tabla va en el orden de ejecución**: B12 va antes que B10 (R2-02), aunque conserva su
número. Cada bloque es un diff revisable, de unas 300 líneas de producción como mucho,
sin refactor mezclado. Las cifras de líneas son estimaciones.

**Reglas comunes a todos los bloques:**
- un solo escritor (agente Opus), de uno en uno, hasta 3 rondas de revisión;
- pruebas primero: las nuevas se ven fallar y las guardas se ven pasar; luego se
  implementa y pasan todas;
- `grep` de llamadores antes de tocar nada;
- sin SPA, sin dependencias y sin scripts en línea (sólo `garage.js`, con `defer`;
  `tests_mobile_shell.py`);
- `manage.py check` limpio y `makemigrations --check --dry-run` sin cambios;
- `suite-gate` al cerrar cada bloque. Referencia de la rama: 3556 passed, 464 subtests,
  0 fallos;
- en Beads, una nota por F al arreglarla, con su commit (si el usuario los pide) y cómo
  probarla.

| Bloque | Fricciones | Archivos | Líneas | Depende de |
|---|---|---|---|---|
| **B1** · Búsqueda segura y píldora de pendientes | F25, F24 | `views.py`, `usage_views.py`, `usage_rides.html` | ~25 | — |
| **B2** · Textos, etiquetas y errores en español | F07, F09, F13 | `web_forms.py`, `maintenance_forms.py`, `forms.py` (errores de `Model.clean`), `views.py` (`show_errors`, `installation_action`) | ~140 | — |
| **B3** · Mensajes al guardar y «Sustitución» | F08, F06 | `maintenance_views.py`, `maintenance_forms.py` | ~40 | B2 |
| **B2b** · Errores en español en el resto de formularios web (D25, añadido el 14 nov tras B3) | F07 (ampliación) | `usage_forms.py`, `history_forms.py`, `photo_forms.py`, `statistics_forms.py`, `local_forms.py`, el formulario del lote de bicis, `maintenance_forms.py` (`SPANISH`) | ~80 | B2 |
| **B4** · Orden alfabético | F10 | `ordering.py` y `checks.py` (nuevos), `apps.py`, y los sitios de la lista de F10 (con `lifecycle.py` y `presentation.py`) | ~125 | — |
| **B5** · Selectores de objeto distinguibles | F02 | `choices.py` (nuevo), `web_forms.py`, `maintenance_forms.py`, `local_forms.py` | ~130 | B2, B4 |
| **B6** · Zona y fechas en los formularios | F01, F03 | `garage_ui.py` (ayudante), `form.html`, `lifespan.html`, `web_forms.py`, `garage.js` | ~90 | B2 |
| **B7** · Nueva regla en filas | F20 | `maintenance_forms.py`, `form.html` (filas del ayudante) | ~40 | B6 |
| **B8** · Retirar: qué cierra, desde cuándo y «Guardando…» | F04 | `retirement.py`, `views.py`, `garage.js`, `garage.css` (`.busy`), `data-busy` en `strava.html`, `history_run.html` y `snooze.html` | ~95 | B6 (mismo `garage.js`) |
| **B9a** · Palabras de las lecturas en una sola fuente (traslado, sin cambio visible) | F05 (parte 1) | `presentation.py`, `web_forms.py` | ~20 | B2 |
| **B9b** · Lecturas en km y horas | F05 | `presentation.py`, `web_forms.py`, `garage_ui.py`, `item_detail.html:101`, `service_event.html:23`, `statistics_metrics.html:3` | ~150 | B9a |
| **B12** · Cifras de reglas e intervenciones | F17, F18 | `presentation.py`, `garage_ui.py` | ~15 | — (va antes que B10: R2-02) |
| **B10** · Formatos heredados | F22 | `garage_ui.py`, `maintenance_alerts.html`, `statistics_metrics.html`, `statistics.html`, `item_detail.html:97`, `bike_detail.html:82`, `strava.html`, `history_index.html`, `usage_profile.html` | ~65 | B9b, B12 |
| **B11** · Ficha: acciones visibles, horas y piezas anteriores | F14, F15, F16 | `item_detail.html`, `bike_detail.html`, `views.py` | ~90 | B10 (misma plantilla) |
| **B13** · Garaje vacío y sesión | F11, F12 | `home.py`, `index.html`, `more.html` | ~30 | B4 (`home.py`) |
| **B14** · Histórico: estado claro y sin trabajos repetidos | F21 | `strava_sync.py` (bloqueo bajo cerrojo), `history_run.html`, `history_index.html`, `strava_views.py` (orden: sin terminar antes que «cubierto»), `strava_forms.py`, `strava.html` | ~160 | B10 (`datetime_text` al minuto) |

### Detalle por bloque

**B1.**
- *Pruebas:* las de F25 y F24, en `tests_mobile_lists.py`.
- *Aceptación:*
  - las cuatro listas responden 200 con un carácter nulo en la búsqueda;
  - con bici no hay enlace con `pending=1`;
  - con `pending=1&bike=…`, el vacío dice el texto de F24.
- *Capturas:* `salidas` y `material`, más Salidas con bici (`--url`).
- *Riesgos:* ninguno.

**B2.**
- *Pruebas:* F07, F09 y F13, en `tests_secondary_forms.py`, `tests_mobile_workshop.py`
  y `tests_views.py`.
- *Aceptación:*
  - ningún formulario web muestra «Name», «Notes», «Item», «Service event»,
    «---------», «Ensure that», «Enter a number», «Enter a valid date», «Null
    characters» ni los mensajes ingleses de F07, también los de montajes y del ancla de
    adquisición (R2-01);
  - cada error sale una sola vez, también uno del servicio al guardar, y un nombre de
    categoría repetido no añade «Escribe un nombre.» (R2-01);
  - el error de un instante fuera del montaje que sale va junto a «Instante del
    cambio»;
  - las páginas que recorre `test_no_django_empty_option_is_shown` son las de F09,
    filtro de Estadísticas incluido;
  - `UsedItemWebForm` llama a `spanish_fields` tras crear sus campos;
  - los títulos van en singular;
  - Categoría es el segundo campo de Crear material.
- *Capturas:* `registrar-intervencion`, `estadisticas`, Crear material, Nuevo tipo,
  Montar, Reemplazar y Registrar lectura (`--url`).
- *Riesgos:* los textos fijados en pruebas se actualizan con el cambio y se dice cuáles.

**B3.**
- *Pruebas:* F08 y F06, en `tests_mobile_workshop.py` y `tests_lifespan.py`.
- *Aceptación:*
  - mensaje en los tres guardados, también al editar;
  - la opción «Sustitución (en un objeto, es su vida útil)»;
  - el mensaje de vida útil sólo con objeto.
- *Capturas:* `taller` tras guardar (mensaje) y Nueva regla.

**B2b** (D25; se ejecuta tras B3 y antes de B4).
- *Origen:* B2-R2-03 (§10.1). Reproducido en la revisión de B2, ya pasaba antes de B2:
  - excepción de una salida, vacía: «This field is required.» una vez;
  - perfil nuevo, vacío: tres veces;
  - salida manual, vacía: dos veces; con `distance_m='mucho'`, «Enter a number.»; con
    `1.2345`, «The value must be exactly representable with three decimal places.»;
  - Estadísticas con la zona vacía, vista previa del FIT sin archivo y lote de bicis
    vacío: también;
  - por lectura de código, lo mismo en `RideCorrectionForm`, `FitExecuteForm`,
    `FitResumeForm` y `PhotoUploadForm` (mensajes de `FileField`).
- *Pruebas:*
  - nuevas: cada formulario de la lista, enviado vacío y con valores mal escritos, sólo
    muestra mensajes en español, cada uno una vez, y no guarda nada;
  - el barrido de `test_no_web_form_page_shows_a_known_english_message` (o uno igual)
    recorre también estas páginas;
  - guardas: los mensajes que ya salen en español no cambian; el admin sigue como está.
- *Aceptación:*
  - ningún formulario web de Garage muestra los mensajes ingleses de F07;
  - `ManualRideForm` y `RideCorrectionForm` llaman a `spanish_fields` después de
    `ride_fields()` y de rehacer `self.fields`, porque crean campos tras
    `super().__init__()`;
  - las traducciones de `exact_usage_value` llegan a las métricas de la salida: vienen
    de `to_python`, así que necesitan `_spanish` en `add_error` o en el campo;
  - cada error sale una sola vez y nunca uno falso (D4).
- *Capturas:* Salida manual, Excepción de una salida, Perfil nuevo y Estadísticas con
  errores (`--url`, POST vacío si la herramienta lo permite; si no, prueba de vista).
- *Riesgos:* los textos fijados en pruebas de histórico y de uso se actualizan y se
  dice cuáles. No mezclar otros cambios: el doble error de un `select` manipulado en
  `UsedItemWebForm` (nota de B2, ronda 2) queda fuera.

**B4.**
- *Pruebas:* F10, en `tests_ordering.py` (nuevo) y `tests_mobile_lists.py`.
- *Aceptación:*
  - los siete nombres ordenados como en §4 F10 en lista, selectores e Inicio;
  - las variantes de mayúsculas («sram gx», «Sram GX», «SRAM GX») salen en el mismo
    orden en lista, selectores e Inicio;
  - `name_key` coincide con la base en nombres con letras base distintas (con la
    salvedad de F10 para ø, ł, æ, œ, ı…), y su aproximación queda documentada y probada;
  - **grep:** cada ordenación por nombre de `garage/*.py`, `garage/services/*.py` y
    `garage/templatetags/*.py` (fuera de las pruebas), también las de `sorted(`/`.sort(`
    sin `.name` (`lifecycle.py:162`, `presentation.py:355-359`), está convertida o en la
    lista de excepciones del bloque, con su motivo (§4 F10, R2-05);
  - «En uso · Ébano, Gravel», en ese orden (R2-05);
  - `manage.py check --database default` contra el clúster de pruebas no da errores, y
    con la consulta sustituida da `garage.E001` (R2-09);
  - ninguna migración.
- *Capturas:* `material` y `garaje`.
- *Riesgos:* `es-x-icu` en producción (§6); la comprobación de sistema lo detecta, no lo
  arregla.

**B5.**
- *Pruebas:* F02, en `tests_secondary_forms.py` o en un `tests_item_choices.py` nuevo.
- *Aceptación:*
  - etiquetas como en F02;
  - retirados al final;
  - fecha sólo en las coincidentes;
  - presupuesto de consultas igual con 5 y con 25 objetos.
- *Capturas:* Nueva regla, Registrar mantenimiento, Montar, Transferir y Reemplazar
  (`--url`), con el selector desplegado si la herramienta lo permite. Si no, se lee el
  HTML.
- *Riesgos:* largo de etiqueta en iOS.

**B6.**
- *Pruebas:* F01 y F03, en `tests_mobile_workshop.py` y `tests_secondary_forms.py`.
- *Aceptación:*
  - la zona va detrás del último campo de fecha;
  - el resumen dice «Horas en … · Cambiar»;
  - «ahora» llega al minuto, con su ayuda; «Editar montaje de …» no la muestra (R2-06);
  - CDP: al escribir otra zona, el resumen cambia;
  - CDP, en Nueva regla a 390×706: con el resumen de la zona colocado justo encima de
    la barra, tras abrirlo, el borde inferior del `details.zone` queda por encima del
    borde superior de la barra, y su punto central no devuelve la barra
    (`elementFromPoint`).
- *Capturas:* Montar, Retirar, Registrar mantenimiento, Vida útil y Crear material
  (`--url`).
- *Riesgos:* `_together.html` queda detrás de la zona (aceptado en F01).

**B7.**
- *Pruebas:* F20.
- *Aceptación:*
  - umbrales de dos en dos;
  - a 390×706, la caja de «Contar desde» sube al menos 170 px (de 1114 px; el
    prototipo dio 176, §4 F20);
  - sin desborde a 320 px.
- *Capturas:* Nueva regla a los 6 tamaños, más 390×706.

**B8.**
- *Pruebas:* F04, en `tests_retire_parts.py`, y la guarda de `tests_ui_guards.py`.
- *Aceptación:*
  - la página nombra el montaje y el límite, y con `with_parts` ofrecido, el de lo que
    lleva dentro;
  - el POST rechazado los conserva;
  - CDP: tras enviar, el botón dice «Guardando…» y un segundo envío no hace otra
    petición (se cuentan en `Network`). Con un envío que el servidor rechaza (un
    instante anterior al límite), para no escribir nada;
  - CDP: el estado ocupado aparece en un formulario de cada plantilla con `form.form`
    y `method=post` de §4 F04 que se pueda abrir en la demo (`form.html`,
    `lifespan.html`, `snooze.html`, `photo_form.html`, `history_preview.html`,
    `strava.html`, `usage_ride.html`), **y en los que llevan `data-busy` y se pueden
    abrir: «Sincronizar ahora» y los atajos de posponer** (R2-07). Se mira la clase y
    `aria-disabled` con la petición interceptada y fallada en CDP (`Fetch`), para que no
    llegue al servidor: «Sincronizar ahora» nunca llega a pedir nada a Strava.
    `history_execute.html`, `source_merge.html` y `history_run.html` (también su
    «Continuar importación» con `data-busy`) necesitan datos que la demo no tiene: se
    cubren con la guarda estática y `test_slow_or_repeating_posts_are_marked_busy`, y se
    dice así;
  - el formulario de tema de `more.html` no cambia;
  - al volver atrás (página de la caché del navegador), el botón vuelve a estar listo.
- *Capturas:* Retirar de una pieza montada, de una suelta y de una bici.

**B9a.** Refactor puro, sin cambio de comportamiento.
- *Pruebas:* ninguna nueva y ninguna tocada. La guarda es la suite entera.
- *Aceptación:*
  - `SCOPES`, `METRICS` y `SOURCE_CHOICES` se construyen en `presentation.py` con los
    mismos textos de hoy, y `web_forms.py` los importa;
  - el diff no cambia ningún texto visible ni ninguna prueba;
  - `suite-gate` con las mismas cifras que antes del bloque.
- *Capturas:* ninguna (no cambia nada visible).

**B9b.**
- *Pruebas:* F05, en `tests_baseline_forms.py`, `tests_mobile_item.py` y
  `tests_statistics.py`.
- *Aceptación:*
  - lecturas en km, horas y salidas;
  - `value` exacto aceptado;
  - ficha, intervención y estadísticas en español y formateadas.
- *Capturas:* Registrar lectura y la ficha con una lectura (§8).
- *Riesgos:* el formulario de corrección con un valor no exacto.

**B12** (va antes que B10, R2-02).
- *Pruebas:* F17 y F18, en `tests_ring.py` y `tests_service_usage.py`.
- *Aceptación:* los días suman el umbral; nunca un «≥ 0 km» en la línea corta, tampoco
  con un mínimo por debajo de 0,1 km (`span_text`, la línea larga, queda fuera: §7).
- *Capturas:* `pieza` con regla de calendario y `taller`.

**B10** (después de B9b y de B12).
- *Pruebas:* F22, en `tests_mobile_workshop.py`, `tests_mobile_stats.py`,
  `tests_strava_views.py` y `tests_history.py`.
- *Aceptación:*
  - ningún `floatformat` en `garage/templates/garage/` (guarda nueva:
    `test_no_template_uses_floatformat`);
  - las cifras con coma decimal y puntos de miles;
  - ninguna hora con microsegundos en Taller, Estadísticas, Strava, «Histórico propio»
    ni el perfil de uso, con datos creados con `now()`
    (`test_statistics_detail_has_no_microseconds`, `test_server_times_are_to_the_minute`
    y `test_no_screen_shows_microseconds`, con datos de prueba y no sólo con la demo:
    R2-03);
  - el «Restante» de días de los detalles técnicos coincide con el del anillo (B12 ya
    está hecho: `test_technical_details_round_days_left_up` pasa entera).
- *Capturas:* `taller` (detalles técnicos abiertos), `estadisticas` (detalle), `pieza` y
  `strava`.

**B11.**
- *Pruebas:* F14, F15 y F16, en `tests_mobile_item.py`, `tests_mobile_bike.py` y
  `tests_parts.py`; presupuestos de `tests_lifecycle.py:393` y
  `tests_mobile_item.py:196`.
- *Aceptación:*
  - acciones fuera de Detalles;
  - enlaces de montar como en la tabla de F14;
  - horas y zona en la cronología;
  - piezas anteriores nombradas;
  - consultas sin subir.
- *Capturas:* `pieza` (suelta, montada y retirada con piezas anteriores) y `bici`.
- *Riesgos:* fila de acciones a 320 px.

**B13.**
- *Pruebas:* F11 y F12, en `tests_mobile_home.py` y `tests_mobile_shell.py`.
- *Aceptación:* cuatro textos de Garaje vacío; «Has entrado como demo» en Más.
- *Capturas:* `mas` y `garaje` (el vacío sólo en pruebas: la demo tiene material).

**B14.**
- *Pruebas:* F21, en `tests_strava_views.py`, `tests_history.py`,
  `tests_mobile_lists.py` y `tests_secondary_forms.py`, sin HTTP real.
- *Aceptación:*
  - estado destacado en las dos ramas;
  - sin la frase antigua, tampoco en «Histórico propio»;
  - el servicio no crea un trabajo con otro sin terminar, ni llama al cliente;
  - un trabajo sin terminar gana al aviso de «cubierto»: la vista redirige a él sin
    pedir confirmación (R2-08);
  - se confirma el repetido sólo si lo cubre un completado de la conexión actual que
    terminó hace como mucho `SYNC_DAYS` días;
  - las horas de los textos nuevos, al minuto o como fecha (F21, F22); la guarda de
    microsegundos de B10 sigue pasando con la página del trabajo.
- *Capturas:* `strava`. La página del trabajo no se puede capturar en la demo (no hay
  trabajos): se verifica con las pruebas, y en §8 se dice cómo verla si se quiere.
- *Riesgos:* Strava real, sólo el usuario.

---

## 6. Lo que requiere al usuario

**Ninguna fricción sale de los bloques.** Ninguna exige migración, dependencia nueva,
cambiar o borrar datos guardados, quitar algo que el usuario ya usa ni tocar Strava
real. Quedan anotados, para el repaso o el despliegue:

1. **F10, intercalación en producción (garage-023).** El orden usa `es-x-icu`. Antes de
   desplegar, alguien con permiso comprueba en la base de producción, en sólo lectura,
   que exista (`pg_collation`). Si no existe, hay que elegir entre ordenar en Python
   (paginación en memoria) o la extensión `unaccent` (migración). Esto **no bloquea**
   el trabajo local. Red de seguridad (R2-09): la comprobación de sistema
   `garage.E001` para `migrate` y `manage.py check --database default` si falta, en
   vez de dejar que las páginas den 500. garage-023 añade ese `check` a su receta,
   porque su plan es un docker-compose sin `migrate`.
2. **F21, con Strava real.** El aviso y el bloqueo sólo se han probado con un cliente
   falso. Lo comprueba el usuario cuando vuelva a importar. «Cubierto» depende de
   `SYNC_DAYS` (7): si un día cambia ese valor, el aviso lo sigue sin tocar nada más.
3. **Todas las [052]:** se repasan con el usuario. Si alguna no le gusta, se revierte
   ese bloque, que es pequeño y aislado.

Nada de las rondas 1 y 2 de la crítica (§10) añade una migración, una dependencia, un
cambio de datos guardados ni quita nada que se use: no sale ninguna fricción de los
bloques. En la ronda 2, la comprobación de sistema es código del propio Garage (sin
dependencia ni infraestructura), `data-busy` es un atributo sin cambio de aspecto, y
los textos nuevos traducen mensajes sin cambiar sus códigos ni las claves de posición.

---

## 7. Fuera de alcance

- **Diferencias de presentación con ProBikeGarage** de la nota del 1 nov, (1)–(8):
  repaso garage-052.
- **Decisiones abiertas de Anillos**, que decide el usuario:
  - la pestaña de Material;
  - las claves de posición en inglés («rear_tire», «main_saddle», ayudas de
    `web_forms.py:219` y `part_forms.py:21`);
  - el gráfico de 420 px;
  - «Guardar foto» y «Continuar importación» como botones secundarios;
  - el `h1` de Bici de 26 px;
  - el orden de teclado de la barra lateral;
  - las pruebas de texto de `tests_ui_guards.py`.
- **garage-053** (posponer una bici o un componente entero).
- **Visto de paso, no pedido (para garage-052):**
  - en la ficha de Cadena 11v, «Coste por km» dice «32,90 EUR · No calculable: costes
    sin importe o moneda» porque otra intervención no tiene importe; el texto confunde;
  - `span_text` sigue diciendo «≥ 0 km» en la pantalla de la intervención (F18 sólo
    cambia la línea corta);
  - la etiqueta de «Sustitución» en el formulario de **intervención** (F06 sólo cubre
    reglas);
  - «Procedencia declarada» de una lectura es texto libre (`manual`): F05 sólo lo
    muestra en español.

---

## 8. Plan de verificación

1. **Por bloque:**
   - las pruebas nuevas, vistas fallar antes del cambio, y las guardas, vistas pasar
     antes y después (se guarda la salida). B9a no tiene nuevas: su guarda es la suite;
   - las pruebas del área: `garage-test -m pytest -q -p no:cacheprovider <archivos>`
     desde la raíz del árbol;
   - `manage.py check`;
   - `makemigrations --check --dry-run` sin cambios.
2. **Al cerrar cada bloque:** `suite-gate <B·n>` (unos 8 min, en segundo plano, nunca
   dos `pytest` a la vez), 0 fallos frente a la referencia (3556 passed, 464 subtests),
   y la cifra nueva anotada.
3. **Revisión:** hasta 3 rondas por bloque. Revisor sin el contexto de la
   implementación y con un caso reproducible por hallazgo (idealmente, una prueba que
   falle).
4. **Comprobaciones con CDP** (navegador sin cabeza, perfil temporal, usuario `demo`,
   puerto 8769, tras reiniciar la demo 047):
   - F01, el resumen cambia al escribir, y al abrir la zona con el resumen justo
     encima de la barra, la zona queda por encima de ella (B6);
   - F04, «Guardando…», un solo envío y vuelta atrás, y el estado ocupado en las
     plantillas de B8, también en «Sincronizar ahora» y los atajos de posponer, con la
     petición fallada en CDP antes de llegar al servidor;
   - F20, posición de «Contar desde» a 390×706 (sube al menos 170 px).
5. **Capturas finales:**
   - con `capture.mjs`: las 12 pantallas × 6 tamaños × 2 temas, más las pantallas
     extra de cada bloque (`--url`) a los 6 tamaños y los 2 temas;
   - salida fuera del repositorio, en la carpeta de capturas de garage-047;
   - criterio: **0 desbordes** (`scrollWidth ≤ clientWidth`) y **0 errores de
     consola** en `report.json`;
   - F19: Crear categoría a 390×706, `:checked` y Guardar de un clic;
   - F23: la ficha **con una lectura**. La demo no tiene ninguna; se crea una en la
     **copia 047** con el usuario `demo` desde Registrar lectura, y se anota. Nunca en
     la demo de Anillos (puerto 8768 y su base), que no se toca.
   - la página de un trabajo del histórico no se puede capturar sin un trabajo. Si se
     quiere verla, se crea uno de FIT en la copia 047 con un archivo ficticio de las
     pruebas; si no, queda verificada por las pruebas de B14.
6. **No verificable en local**, y se dice así al cerrar:
   - `es-x-icu` en producción (la comprobación de sistema sólo se ha visto fallar con
     la consulta sustituida);
   - el aviso de F21 contra Strava real;
   - dos importaciones de Strava pedidas a la vez de verdad (F21): las pruebas cubren
     las llamadas seguidas; lo concurrente queda cubierto por el cerrojo, por diseño;
   - el aspecto en un iPhone real del selector nativo con etiquetas largas (F02).

---

## 9. Correspondencia con garage-047

| Viñeta de Beads (descripción o notas) | F |
|---|---|
| Más relevantes 1: Zona horaria escondida… la barra fija tapa el campo | F01 |
| Más relevantes 2: Nombres duplicados indistinguibles… retirados sin marca | F02 |
| Más relevantes 3: Fechas precargadas con «ahora» al segundo | F03 |
| Más relevantes 4: Retirar no dice qué montajes cerrará… sin «guardando…» | F04 |
| Más relevantes 5: Registrar lectura en bruto… «Lecturas de uso» en inglés y en bruto | F05 (y la parte de la ficha de F22) |
| Más relevantes 6: Elegir el tipo «Sustitución» en Nueva regla | F06 |
| Coherencia: Etiquetas en inglés… errores de solape o ciclo en inglés | F07 |
| Coherencia: Sin mensaje de confirmación al guardar tipo, regla e intervención | F08 |
| Coherencia: Títulos en plural; «---------»; Categoría casi al final | F09 |
| Coherencia: Orden alfabético sensible a acentos y mayúsculas | F10 |
| Coherencia: Garaje vacío dice «Todo tu material está montado.» | F11 |
| Coherencia: No se ve qué usuario tiene la sesión | F12 |
| Coherencia: Placeholder «EUR» en Moneda | F13 |
| Ficha: «Retirar» y «Montar / remontar» dentro de Detalles; tres botones de montar | F14 |
| Ficha: el resumen MONTAJES sólo da la fecha; horas sin zona | F15 |
| Ficha: un padre retirado dice «Sin piezas montadas dentro» | F16 |
| Ficha: días de una regla redondeados hacia abajo por los dos lados | F17 |
| Ficha: sin salidas, «a ≥ 0 km de la anterior» | F18 |
| Ficha: Crear categoría, radio sin marcar; Guardar falló a un clic | F19 |
| Ficha: Nueva regla, «Contar desde» y umbrales bajo el pliegue a 706 px | F20 |
| Notas, 1 nov: feedback del usuario sobre el histórico («¿cómo sé si falta?») y el segundo trabajo | F21 |
| Notas, 14 nov, añadido (a): formatos heredados («Km: 2795.000») y lecturas en bruto en la ficha | F22 (lecturas: F05) |
| Notas, 14 nov, añadido (b): tamaño táctil de «Corregir lectura» | F23 |
| Notas, 14 nov, añadido (c): píldora de pendientes en Salidas con una bici | F24 |
| Notas, 14 nov, añadido (d): una entrada de búsqueda que da error 500 | F25 |
| Notas, 1 nov: diferencias de presentación con ProBikeGarage (1)–(8) | fuera (§7, garage-052) |
| Notas, 3 nov: desborde por `table.sr-only` | ya corregido en Anillos (`74ffcd6`); se comprueba en las capturas finales (§8) |
| Notas, 4 nov: posponer bici o componente entero | fuera (garage-053) |

---

## 10. Registro de la crítica

Cada hallazgo se intentó refutar reproduciéndolo antes de aplicarlo. Ninguno se
rechazó: los dieciséis de la ronda 1 y los nueve de la ronda 2 se reprodujeron. La
numeración F y D no cambia: no se retiró ninguna; B9 se partió en B9a y B9b (ronda 1), y
B12 pasa a ir antes que B10 sin cambiar de número (ronda 2).

| Ronda | Id | Severidad | Resultado | Motivo (una línea) |
|---|---|---|---|---|
| 1 | R1-01 | importante | aplicado | `SYNC_DAYS` = 7 (`strava_sync.py:67`, `:377`) y «Quitar lo sincronizado» no borra los `ImportRun`: «cubierto» exige además la conexión actual y haber terminado hace ≤ `SYNC_DAYS` días; textos nuevos; también el panel de «Histórico propio» (F21, D24, B14). |
| 1 | R1-02 | importante | aplicado | Reproducido con CDP a 390×706: con la zona detrás de «Contar desde», al abrirla queda en 568–618 px bajo la barra (540–616). `scrollIntoView({block: 'nearest'})` al abrir la deja en 331–520 px; va en B6 con su aceptación CDP, y §1 corregido (F01, D11). |
| 1 | R1-03 | importante | aplicado | Prototipo en la demo: «Contar desde» sube 176 px (1114 → 938), no 200. Criterio fijado en ≥ 170 px; la etiqueta de Tiempo ya va en dos líneas a 390 px; acortarla (Δ 198) se descarta (F20, B7). |
| 1 | R1-04 | importante | aplicado | Reproducido en un shell: con `SpanishWebMixin`, tres decimales en el precio dan «Ensure that there are no more than 2 decimal places.». Se añaden los códigos de `DecimalValidator`, los mensajes del modelo de lecturas y de `exact_usage_value`, y `spanish_fields` al final de `UsedItemWebForm.__init__` (F07, D4, B2). |
| 1 | R1-05 | importante | aplicado | 25 horas con microsegundos en Estadísticas de la demo, de `report.end` y `block.end`; variante al minuto de `local_datetime` y guarda final sin `,\d{6}` (F22, D16, B10). |
| 1 | R1-06 | importante | aplicado | Comprobado en el clúster local: ICU desempata por acento y mayúscula y ordena la puntuación de otra forma que una clave Python. Se ordena en la base y en memoria sólo con órdenes estables o por posición; `name_key`, aproximación documentada y probada (F10, F02, D9, B4). |
| 1 | R1-07 | menor | aplicado | `retire_with_parts` retira cada pieza con su propio `_close_for_retirement`, que mira también sus hijas: el límite se calcula también sobre el alcance cuando se ofrece `with_parts`, y el texto no promete que baste (F04, D14, B8). |
| 1 | R1-08 | menor | aplicado | `quantity('distance_m', 0.04, down=True)` da «0»: se decide con la cifra mostrada; prueba con 0,04 y 0,1 km (F18, D21, B12). |
| 1 | R1-09 | menor | aplicado | `quantity('calendar_days', 180.4)` da «180» y con `up`, «181»: el «Restante» de los detalles técnicos redondea los días hacia arriba, como el anillo (F17, F22, D16, D20). |
| 1 | R1-10 | menor | aplicado | «---------» también en Reemplazar (`incoming_item`), en el filtro de Estadísticas (3 en la demo) y en la excepción de una salida (`usage_forms.py:96`). Estadísticas entra con «Todas»/«Todos», y la prueba enumera sus páginas (F09, D5, B2). |
| 1 | R1-11 | menor | aplicado | El grep encuentra más ordenaciones por nombre (`usage_views.py:65`, `:107`, `:132`, `statistics.py:171-172`, `service_usage.py:187`, `parts.py:53`, `:70`, `workshop.py:55`, `strava_views.py:57` y `Meta.ordering`): lista completa y aceptación por grep con excepciones (F10, B4). |
| 1 | R1-12 | menor | aplicado | Varias pruebas «nuevas» pasan hoy: cada F separa ahora las nuevas (fallan hoy) de las guardas (pasan hoy); §4, §5 y §8.1 lo dicen. |
| 1 | R1-13 | menor | aplicado | `strava_import` no toma cerrojo antes de `start_strava_import`: la comprobación pasa al servicio, antes de `ensure_account` y repetida bajo el cerrojo que crea el trabajo; prueba con dos llamadas seguidas (F21, D24, B14). |
| 1 | R1-14 | menor | aplicado | `home.gear` también queda vacío con piezas montadas y el resto retiradas: cuarto texto, «Todo tu material activo está montado.», con su prueba (F11, D22, B13). |
| 1 | R1-15 | menor | aplicado | B9 mezclaba traslado y comportamiento: B9a mueve las palabras sin cambio visible ni pruebas tocadas; B9b cambia el comportamiento (§5, F05, D15). |
| 1 | R1-16 | menor | aplicado | Citas corregidas: ≤ 47 en `tests_mobile_item.py:196`; zona de `lifespan.html` ya tras «Cuenta desde» (no se mueve); llamadores reales de `SCOPES`/`METRICS`/`SOURCE_CHOICES`; lista completa de `form.form` con `method=post` en F04 y B8; la etiqueta de F06 usa la regla de `is_life` (`strip` y minúsculas), con prueba « Sustitución ». |
| 2 | R2-01 | importante | aplicado | Reproducidos (shell y código): `invalid_transition`, `invalid_slot`, `installation_closed`, el ancla de adquisición, `DateField` y el carácter nulo siguen en inglés; y un error del servicio al guardar sale dos veces (`_update_errors` + `show_errors`). Al reproducirlo en la demo apareció además un «Enter a nonempty name.» falso tras un nombre de categoría repetido. Textos, `INVALID`, `FIELD_MESSAGES`, `at` en `installation_action`, «un error, una vez» y pruebas (F07, D4, B2). |
| 2 | R2-02 | importante | aplicado | `remaining_text` redondea los días hacia abajo hasta B12 (`presentation.py:58-59`, `:169-171`): con B10 antes, su prueba del anillo falla. B12 va antes que B10 y B10 depende de B12 (§5, F17). |
| 2 | R2-03 | importante | aplicado | Cinco plantillas más pintan horas de `now()` con microsegundos que la demo no enseña (0 en Strava e Histórico, 8 en Taller, contadas). Variante al minuto en `strava.html:16`, `:43`, `history_index.html:42`, `maintenance_alerts.html:10`, `usage_profile.html:12`; textos de F21 al minuto o como fecha; guarda con datos de prueba (F22, F21, D16, B10). |
| 2 | R2-04 | menor | aplicado | Reproducido en un shell: el valor de una lectura da el mensaje de `exact_usage_value`, no el de `DecimalValidator`. Cita corregida y la prueba espera «El valor exacto admite como máximo 3 decimales.» (F07). |
| 2 | R2-05 | menor | aplicado | `lifecycle.py:162` (`sorted(labels)`) y, además, `presentation.py:355-359` (`str(item.target)` en `by_severity`) ordenan nombres sin `.name` ni `order_by`. Van a la lista con `name_key`; el grep de B4 recorre todo `sorted(`/`.sort(`/`order_by(`; prueba «Ébano, Gravel» (F10, B4). |
| 2 | R2-06 | menor | aplicado | `installation_edit` usa `InstallationWebForm` para editar, con `started_at` guardado: la ayuda «Por defecto, ahora.» sólo en el alta; guarda `test_editing_a_mount_does_not_say_now` (F03, D12, B6). |
| 2 | R2-07 | menor | aplicado | «Sincronizar ahora» (hasta 14 llamadas y 25 s) y los atajos de posponer (un doble toque crea dos aplazamientos) no llevan `form.form`; «Continuar importación» no duplica pero gasta cuota. Marca `data-busy` en los tres; el resto de POST sin `form.form`, fuera con su motivo (F04, D14, B8). |
| 2 | R2-08 | menor | aplicado | Con un completado reciente que cubre la fecha y otro en pausa, la vista pedía confirmar algo que el servicio rechazaría. La vista mira antes los trabajos sin terminar y redirige; prueba nueva (F21, D24, B14). |
| 2 | R2-09 | menor | aplicado | Reproducido: una intercalación que falta da `ProgrammingError` (500), no un orden peor. Comprobación de sistema `garage.E001` con `databases` (la ejecutan `migrate` y `check --database default`), probada con la consulta sustituida; nota de §6 conservada (F10, D9, B4, §6). |

### 10.1 Revisiones durante la implementación

Hallazgos de las rondas de revisión de cada bloque (hasta 3; se para cuando sólo quedan
menores). Cada uno se intentó refutar reproduciéndolo antes de corregirlo.

| Bloque | Id | Severidad | Resultado | Motivo (una línea) |
|---|---|---|---|---|
| B1 | — | — | — | Ronda 1 sin hallazgos. |
| B2 | B2-R1-01 | importante | corregido | `PAIRED` de `OwnedInventoryForm._update_errors` ocultaba un error real de la moneda si el formulario rechazaba el precio («12,50» + «eur»): sólo se quita el mensaje del par. |
| B2 | B2-R1-02 | menor | corregido | Un carácter nulo en un selector de objeto seguía diciendo «Null characters are not allowed.». |
| B2 | B2-R1-03 | menor | corregido | Con una zona IANA inválida, la fecha bien escrita mostraba además «Indica la fecha y hora con su zona horaria.». |
| B2 | B2-R2-01 | menor | corregido | Crear material usado: un inicio desde adquisición mal escrito añadía «Confirma el inicio de adquisición…», que no es cierto. |
| B2 | B2-R2-02 | menor | corregido | Nueva regla: un umbral mal escrito añadía «Indica al menos un umbral…»; con km, dos errores bajo el mismo campo. |
| B2 | B2-R2-03 | menor | bloque B2b | Mensajes en inglés en formularios web fuera de la lista de D4; ya pasaba antes de B2. Ver D25 y B2b. |
| B2 | (nota) | menor | fuera | Un `select` manipulado en `UsedItemWebForm` da dos errores bajo el mismo campo; sólo alcanzable falseando el POST. Para garage-052. |
| B3 | B3-R1-01 | menor | corregido | En una base con `ctype` C, «Sustitución» y «SUSTITUCIÓN» conviven y las dos opciones decían lo mismo: con varios tipos que cuentan, cada opción lleva su nombre delante. |
| B3 | B3-R1-02 | menor | pendiente | `services/lifespan.py` (`_life_type`, `latest_replacement`) busca con `name__iexact` sin quitar espacios, distinto de `is_life_type`: con un tipo «SUSTITUCIÓN» además de «Sustitución», la ficha muestra «Vida útil» pero «Editar vida útil» no encuentra la regla. Ya pasaba antes de B3; sólo con datos crudos o una base con `ctype` C. Arreglarlo cambia el servicio de vida útil (qué tipo cuenta si hay varios): decisión del usuario en garage-052. |
| B2b | B2b-R1-01 | importante | corregido | Corregir salida: un inicio mal escrito, inexistente o repetido (cambio de hora) añadía «No puedes convertir el inicio en desconocido…», que es falso. |
| B2b | B2b-R1-02 | menor | corregido | Un valor manipulado que no es un UUID, en una casilla múltiple o en cualquier selector, decía «“abc” is not a valid UUID.»: ahora «Elige una opción válida.», en la capa común de traducción. |
| B2b | B2b-R1-03 | menor | corregido | Una modalidad que crece al pasarla a minúsculas («İ» × 150) pasaba el formulario y fallaba al guardar en inglés. Texto nuevo: «Se guarda en minúsculas y así pasa de 150 caracteres: acórtala.». |
| B2b | (textos) | — | [052] | B2b escribe textos en español que la spec no daba: «Esa fecha ya ha pasado: para fechas pasadas, elige «Aplicar explícitamente al histórico».», «La nueva versión tiene que empezar dentro de la vigencia de esta…», «Las versiones de un mismo perfil no pueden solaparse.», «Ninguna fuente aporta el inicio…», y los de archivo («No llegó ningún archivo: vuelve a elegirlo.», «El archivo está vacío.»). |
| B4 | B4-R1-01 | menor | documentado | `name_key` pone ø, ł, æ, œ, ı tras la «z» e ICU no. Se documenta la salvedad (F10) en vez de copiar reglas de ICU (D9). |
| B4 | B4-R1-02 | menor | corregido | «En uso · …» desempataba mayúsculas al revés que ICU y que Inicio: la consulta ya existente ordena por el nombre con intercalación. |
| B4 | B4-R1-03 | menor | corregido | Estadísticas, «Observado por bici», ordenaba por el UUID de la bici: ahora en orden español y «Bici desconocida» al final (elección propia, [052]). |
| B5 | B5-R1-01 | menor | corregido | Dos nombres que sólo difieren en lo invisible (dos espacios, NFC/NFD, espacio de ancho cero) se veían iguales sin fecha ni número: la comparación de etiquetas los normaliza. |
| B6 | B6-R1-01 | menor | corregido | Tras «Atrás», el navegador restauraba otra zona en el campo y el resumen «Horas en …» seguía diciendo la anterior: `garage.js` lo resincroniza en `pageshow`. |
| B6 | (nota) | — | [052] | Siguiendo D11 al pie de la letra, en «Crear material usado» la zona queda entre «Referencia…» y «Qué uso cubre esta lectura». |
| B7 | — | — | — | Ronda 1 sin hallazgos. La ayuda «Número de salidas.» se quita sólo del formulario web, no del admin. |
| B8 | B8-R1-01 | menor | corregido | «No está montado» en una pieza que sigue montada hasta una fecha posterior (bici con retirada programada). |
| B8 | B8-R1-02 | menor | corregido | Tras un POST rechazado, la explicación daba las horas en la zona de la cookie y el formulario decía otra. |
| B8 | B8-R1-03 | menor | corregido | Si se detenía la carga (Stop o Esc) durante el envío, el botón quedaba en «Guardando…» y no se podía volver a enviar sin recargar. |

### 10.2 Estado al pausar (14 nov 2026, a petición del usuario)

Hechos, con la suite completa sin fallos tras cada uno: B1, B2, B3, B2b, B4, B5, B6, B7 y
B8 (B8: 3780 passed, 696 subtests). Quedan, en este orden: **B9a, B9b, B12, B10, B11, B13
y B14**, y después la verificación final de §8 (suite, `check`, CDP de F01, F04 y F20,
capturas completas, y F19 y F23 en capturas).
