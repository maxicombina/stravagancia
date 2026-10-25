# Especificación garage-041: juego inicial de categorías con icono

Fecha: 18 de octubre de 2026. Autor: Claude (Fable 5.1). Tarea Beads: `garage-041`.
Pedido del usuario: «en material me faltan muchas categorías» → «juego inicial de
categorías. me gusta que tengan su icono y tal» → «andá haciendo, sí, con tests».
Rama `codex/garage-plan`; sin commits. **Una migración aditiva** (`AddField`).

## 1. Punto de partida

Las categorías son libres y por usuario (`Category`: nombre, notas, archivada).
Una cuenta nueva arranca sin ninguna, y crear un componente exige categoría. El
icono de cada objeto se deduce por palabras clave del nombre de la categoría y
del objeto (`garage_ui.ICONS` → `_icons.html`): hay once iconos de material
(cadena, cubierta, rueda, freno, casete, sillín, zapatilla, casco, luz, pieza,
bici). No hay forma de elegir el icono.

## 2. Decisiones

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Icono | a) seguir deduciéndolo por nombre; b) campo `icon` en la categoría, elegido al crearla, con el nombre como sugerencia | **b)**: es lo que pide el usuario («que tengan su icono»); la deducción por nombre queda como valor por defecto y como respaldo para categorías antiguas sin icono. Los objetos heredan el icono de su categoría; el nombre del objeto sólo afina si la categoría no tiene icono. |
| Cuándo se crea el juego | a) al crear la cuenta; b) botón explícito | **b)**: botón «Crear las categorías habituales» en Categorías (y en la pantalla vacía de Material). Idempotente: sólo crea las que no existan (sin distinguir mayúsculas); dice cuántas creó y cuántas ya tenía. Nunca borra ni renombra. |
| Qué juego | — | Ver §3. Nombres en singular, en español, los que ya reconocen los iconos cuando los hay. |
| Iconos nuevos | — | Símbolos SVG en el sprite (`_icons.html`) de 24×24, línea, mismo estilo: platos, bielas, pedalier, desviador, maneta, cable, cámara, buje, llanta, radio, pinza, horquilla, dirección, potencia, manillar, puños, tija, pedal, cala, amortiguador, gafas, guantes, ciclocomputador, sensor, batería, bidón/portabidón, bolsa, herramienta. Donde no haya símbolo propio, uno genérico («pieza»). |
| Elegir icono | — | En el formulario de categoría, una rejilla de iconos con nombre (botones de radio con `aria-label`, sin JavaScript), sugerido por el nombre. |

## 3. Juego inicial (grupo sólo para ordenar la pantalla)

- **Transmisión**: Cadena (chain), Casete (cassette), Platos (chainring),
  Bielas (crank), Pedalier (bottom_bracket), Desviador trasero (derailleur),
  Desviador delantero (derailleur), Manetas de cambio (shifter), Cables y
  fundas (cable).
- **Ruedas**: Rueda (wheel), Cubierta (tire), Cámara (tube), Buje (hub), Llanta
  (rim), Radios (spoke), Líquido sellante (sealant).
- **Frenos**: Pastillas (brake), Discos (disc), Pinzas (caliper), Manetas de
  freno (brake_lever).
- **Dirección y postura**: Horquilla (fork), Dirección (headset), Potencia
  (stem), Manillar (handlebar), Puños o cinta (grips), Tija (seatpost), Sillín
  (saddle).
- **Suspensión**: Horquilla de suspensión (suspension_fork), Amortiguador
  (shock).
- **Pedales**: Pedales (pedal), Calas (cleat).
- **Equipación**: Casco (helmet), Zapatillas (shoe), Gafas (glasses), Guantes
  (gloves), Luces (light), Ciclocomputador (computer), Sensores (sensor),
  Batería (battery), Bidón y portabidón (bottle), Bolsas (bag), Herramientas
  (tool).

## 4. Modelo y migración

`Category.icon`: `CharField(max_length=32, blank=True, default="")`, con CHECK
`icon = '' OR icon ~ '^[a-z_]+$'` y validación contra la lista de iconos
(`garage/icons.py`: `ICON_CHOICES` con clave, nombre en español y palabras
clave). Migración `0011_category_icon` (`AddField` + CHECK; sin datos).
`item_icon(item)`: icono de la categoría si lo tiene; si no, deducción por
nombre como hoy. Exportación: columna `icon` en `categories` (aditiva, doc).

## 5. Servicio y pantallas

- `services/categories.py`: `STARTER` (grupo, nombre, icono),
  `create_starter_categories(actor)` bajo el bloqueo del propietario; devuelve
  creadas y existentes; `suggest_icon(name)`.
- Categorías: botón «Crear las categorías habituales» (POST) con el número que
  faltan; mensaje «Creadas N categorías; M ya existían». Lista con icono.
- Material vacío y el formulario de objeto sin categorías: el mismo botón.
- Formulario de categoría: rejilla de iconos (radio), sugerencia por nombre.
- Iconos nuevos en el sprite; `item_icon` y las listas los usan.

## 6. Pruebas

Idempotencia y mayúsculas, propiedad (no toca a otros usuarios), bloqueo,
`icon` válido/ inválido, sugerencia por nombre, `item_icon` con y sin icono de
categoría (compatibilidad con las pruebas existentes), formulario y rejilla,
botón en Categorías y Material, exportación, migración, GET sin escrituras,
presupuestos de consultas de las listas. Suite completa, `check`,
`makemigrations --check`, capturas y revisión independiente.

## 7. Revisión de código (18 oct 2026)

Revisión independiente sin bloqueos: un hallazgo importante y seis menores.
Todos corregidos, cada uno con su prueba. `garage/tests_categories.py` pasa de
52 a 77 casos.

1. **Importante. «Según el nombre» congelaba la sugerencia.** `CategoryWebForm.clean`
   guardaba `suggest_icon(nombre)`, y el formulario de edición preseleccionaba
   esa sugerencia en las categorías antiguas. Bastaba editar las notas de
   «Ruedas» para guardar `wheel`. Desde entonces, una «Cubierta GP5000» de esa
   categoría pasaba a mostrar «Orientativo para una rueda: unos 20.000 km».
   Ahora «Según el nombre» siempre guarda `''`, que se deduce cada vez (el
   respaldo del §4). Las categorías sin icono abren el formulario con esa opción
   marcada, y su casilla dibuja el icono que el nombre sugiere en ese momento,
   con `aria-label` «Según el nombre (Rueda)». Las mixtas, como «Ruedas y
   cubiertas», dejan que cada objeto se afine por su nombre. Pruebas:
   `test_editing_only_the_notes_of_an_older_category_changes_no_icon`,
   `test_by_name_stores_nothing_and_each_item_refines` y
   `test_older_category_keeps_by_name_checked_with_its_glyph`.
2. **«Te faltan 1».** Ahora dice «Te falta 1 de las 42 habituales». Ampliada
   `test_categories_list_offers_it_with_the_missing_count`.
3. **Foco de la rejilla.** Cada radio va dentro de su propio
   `<span class="tile">` (`position: relative`), con el input `inset: 0` sobre
   su casilla. Medido en Chrome sin interfaz: 44 de 44 inputs coinciden con su
   etiqueta. «Categorías habituales» pasa de `<h3>` a `<h2>`, con el mismo
   tamaño. Pruebas: estructura en `test_grid_of_radio_icons`, reglas en
   `test_grid_inputs_sit_over_their_own_tile` y `<h2>` en la prueba de la lista.
4. **Alta o edición.** El formulario distingue alta y edición con
   `self._resource_id is not None` (`form.editing`), no con `instance.pk`, que
   siempre tiene valor por el `uuid4`. Prueba:
   `test_new_and_edit_forms_are_told_apart_by_the_resource_id`.
5. **Clave retirada de la lista.** Si la clave guardada ya no está en `ICON_KEYS`,
   el formulario marca «Según el nombre». Además, `IconGrid.value_omitted_from_data`
   devuelve `False`: un grupo sin nada marcado equivale a `''`, nunca a conservar
   la clave guardada. El error del modelo (`invalid_icon`) se muestra en español
   en el formulario web; el modelo sigue en inglés, como el resto de sus mensajes.
   Pruebas: `test_a_key_no_longer_offered_never_blocks_an_edit` y
   `test_model_rejection_of_a_key_is_shown_in_spanish`.
6. **Concurrencia y documentación.**
   - `test_two_simultaneous_starter_clicks_create_each_category_once`: dos hilos
     con barrera dan exactamente (42, 0) y (0, 42).
   - `test_starter_waits_for_a_manual_create_with_other_case`: es determinista.
     «CADENA» se crea bajo el bloqueo y sólo se confirma cuando
     `pg_stat_activity` muestra al juego inicial esperando. Resultado: 41
     creadas y «Cadena» existente.
   - `docs/garage-domain.md` documenta `icon`, su CHECK, el significado de `''`
     y la precedencia.
   - `docs/garage-handoff.md` avisa de que 0009–0011 sólo existen en local.
     `CLAUDE.md` («Retomar ahora») no se ha tocado, porque este encargo lo
     prohibía: hay que actualizarlo aparte.
7. **Cambio respecto a «como hoy».**
   - Los empates en la deducción ya no los decide el orden del catálogo, sino la
     posición: gana la palabra escrita antes, que en español es el núcleo. Así,
     «Llave de radios» da herramienta y «Radios de rueda» da radios. Las palabras
     clave son únicas, cosa que se comprueba al importar. (La re-verificación,
     §8, quitó la preferencia por la palabra más larga: ahora manda la posición.)
   - La deducción nueva (primero el nombre del objeto, con los iconos nuevos) es
     un **cambio visible que debe confirmar el usuario**. Ejemplos: «Disco» en
     «Frenos» pasa de freno a disco, «Llanta» de rueda a llanta, «Plato» de
     casete a platos, «Calas» de zapatilla a calas y «Cámara» en «Cubiertas» de
     cubierta a cámara. Lo fija `test_change_from_the_pre_041_deduction`.
   - Vida útil orientativa. Opciones: a) ninguna para las claves nuevas; b) la
     de la familia antigua; c) cifras propias del usuario. **Elegida:** la llanta
     conserva la de la rueda (mismo texto que antes, `SUGGESTIONS["rim"]`).
     Disco, platos, calas y cámara se quedan sin cifra, porque la que heredaban
     nombraba otra pieza: «Usar» ponía 1.500 km de pastillas a un disco. Lo fija
     `test_lifespan_hint_follows_the_deduced_icon`.
   - «Funda para casco» daba cables, porque «funda» a secas estaba en el
     catálogo como funda de cable (homónimo). La re-verificación (§8) retiró esa
     palabra suelta: quedan «funda de cambio/freno/cable».

Comprobaciones finales:
- Suite completa: **2278 pruebas y 45 subcasos pasan** (125 s).
- `check`: sin problemas.
- `makemigrations --check --dry-run`: «No changes detected».
- `inspect`: 0 filas.
- Mutaciones: cada una hace fallar al menos una prueba nueva.
  - Volver a congelar la sugerencia.
  - Quitar el bloqueo del juego inicial. También falla la prueba de orden SQL.
  - Desempatar por el catálogo.
  - Usar `instance.pk`.
  - Conservar la clave omitida.
  - Quitar la traducción.
  Los archivos se restauraron con hash idéntico.
- Capturas a 390 px en claro y oscuro, con el cliente de pruebas y Chrome sin
  interfaz, sin servidor ni base de demo.

## 8. Re-verificación (18 oct 2026)

Verificador independiente (Opus): los siete hallazgos del §7 quedan
comprobados en el código y en la suite (2278 + 45). Señaló dos menores nuevos
en la deducción por nombre, corregidos por el orquestador (Fable) en
`garage/icons.py` con sus pruebas en `TestSuggestion`:

1. **La palabra más larga ganaba al núcleo.** «Llave de cadena» daba cadena (y
   ofrecía «unos 3.000 km» a una herramienta), «Bolsa de sillín» sillín, «Luz de
   casco» casco. Ahora gana la palabra escrita antes; la longitud sólo desempata
   a igual posición («Horquilla de suspensión», «Manetas de cambio»). Efecto:
   «Ruedas y cubiertas» sugiere rueda (antes cubierta); cada objeto se sigue
   afinando por su nombre.
2. **Coincidencia dentro de otra palabra.** «Chubasquero» daba buje (hub),
   «Recambios» desviador (cambio), «Escalador» calas, «Discreto» disco (disc).
   Ahora las palabras clave casan como palabra completa, admitiendo un plural
   («Cadenas», «Pedales», «discs»; no «disco» para «disc»). Por eso «neum» pasa
   a «neumatico» y desaparece «funda» suelta (cualquier funda): «Funda para
   casco» da casco y «Fundas de freno» cables.

También pendiente del verificador: `CLAUDE.md` («Retomar ahora») nombraba sólo
la 0009 y la suite de 2068; lo actualiza el orquestador. Suite completa tras
estas correcciones: ver `docs/validation/garage-041.json`.
