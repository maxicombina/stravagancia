# Garage · Estilo «Anillos» (opción 1) en la app (1 nov 2026)

> **Estado: revisión aplicada a medias (comprobado el 3 nov 2026). No está lista
> para que el usuario decida.** El borrador (inventarios en
> `~/.cache/stravagancia/session-2026-11-01/anillos-spec-inventarios.md`) pasó la
> revisión adversarial de un agente Opus: 29 hallazgos (1 alto, 10 medios y 18
> bajos). El agente que los aplicaba editó de arriba abajo y **se cortó por un
> error de la API** (última edición 1 nov 22:01 UTC; fallo 2 nov 04:27 UTC) justo
> después de F1a. **Revisado:** §1–§5, §6.0, F0 y F1a. **Sin aplicar:** F1b en
> adelante, §7 y §8, incluido R1, el único alto: §8.2 todavía contradice esta
> cabecera y §8.1 está desfasada. La lista de hallazgos está literal en §9, todavía
> sin veredictos. **Rige la regla más estricta: ninguna fase visible (F1a en
> adelante) se implementa antes de que el usuario responda §8.1, ni siquiera en
> la copia aparte de §6.0.** Antes de eso sólo F0 y la preparación.

Especificación para llevar a la app la dirección visual que eligió el usuario:
la maqueta `design/option-1/index.html`, con su README `design/option-1/README.md`.
La comparación entre las tres opciones está en `design/README.md`.

Esta fase es sólo de análisis: no se ha tocado código, plantillas, CSS, pruebas,
Beads ni git, y no se ha arrancado nada. Las cifras de contraste de §3 se han
**recalculado** con la fórmula WCAG 2.x (36 pares, 0 fallos) y las afirmaciones
sobre el código se han comprobado leyéndolo.

**Rutas.** Las que llevan carpeta son relativas a la raíz del repositorio. Las
que no: los `tests_*.py`, `presentation.py`, `views.py`, `photo_views.py`,
`app_views.py`, `assets.py`, `icons.py`, `urls.py` y `photos.py` están en
`garage/`; `home.py`, `workshop.py`, `lifecycle.py` y `maintenance_due.py`, en
`garage/services/`; `garage_ui.py`, en `garage/templatetags/`; `garage.css` y
`garage.js`, en `garage/static/garage/`; las plantillas (`*.html`, `sw.js`), en
`garage/templates/garage/`. En la raíz hay otros `tests_*.py`
(`tests_local_strava*.py`) que esta spec no cita.

**Sin migración.** Ninguna fase la necesita. Si alguna llegara a necesitarla,
sería la `0013`, sólo aditiva y sólo local; ver §7.

---

## 1. Objetivo y decisión del usuario

Decisión del 1 nov 2026, literal: **«hagamos a, la 1 (anillos)»**.

- **«la 1 (anillos)»**: la opción 1 de `design/`. Su idea es que cada pieza
  lleva un anillo de desgaste con el icono de la pieza y que el color del
  estado dice qué toca, siempre acompañado de icono y palabra. Tiene una paleta
  violeta sobre papel cálido, fuentes Outfit y Figtree, tarjetas, una barra de
  pestañas flotante y una barra lateral en escritorio.
- **«a»**: se interpreta como la pregunta anterior del usuario, **la foto de la
  bici** (ver D1). Se incorpora a la **cabecera de la ficha de la bici**:
  - si la bici tiene foto, se muestra la foto;
  - si no, una tesela con el icono de bici y el enlace «Añadir foto».

  El código de fotos privadas ya existe (`garage/services/photos.py`,
  `garage/photo_views.py`, `photo_list.html`), pero **las fotos reales dependen
  de garage-010**, porque el bucket y la credencial siguen pendientes. Hasta
  entonces `photo-content` responde 503 (`photo_views.py:55-61`) y en la demo
  no hay fotos, así que lo que se verá es la tesela.
- **Pieles (skins):** el usuario preguntó si la app podría tener varias, pero
  no lo ha confirmado. Se deja la estructura preparada, con los tokens
  agrupados por tema y los componentes usando sólo variables, **sin selector
  de pieles** (D12).

**Qué no cambia:** el dominio. Los estados, las palabras, los umbrales, «≥»,
«≈» y Pospuesto los sigue decidiendo `garage/presentation.py:11-26` y los
servicios. La maqueta es ilustrativa: sus datos inventados no mandan sobre el
significado. Por ejemplo, su «En curso · 71 %» sin «≥» contradice la app.

---

## 2. Supuestos tomados sin preguntar

Cada supuesto lleva la alternativa descartada. Los marcados **[confirmar con el
usuario]** son ambiguos o visibles para él.

**D1 · «a» es la foto de la bici en su cabecera.** [confirmar con el usuario]
- *Alternativa descartada:* leer «a» como «la primera variante» de algo de la
  maqueta. La maqueta no tiene variantes a/b, y la última pregunta del usuario
  fue la foto.

**D2 · Foto de portada.** [confirmar con el usuario]
- Es la primera foto de la bici en orden de alta. `Photo.Meta.ordering =
  ("created_at", "pk")` (`garage/models.py:1150`), así que `owned_photos()` ya
  sale ordenada.
- No se añade un campo «portada», porque haría falta migración.
- La vista pasa `cover` sin consulta extra. Hoy `context['photos']` es un
  QuerySet (`garage/views.py:110`); F3b lo convierte en `list(...)` y pone
  `cover = photos[0]` si hay alguna, así la lista se evalúa una sola vez.
- Sólo para la bici. La ficha de pieza conserva la tesela con su icono.
- **Coste de la portada** (se acepta por defecto; §8.1, punto 1): `photo-content`
  responde `no-store` y redirige cada vez a una URL firmada distinta
  (`photo_views.py:52-64`), así que el navegador no la guarda. Las fotos se
  guardan hasta 2000 px de lado en WebP (`photos.py:18`, `:76`, `:125`) y no hay
  miniaturas. Cada visita a la ficha baja la imagen entera para una tesela de
  ~112 px, y otra vez la galería «Fotos privadas» si se desplaza hasta ella
  (`photo_list.html:4`, `loading="lazy"`). Hasta garage-010 no hay fotos, así
  que no cuesta nada. Si con fotos reales pesa, haría falta una tarea nueva de
  miniaturas (no existe; garage-022 es la revisión de integración).
- *Alternativas descartadas:* la foto más reciente, un campo de portada (0013) y
  la portada también en las tarjetas del Garaje (posible después, con +1
  consulta constante; §6 F3a).

**D3 · Sin foto: tesela e «Añadir foto», sin ilustraciones.**
- La tesela lleva `i-bike` sobre `--primary-soft`.
- El enlace «Añadir foto» (icono `i-camera`, que ya existe) va al mismo destino
  que `photo_list.html:2`. Sin foto habrá, por tanto, dos «Añadir foto» en la
  ficha (cabecera y sección «Fotos privadas»). Se acepta: mismo texto y mismo
  destino, y el de la cabecera es lo que pidió el usuario.
- *Alternativa descartada:* las ilustraciones SVG por tipo de bici de la
  maqueta (`svg.bike-art`, doble suspensión o gravel). `Bike` no tiene tipo
  (sólo nombre, marca, modelo y fechas), así que haría falta un campo y la 0013.

**D4 · Fuentes Outfit y Figtree autoalojadas** en
`garage/static/garage/fonts/`, con su licencia OFL junto a cada archivo.
- **Permiso dado** el 1 nov 2026 («baja, claro»; notas de garage-050). Ya están
  descargadas, fuera del repositorio, en
  `~/.cache/stravagancia/fonts-anillos/download/`, con su procedencia en
  `~/.cache/stravagancia/fonts-anillos/PROCEDENCIA.md`: URL de origen, sha256,
  pesos y `unicode-range`. Figtree latin wght 400–700 (20 184 B) y Outfit latin
  wght 500–700 (32 228 B), woff2 variables, más `OFL-Figtree.txt` y
  `OFL-Outfit.txt`. F1b las copia comprobando el sha256; no se vuelve a
  descargar nada.
- Hasta F1b, los tokens ya nombran las familias con respaldo de sistema:
  `ui-rounded` / `SF Pro Rounded` en Apple y `system-ui` en el resto.
- El subconjunto latino no trae «≥» (U+2265), «≈» (U+2248) ni «→» (U+2192):
  salen en la fuente del sistema (lo advierte `PROCEDENCIA.md`). Se revisa en
  las capturas (F1b).
- *Alternativa descartada:* Google Fonts como en la maqueta
  (`index.html:8-10`):
  - el service worker ignora otros orígenes (`sw.js:25`), así que sin red no
    habría fuentes;
  - se enviaría la IP del usuario a Google;
  - contradice `garage.css:1` («no external fonts»).

**D5 · El tema se recuerda en el navegador, no en el perfil, y se guarda en una
cookie `garage_theme`.** [confirmar con el usuario]
- La cookie vale `light` o `dark`; si no existe, el tema es automático.
- El servidor la pinta como `<html data-theme>`, igual que ya pinta `data-os`
  (`shell.html:2`, `garage_ui.py:47-51`).
- `garage.js` sólo mejora: aplica el cambio al instante y escribe la cookie,
  como ya hace con `garage_tz` (`garage.js:11-18`).
- Todo funciona sin JS, no hay parpadeo al navegar y `theme-color` sale correcto
  desde el servidor.
- *Alternativas descartadas:*
  - `localStorage`, como la maqueta y el encargo. Sin script en línea habría
    parpadeo en cada navegación, y el script en línea lo prohíbe
    `tests_mobile_shell.py:52` (12 subcasos).
  - Un script externo bloqueante en `<head>`. Cambia esa misma prueba y sigue
    dependiendo de JS.
  - Un campo en el perfil. Necesita la 0013 y el tema seguiría al usuario entre
    dispositivos.
- La cookie es del navegador: en iOS, la app instalada guarda sus cookies
  aparte de Safari, así que el tema se elige en cada una (§4.8).
- La descripción de garage-050 en Beads dice «tema en localStorage». Fable la
  corrige cuando el usuario confirme D5.

**D6 · El tema se elige en Más → Apariencia.** [confirmar con el usuario]
- Opciones: Automático, Claro y Oscuro, en un formulario POST que funciona sin
  JS.
- **No hay botón de tema en cada barra superior.**
- *Alternativa descartada:* el botón de la maqueta en cada pantalla. El
  inventario de la maqueta lo marca como sólo de maqueta. Cuesta un botón de
  44 px en cada barra, impide que la barra se pliegue a 6 px
  (`garage.css:58-59`) y duplica el control.

**D7 · Vocabulario: se mantienen «Próximo» y «quedan».** [confirmar con el
usuario]
- Están en `presentation.py:14` y `:195`, y son los que usan el dominio y las
  specs.
- La maqueta usa «Pronto» y «faltan». Cambiarlo sería un cambio aparte, **no
  de una línea**. Toca:
  - `STATES["soon"]` (`presentation.py:14`) y el texto «quedan» (`:195`);
  - `LABELS` (`maintenance_due.py:18`), que pone «Próximo» en los detalles
    técnicos (`maintenance_alerts.html:5`, `alert.label`). Ahí el estado al día
    se llama «Vigente», no «Al día»: es una diferencia anterior a esta spec y
    queda fuera de alcance;
  - las notas fijas `index.html:45`, `maintenance.html:13` y
    `maintenance_alerts.html:3`;
  - las frases en minúscula `maintenance.html:10` y `bike_detail.html:23` («lo
    vencido o próximo»). No pueden tomar la palabra de `STATES`, porque con
    «Pronto» quedaría «lo vencido o pronto»: habría que reescribirlas;
  - la prueba `tests_mobile_home.py:81` («km quedan»).
- Esta spec no centraliza el vocabulario: F2b ya no mueve las notas a `STATES`.

**D8 · «Revisar» pasa a la lupa.** [confirmar con el usuario]
- Se dibuja el símbolo nuevo `i-search`: `presentation.py:13` pasa de `alert`
  a `search`.
- Hoy «Revisar» comparte el triángulo con «Próximo», así que el icono no
  distingue los dos estados.
- También pasa a la lupa la tesela de la fila «Sin bici · revisar» de
  Estadísticas (`statistics.html:43`, hoy `#i-help`). Es una fila `st-review`
  que lleva a la misma lista que la de Garaje (`?pending=1`).
- **No cambian** los avisos `.pending st-review` con `#i-alert`
  (`strava.html:6`, `:8`, `:18`, `form.html:5`, `lifespan.html:21`,
  `usage_ride.html:8` y `ride_review.html:24`). Son avisos genéricos en ámbar,
  no el estado «Revisar» de una regla o una salida.
- *Alternativa descartada:* mantener `alert`.

**D9 · Cómo se ve una fila de regla.** [confirmar con el usuario]
- **Anillo con el icono de la pieza**:
  - el de la bici si es una regla de bici;
  - 52 px, radio 22 (`SMALL_RING`) y trazo 6;
  - lleno al llegar al 100 %, como hoy (`presentation.ring`, `:68-72`).
- **Chip «palabra · porcentaje»**: «Revisar · ≥ 95 %», «Vencido · 116 %».
  - Lleva «≥» y «≈» a la vista.
  - Muestra el exceso por encima del 100 %, que el anillo no dibuja.
- **Se conserva la columna `.big`** con la cifra humana: «+8 h de más», «150 km
  como máx.».
- **Depende de otra confirmación pendiente.** El icono del centro es el que
  deduce `icons.item_icon_key` (categoría, luego nombre). El usuario aún no ha
  confirmado el «cambio visible» de esa deducción (spec 041 §7.7–§8;
  CLAUDE.md, «Retomar ahora», punto 2), y con F2a ese icono pasa a verse en
  cada fila. Por eso entra en §8.1, punto 3.
- *Alternativa descartada:* la frase de la maqueta dentro del chip («Vencido ·
  8 h de más») y sin columna `.big`. O pierde «≥» y «≈» a la vista, o repite la
  cifra en dos sitios, y la fila se alarga.

**D10 · Se mantiene la estructura de pantallas del dominio.** [confirmar con el
usuario]
- **Taller:** sus cuatro grupos (Requiere atención, Pospuestos, Sin datos, En
  curso y al día; `workshop.py:58-62`) en su orden actual.
- **Ficha de bici:** «Requiere atención» separada de «Montado ahora».
- **Sin zonas** (Suspensión, Transmisión…): el modelo no las tiene.
- *Alternativas descartadas:*
  - un grupo por estado en el orden de la maqueta (Vencido, Pronto, En curso,
    Al día, Sin datos);
  - zonas deducidas de los grupos de iconos de `icons.py`.

**D11 · Una sola piel para iOS y Android.** [confirmar con el usuario]
- `data-os` se queda sólo para lo funcional:
  - FAB en Android y «+» en la barra en iOS;
  - atrás con flecha o con chevron y texto (`_back.html:1`);
  - instrucciones de instalación (`more.html:29-30`);
  - `Vary` de la página sin conexión.
- **Se quitan 11 líneas estéticas**: `garage.css:64, 72, 192, 221-224,
  252-255`.
- **Se conservan 6**: `:46, 50, 58-59, 193, 198`, incluida la del FAB que lee
  `tests_mobile_shell.py:74`. Sólo declaran `display`, `height` y
  `padding-bottom`.
- Como 221-224 son el interruptor y 252-255 la barra de pestañas, F2e se hace
  **antes** que F2c y F2d (§6). Si no, entre fases, en Android la línea 255
  pintaría la pastilla activa en `--primary-soft` sobre la barra (1,21:1), que
  la maqueta descartó (README:129-130).
- *Alternativas descartadas:* mantener las 17 líneas, o quitar `data-os` del
  todo (rompe `tests_mobile_shell.py:71-85`).

**D12 · Pieles: estructura preparada, sin selector.**
- Todos los tokens van en un bloque por tema al principio de `garage.css`: claro
  en `:root` y oscuro en las dos copias de §3.
- Los componentes sólo usan `var()`, y una prueba prohíbe colores literales
  fuera de ese bloque.
- Una piel futura serían **tres** bloques más, escritos **después** de los de
  la base y con todos los tokens: `:root[data-skin="x"]` (claro, 0,2,0),
  `@media (prefers-color-scheme: dark) { :root[data-skin="x"]:not([data-theme="light"]) }`
  (0,3,0) y `:root[data-skin="x"][data-theme="dark"]` (0,3,0). El bloque claro
  de la piel empata en especificidad con el oscuro de la base
  (`:root:not([data-theme="light"])`, 0,2,0), así que el orden es parte del
  patrón: los dos oscuros de la piel, más específicos, la vuelven a dejar bien
  en oscuro. La prueba de paridad tendría que cubrir cada piel. Hoy no se pinta
  `data-skin` ni hay selector.
- *Alternativas descartadas:*
  - `light-dark()`, que evitaría duplicar el bloque oscuro, pero en
    navegadores antiguos deja la app sin colores;
  - pintar ya `data-skin="anillos"`, que no sirve para nada sin una segunda
    piel.

**D13 · Escritorio: desde 1000 px, la misma `<nav class="tabbar">` pasa a ser
una barra lateral de 248 px, sólo con CSS.**
- Encima va la marca «Garage», sin enlace y oculta en móvil, y el contenido se
  ensancha hasta 1080 px.
- *Alternativa descartada:* una segunda navegación en `base.html`. Rompe
  `tests_mobile_shell.py:34-37` (`current_tab`), que exige un único `<a
  class="tab" … aria-current="page">` en los 11 subcasos de
  `test_active_tab_follows_the_section` (`:54-61`), y duplica enlaces para los
  lectores de pantalla.

**D14 · Gráfico: se mantiene el de línea actual** (`charts.py`, `_chart.html`,
navegable con flechas en `garage.js:55-81`) con los colores nuevos. [confirmar
con el usuario]
- *Alternativa descartada:* las barras CSS de la maqueta. Necesitan
  `style="--h:…"` en línea, que prohíben 8 pruebas (§7), y no reciben foco.
  Además habría que cambiar `charts.py`, `_chart.html` y el JS.

**D15 · Se conservan los nombres de clase de la app y se les cambia el
estilo.** Son `entry`, `entry-name`, `entry-sub`, `glyph`, `chip`, `chip-link`,
`st-progress`, `st-current`, `stats`, `panel`, `card`, `gauge`, `timeline`,
`menu` y `tabbar`.
- **No se importan de la maqueta** clases que chocan con otras de la app:
  - `.row`, con `.page .row` (`garage.css:261`);
  - `.tile`, con `.choice.icons .tile`, que lee `tests_categories.py:322-328`;
  - `.badge`, con `.page .badge`;
  - `.bar`, con el medidor SVG `.bar` (`garage.css:296`);
  - `.ring-ic`, el círculo de 52 px de la fila «salidas por revisar»
    (`garage.css:113`, `index.html:19`). Por eso el `<use>` del centro del
    anillo lleva una clase propia, `ring-glyph` (§4.1): si llevara `ring-ic`,
    su `width`/`height` de 52 px, que en SVG 2 son propiedades geométricas
    también del `<use>`, anularían el 24×24.
- Las clases de estado se quedan como están. `.st-ok` sigue como alias de
  `.st-current`.
- Se mantiene `@view-transition` (`garage.css:22-24`). No se añaden la
  animación `rise` ni la navegación con `:target` de la maqueta.

**D16 · Token propio `--danger-ink` para el texto de error y los botones de
borrar** (`.errorlist`, `.btn.danger`, `.link-btn.danger`).
- Hace falta porque `--due` como texto sobre `--bg` da **4,49:1** en claro, por
  debajo de 4,5 (recalculado).
- Valores: `#B42318` en claro (5,93:1) y `#FF7B72` en oscuro (7,43:1).
- La regla de la maqueta «el texto nunca usa el color del estado» se refiere a
  los estados de mantenimiento. Un error de formulario no lo es.

**D17 · Insignia de la bici en el Garaje.**
- Dice «N avisos» con el icono y el color del estado más grave de esa bici. Para
  eso se añade el campo calculado `HomeBike.worst`, en el mismo bucle de
  `home.py:122-127`, sin consulta extra.
- Como el icono es `aria-hidden` y la palabra es un recuento, la gravedad va
  también en texto oculto: «2 avisos<span class="sr-only">, el más grave:
  Vencido</span>», con la palabra de `STATES`.
- La insignia sustituye al sufijo « · N avisos» de la línea secundaria
  (`index.html:55`; ninguna prueba lo fija), para no decirlo dos veces.
- Con 0 avisos dice «Sin avisos», en un chip neutro.
- *Alternativa descartada:* «Todo al día» en verde, como la maqueta. `alerts`
  sólo cuenta lo que requiere atención (`home.py:124-127`), así que una bici con
  reglas Sin datos o Pospuestas saldría «al día» sin estarlo.

**D18 · Iconos PNG de la app y del manifiesto: siguen en cobalto `#2450d6`
hasta que el usuario lo pida.** [confirmar con el usuario]
- Están en `tools/garage_icons.py:70-75`.
- Pasarlos al violeta `#5536C8` es la fase opcional F4d. Cambia el icono de la
  pantalla de inicio del teléfono.

**D19 · Ciclo de vida.**
- El chip neutro con icono de la maqueta va **sólo en la cabecera de la ficha de
  pieza**, con los iconos nuevos `i-box`, `i-user`, `i-archive` e `i-sparkle`.
- **Sus palabras** («Montado», «Disponible», «Sin estrenar», «En uso» y
  «Retirado») van en constantes nuevas de `lifecycle.py`, que su docstring
  declara única fuente de los estados y sus palabras (`lifecycle.py:5-7`). Hoy
  no hay una constante «Montado» (el texto se forma con la bici, `:139`, `:144`)
  y `RETIRED_TEXT` es «Retirado el», que necesita fecha (`:28`).
- La `.lede` sigue con la frase completa (`life_text`, con fecha). El chip es su
  resumen de una palabra, así que el lector de pantalla oye la palabra dos
  veces. Se acepta.
- **Excepción documentada:** en la lista de Material, «Retirado» sigue siendo el
  chip gris sin icono (`list.html:19`). En la cabecera es el chip de ciclo de
  vida, con icono. Los dos son grises; cambia sólo el icono.
- En la lista de Material se mantienen:
  - la línea de texto `life_text`;
  - el chip gris «Retirado» (R042-6; lo fijan `tests_lifecycle.py:277` y
    `tests_mobile_lists.py:54`);
  - los filtros del servidor con «Todos» al final (`lifecycle.py:22`).
- *Alternativa descartada:* agrupar Material en tarjetas por estado con filtros
  hechos en CSS, como la maqueta. Contradice la spec 042 §2.

**D20 · El orden de las fases lo fija esta spec (§6); cuándo empieza y cómo se
aprueba, el usuario.**
- Cada fase la implementa un agente Opus con pruebas primero, sin commits.
- **Todo garage-050 se hace en una copia aparte** (worktree con la rama
  `garage-050-anillos`, sin push) y se ve en su propio servidor, **8768**, contra
  la misma base demo 55433 (§6.0). La demo **8766 no cambia** hasta que el
  usuario apruebe: es la que usa para dar feedback (garage-047) y para Strava
  con `maxi`, y `runserver` sirve plantillas y CSS del árbol de trabajo, así
  que cada fase a medias le cambiaría la interfaz.
- Las capturas se hacen sólo con el usuario ficticio `demo`, en 8768, y se
  guardan fuera del repositorio.
- Cuándo empieza respecto a garage-047 y cómo da el «vale» el usuario.
  [confirmar con el usuario] (§8.1, punto 8).
- *Alternativa descartada:* una sola entrega grande. Viola «una cosa por
  cambio» y hace imposible revisarla. *Y también:* implementar en el árbol
  principal con la 8766.

---

## 3. Tokens

### 3.1 Tabla, claro y oscuro

Son los tokens de la maqueta (`design/option-1/index.html:16-25` y README:60-75),
más los propios de la app, marcados con ★.

| Token | Uso | Claro | Oscuro | Sustituye a (app hoy) |
|---|---|---|---|---|
| `--bg` | fondo de pantalla y barra superior opaca | `#F5F3EF` | `#131118` | `--bg` |
| `--surface` | tarjetas, barra de pestañas, campos | `#FFFFFF` | `#1D1A23` | `--surface` |
| `--surface-2` | teselas `.glyph`, cifras, chips neutros, `.count`, carril de Apariencia, `.btn.ghost` | `#EFEBE4` | `#29252F` | `--tile` |
| `--line` | separadores (decorativos) | `#E4DFD7` | `#2F2B37` | `--line` |
| `--ink` | texto principal; icono del centro del anillo | `#1C1A21` | `#F3F1F6` | `--ink` |
| `--ink-2` | texto secundario, pestañas inactivas, chevrones | `#5D5866` | `#B3ADBD` | `--ink2` |
| `--field` | borde de campos (1,5 px) | `#8C8694` | `#7F7889` | `--line` en campos |
| `--primary` | marca, enlaces, botón principal, «En curso», pestaña activa, línea del gráfico | `#5536C8` | `#B6A2FF` | `--accent` |
| `--on-primary` | texto e icono sobre `--primary` | `#FFFFFF` | `#1B1035` | `--on-accent` |
| `--primary-soft` | tesela sin foto, mensajes, aviso de instalación, pista de «En curso», «Sin estrenar» | `#ECE6FD` | `#2D2550` | `--accent-soft` |
| `--focus` | anillo de foco de 3 px | `#C2410C` | `#FF9A5C` | `--focus` |
| `--due` / `--due-soft` | Vencido: arco e icono / fondo del chip y pista | `#D2312F` / `#FCE4E2` | `#FF7B72` / `#3D1F22` | `--due`, `--due-i` / `color-mix` |
| `--soon` / `--soon-soft` | Próximo y Revisar | `#B86200` / `#FFEFD2` | `#F2B13B` / `#3A2B12` | `--soon`, `--soon-i` |
| `--ok` / `--ok-soft` | Al día | `#1E8449` / `#DDF3E5` | `#4FCB83` / `#15301F` | `--ok`, `--ok-i` |
| `--nodata` / `--nodata-soft` | Sin datos y Pospuesto | `#7A7482` / `#EEEBF0` | `#A29CAB` / `#2A2730` | `--ink2` en estados |
| ★ `--danger-ink` | texto de error, botón de borrar (D16) | `#B42318` | `#FF7B72` | `--due-i` |
| ★ `--knob` | botón del interruptor `.sw` **apagado**, sobre su carril en `--field`. Encendido, el botón va en `--on-primary` sobre `--primary` | `#FFFFFF` | `#FFFFFF` | literal `#ffffff` (`garage.css:218`) |
| ★ `--knob-shadow` | sombra del botón del interruptor. Sustituye a `0 2px 4px var(--shadow)` (`garage.css:218`), que sería inválida con `--shadow` como lista | `0 1px 3px rgba(28,26,33,.30)` | `none` | — |
| `--shadow` | sombra de tarjeta | `0 1px 2px rgba(28,26,33,.06), 0 10px 24px -14px rgba(28,26,33,.22)` | `none` | `--shadow` (era sólo un color; sus otros usos, `:197` y `:218`, pasan a `--shadow-float` y `--knob-shadow`) |
| ★ `--shadow-float` | barra flotante y FAB | `0 10px 30px -10px rgba(28,26,33,.35)` | igual | literal de la maqueta (línea 294) |
| `--card-border` | borde de 1 px de tarjetas, barra de pestañas flotante y filtros (como la maqueta, `index.html:67`, `:229`, `:294`). En oscuro es lo único que los separa del fondo: `--shadow` es `none` y `surface`/`bg` da 1,09:1 | `transparent` | `#2F2B37` | — |
| `--font-display` | títulos, nombres de bici, cifras | `"Outfit", ui-rounded, "SF Pro Rounded", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | igual | `--font` |
| `--font-body` | texto | `"Figtree", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` | igual | `--font` |
| `--num` | cifras: pasa a `var(--font-display)` con `font-variant-numeric: tabular-nums` | — | — | `--num` (monoespaciada) |
| `--r-sm/md/lg/xl/pill` | radios | 10 · 16 · 22 · 28 · 999 | igual | literales |
| `--s1…--s8` | espaciado | 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 | igual | literales |
| ★ `--nav-h` / `--nav-gap` / `--nav-space` | geometría de la barra flotante (§4.5) | 72px / 10px / `calc(var(--nav-h) + var(--nav-gap) + env(safe-area-inset-bottom, 0px))` | igual | `--tabbar: 62px` |

**Clases de estado.** Se elimina `--ci`: con la paleta nueva, el color del
estado ya llega a 3:1 como icono. Queda así:

```css
.st-due { --c: var(--due); --soft: var(--due-soft); }
.st-soon, .st-review { --c: var(--soon); --soft: var(--soon-soft); }
.st-progress { --c: var(--primary); --soft: var(--primary-soft); }
.st-current, .st-ok { --c: var(--ok); --soft: var(--ok-soft); }
.st-nodata, .st-snoozed { --c: var(--nodata); --soft: var(--nodata-soft); }
```

Los `color-mix` de `garage.css:91, 93, 108, 131, 201, 217, 297, 317` pasan a
usar `var(--soft)` o tokens. **Siempre con respaldo**: `var(--soft,
var(--surface-2))` y `var(--c, var(--primary))`. Hay medidores sin ningún
ancestro `st-*`, como la barra de reparto `.bar.share` de `statistics.html:39`.
Sin respaldo, `fill: var(--soft)` sería inválido al calcularse; como `fill` se
hereda, la pista se pintaría en negro. Hoy `.meter`, `.chip` y `.bar` ya llevan
respaldo (`garage.css:91`, `:93`, `:297`). Una prueba lo vigila (§3.3).

**Bloques de tema** (D5, D12). En F1a sólo existen `:root` y el `@media`. El
bloque forzado y la prueba de paridad llegan en F1c.

```css
:root { /* Anillos · claro */ … color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { /* Anillos · oscuro */ … color-scheme: dark; } }
:root[data-theme="dark"] { /* copia idéntica del oscuro */ … color-scheme: dark; }
```

**Fuera del CSS.** Los colores del tema aparecen también en:
- `shell.html:7-8` (`theme-color`), que pasa a `#F5F3EF` / `#131118`;
- `shell.html:9` (`color-scheme`);
- `app_views.py:32-33` (`background_color` y `theme_color` del manifiesto), que
  pasan a `#F5F3EF`.

### 3.2 Pares de contraste (AA)

Mínimos: 4,5:1 para texto y 3:1 para bordes, iconos y arcos. Formato: claro /
oscuro. Todos se han recalculado y no falla ninguno.

| # | Par | Uso | Mín. | Claro / oscuro |
|---|---|---|---|---|
| 1 | ink / bg | texto de pantalla | 4,5 | 15,54 / 16,70 |
| 2 | ink / surface | texto en tarjeta | 4,5 | 17,23 / 15,29 |
| 3 | ink / surface-2 | cifras, chips neutros | 4,5 | 14,50 / 13,37 |
| 4 | ink / primary-soft | mensajes, «Sin estrenar» | 4,5 | 14,19 / 12,55 |
| 5–8 | ink / due-soft · soon-soft · ok-soft · nodata-soft | texto de chips de estado | 4,5 | 14,22 / 13,21 · 15,20 / 12,20 · 14,79 / 12,70 · 14,58 / 13,08 |
| 9 | ink-2 / bg | entradillas, notas | 4,5 | 6,21 / 8,59 |
| 10 | ink-2 / surface | secundario en tarjeta | 4,5 | 6,88 / 7,87 |
| 11 | ink-2 / surface-2 | etiquetas de cifras | 4,5 | 5,79 / 6,88 |
| 12 | primary / bg | «atrás», enlaces | 4,5 | 6,90 / 8,56 |
| 13 | primary / surface | enlaces en tarjeta; carril encendido del interruptor | 4,5 | 7,64 / 7,84 |
| 14 | primary / primary-soft | arco «En curso» sobre su pista | 4,5 | 6,30 / 6,43 |
| 15 | on-primary / primary | botón, pestaña activa, filtro elegido, botón del interruptor encendido | 4,5 | 7,64 / 8,19 |
| 16 | primary / surface-2 | segmento elegido, barra de reparto | 3 | 6,43 / 6,86 |
| 17–18 | due / surface · due-soft | arco e icono Vencido | 3 | 4,98 / 6,80 · 4,11 / 5,88 |
| 19–20 | soon / surface · soon-soft | Próximo y Revisar | 3 | 4,39 / 9,09 · 3,87 / 7,25 |
| 21–22 | ok / surface · ok-soft | Al día | 3 | 4,72 / 8,33 · 4,05 / 6,92 |
| 23–24 | nodata / surface · nodata-soft | Sin datos y Pospuesto | 3 | 4,52 / 6,44 · 3,82 / 5,51 |
| 25 | field / surface | borde de campos; carril apagado del interruptor | 3 | 3,53 / 4,04 |
| 26–28 | focus / bg · surface · surface-2 | foco | 3 | 4,67 / 8,95 · 5,18 / 8,19 · 4,36 / 7,16 |
| ★29 | danger-ink / bg | error en un formulario sobre el fondo | 4,5 | 5,93 / 7,43 |
| ★30 | danger-ink / surface | error dentro de una tarjeta | 4,5 | 6,57 / 6,80 |
| ★31–34 | due · soon · ok · nodata / bg | anillos y chips en filas fuera de tarjeta (listas, formularios) | 3 | 4,49 / 7,43 · 3,96 / 9,93 · 4,26 / 9,10 · 4,08 / 7,03 |
| ★35 | ink-2 / primary-soft | texto secundario en mensajes y aviso de instalación | 4,5 | 5,67 / 6,45 |
| ★36 | knob / field | botón apagado del interruptor sobre su carril | 3 | 3,53 / 4,24 |

Los pares 1–28 son los de la maqueta (README:92-121). Los ★29–36 son propios de
la app, porque la app tiene filas sobre `--bg`, formularios con errores,
mensajes y el interruptor `.sw`. Con los pares 13, 15, 25 y ★36, el interruptor
cumple 3:1 en sus cuatro contrastes, en los dos temas: carril apagado y
encendido contra la tarjeta, y botón apagado y encendido contra su carril.
**Descartados:**
- `--due` como texto de error, que da 4,49 sobre `--bg` (D16);
- el botón blanco sobre `--primary` en oscuro, que da 2,19:1 (recalculado);
- el carril apagado en `--surface-2`, que da 1,19:1 contra la tarjeta.

### 3.3 Cómo se verifica en la app

1. **Módulo nuevo `test_support/contrast.py`**, en Python puro y sin
   dependencias. Hace cinco cosas:
   - lee `garage/static/garage/garage.css`;
   - extrae los tres bloques de tokens;
   - calcula la luminancia relativa WCAG;
   - comprueba los 36 pares anteriores;
   - imprime la tabla cuando se ejecuta como
     `python -m test_support.contrast garage/static/garage/garage.css`.
2. **Prueba nueva `garage/tests_theme_tokens.py`**, que lo usa dentro de la
   suite:
   - `test_pairs_meet_wcag`: 36 pares × 2 temas = **72 comprobaciones**, como
     subcasos;
   - `test_dark_blocks_are_identical`: compara el `@media` oscuro con
     `[data-theme="dark"]`, token a token (≥ 21 tokens de color, 1 aserción con
     la diferencia). Llega en F1c;
   - `test_no_literal_colors_outside_tokens`: busca `#hex`, `rgb(`, `rgba(` y
     `hsl(` fuera de los bloques de tokens. La lista resultante debe estar vacía
     (1 aserción). Es la garantía de D12;
   - `test_state_classes`: las 7 clases `st-*` fijan `--c` y `--soft` **con
     los tokens cuyos pares se comprueban** (por ejemplo, `.st-due` con
     `--due`/`--due-soft`; 7 subcasos × 2 aserciones). No refleja la
     implementación por gusto: es lo que une la tabla de contraste con lo que
     se pinta. Si `.st-due` usara otro token, los 72 pares no dirían nada;
   - `test_state_vars_have_fallback`: en `garage.css` no hay ningún
     `var(--c)` ni `var(--soft)` sin respaldo (1 aserción con la lista; R8);
   - `test_theme_color_matches_bg`: las `meta theme-color` de `shell.html` y los
     colores del manifiesto coinciden con `--bg` claro y oscuro (4 aserciones).
3. **Auditoría del DOM** en Chrome sin interfaz, contra el servidor de la copia
   aparte, 8768 (§6.0), con el usuario `demo`. Es un script fuera del
   repositorio, como el de la maqueta. Sus puntos son:
   - recorre el texto de las pantallas del juego de capturas (§6.0);
   - calcula el color efectivo y su fondo y exige 4,5:1, o 3:1 en texto grande;
   - mide arcos, iconos de chip y bordes de campo;
   - informa de los fallos, aunque no forma parte de la suite.

   **Lo que no comprueba:** las fotos y los colores mezclados por el navegador.

---

## 4. Componentes

### 4.1 Medidor anillo con icono (`_ring.html`)

Se mantiene **un solo SVG**, ahora con el icono dentro:

```html
<svg class="ring" viewBox="0 0 56 56" aria-hidden="true">
  <circle class="trk" cx="28" cy="28" r="22"/>
  {% if metric.ratio %}<circle class="arc" cx="28" cy="28" r="22" stroke-dasharray="{{ metric.small_ring }}" transform="rotate(-90 28 28)"/>{% endif %}
  <use class="ring-glyph" href="#i-{{ w.piece_icon }}" x="16" y="16" width="24" height="24"/>
</svg>
```

La clase es `ring-glyph`, no `ring-ic`, que ya existe con otro uso (D15).
`_ring.html` necesita `w` además de `metric`. Las filas que no usan
`_wear_row.html` lo incluyen con `{% include "garage/_ring.html" with
w=alert.wear metric=alert.wear.headline %}` (Taller, F3d) o con
`w=row.wear metric=row.wear.headline` («Montado ahora», F3b).

- **`Wear.piece_icon`** es una propiedad nueva y pura en `presentation.py`:
  - si la regla es de una pieza, devuelve `icons.item_icon_key(rule.item)`;
  - si no, devuelve `"bike"`.

  Es el mismo criterio que `_together.html:6` y `snooze_views.py:77`.
- **Para evitar N+1:** `maintenance_due.py:174` pasa a
  `select_related("item", "item__category", "bike", "service_type")`, porque
  `item_icon_key` lee `item.category` (`icons.py:108`).
- **CSS:**
  - `.ring` mide 52 px y lleva `color: var(--ink)` (`var(--ink-2)` con
    `st-nodata`);
  - `.ring .trk` lleva `stroke: var(--soft, var(--surface-2)); stroke-width: 6`;
  - `.ring .arc` lleva `stroke: var(--c, var(--primary))`, trazo 6 y extremo
    redondeado;
  - `.ring .ring-glyph` lleva `fill: none; stroke: currentColor; stroke-width:
    1.8; stroke-linecap: round; stroke-linejoin: round`. Esas propiedades se
    heredan dentro del `<use>`; los símbolos con atributos propios, como
    `i-chainring`, los conservan. **`currentColor` y no `var(--ink)`**: en
    `forced-colors` el navegador fuerza `color`, pero no un `stroke` con un
    color fijo. Con `data-theme="light"` y un contraste alto oscuro, un trazo
    en `--ink` quedaría oscuro sobre negro;
  - `.ring text` desaparece.
- **Accesibilidad:** el anillo sigue siendo decorativo. El porcentaje pasa a
  leerse **en el chip**, así que se quita el `sr-only` de `_wear_row.html:6` para
  que no se lea dos veces.

| Caso | Clase | Arco | Pista | Centro | Chip (icono, palabra y %) | `.big` |
|---|---|---|---|---|---|---|
| Vencido | `st-due` | `--due`, lleno al 100 % | `--due-soft` | icono de la pieza en `--ink` | octágono «Vencido · 108 %» | «+32» «días de más» |
| **Exceso por encima del 100 %** | `st-due` | lleno (`ring()` tiene tope) | — | pieza | «Vencido · 116 %»: el exceso **sí** se ve | «+8» «h de más» |
| Revisar | `st-review` | `--soon` | `--soon-soft` | pieza | lupa (D8) «Revisar · ≥ 95 %» | «150» «km como máx.» |
| Próximo | `st-soon` | `--soon` | `--soon-soft` | pieza | triángulo «Próximo · 95 %» | «150» «km quedan» |
| En curso | `st-progress` | `--primary` | `--primary-soft` | pieza | medidor «En curso · ≥ 62 %» | «… km como máx.» |
| Al día | `st-current` | `--ok` | `--ok-soft` | pieza | círculo con marca «Al día · 14 %» | «… km quedan» |
| **Sin datos** | `st-nodata` | sin arco | punteada `3 5`, trazo 2,5, en `--c` | pieza en `--ink-2` | interrogación «Sin datos», sin % | «—» «sin datos», más el motivo o «ninguna salida con desnivel» |
| Regla sin métricas | `st-nodata` | sin arco | punteada | pieza | «Sin datos» | «—» |
| **≥** (histórico incompleto) | según estado | — | — | — | «≥ N %» en el chip, visible | «como máx.» o «de más como mín.» |
| **Estimado** | según estado | — | — | — | «≈ N %» y la nota «estimado» | «km estimados» o «(estimado)» |
| **Pospuesto** | `st-snoozed` | `--nodata`, con la proporción real | `--nodata-soft` | pieza | reloj «Pospuesto · 108 %», más la nota «Vencido · quedan 5 días» (`_wear_row.html:6`) | la del estado real |
| Proporción 0 | según estado | sin arco (`Decimal(0)` es falso) | pista | pieza | «Al día · 0 %» | «… quedan» |
| Regla de bici | según estado | — | — | `i-bike` | — | — |
| **Retirado** | — | no hay fila: lo excluyen `home.py:119` y `workshop.py:60` | — | — | en la ficha de una pieza retirada, chip de ciclo de vida «Retirado» en la cabecera (D19); el medidor sigue | — |

- **El medidor grande de la ficha** (`item_detail.html:13-21`) conserva su SVG
  (radio 62, `LARGE_RING`), con trazo 13 y pista `--soft`. Las cifras van en
  Outfit 600.
- **Su `aria-label` (`:16`) no cambia.** El chip de debajo (`:21`) ya da
  «palabra · ≥ N % de …» en texto accesible. Añadir `percent_text` al
  `aria-label` lo haría leer dos veces, y además diría «≥», no «al menos».

### 4.2 Chips

- **Chip de estado** (`.chip.st-*`):
  - píldora de 26 px de alto, con relleno `3px 10px 3px 7px`;
  - Figtree 600 de 13 px, texto en `--ink` sobre fondo `var(--soft)`;
  - icono de 15 px en `var(--c)`, con `aria-hidden="true"`.
- **Marcado en la fila de regla:**
  `<span class="chip st-{{ w.state }}"><svg class="ic xs" aria-hidden="true"><use href="#i-{{ w.icon }}"/></svg>{{ w.word }}{% if metric.percent is not None %} · {{ metric.percent_text }}{% endif %}</span>`.
  - En las listas (`list.html:19`) no cambia: lo fijan las pruebas (D19).
- **El color nunca va solo:** todo chip de estado lleva icono y palabra.
  - El de las salidas por revisar (`index.html:22`, hoy con `#i-alert` escrito
    a mano) pasa a tomar el icono y la palabra de `STATES["review"]`.
- **Chip de ciclo de vida** (`.chip.life`; D19):
  - fondo `--surface-2` e icono en `--ink-2`;
  - Montado `i-bike`, Disponible `i-box`, En uso `i-user`, Retirado
    `i-archive`;
  - Sin estrenar `i-sparkle`, con fondo `--primary-soft` e icono `--primary`.
  - La palabra sale de las constantes nuevas de `services/lifecycle.py` (D19).
- **Filtros** (`.chips .chip-link`, `.chip-link.on`):
  - píldora de 44 px en `--surface`, con `--shadow` y `border: 1px solid
    var(--card-border)`;
  - la elegida en `--primary` con `--on-primary`, peso 700 y `aria-current`, que
    ya existe;
  - en `forced-colors` desaparecen los fondos, así que la elegida lleva un borde
    de 3 px y el texto subrayado, y las demás un borde de 1 px. Si todas
    llevaran el mismo borde, no se sabría cuál está elegida.

  El marcado no cambia.

### 4.3 Tarjetas y secciones

- **`.card` y `.panel`**: un mismo aspecto.
  - `--surface`, borde `--card-border`, radio 22 y `--shadow`;
  - relleno 16, `display: grid; gap: 12px`.

  `.page .card` (heredado, 6 plantillas) toma el mismo estilo.
- **`section.sec.card`**: las secciones de las pantallas principales que la
  maqueta pone en tarjeta. Se añade la clase `card` a la `section`, que ya
  existe; no hay elementos nuevos.
- **`.sec-h h2`**: Outfit 600 de 20 px, sin mayúsculas. La maqueta reserva las
  mayúsculas para `.grp`.
  - Dentro de una tarjeta, `.sec-h` hace de `.card-h`.
  - `.count` es una píldora de 28 px en `--surface-2`.
- **`.sub-h`**: título de subgrupo, como `.grp` de la maqueta (13 px,
  mayúsculas, `--ink-2`). Se conserva el nombre porque lo lee
  `tests_snoozes.py:364`.

### 4.4 Filas

- **`.entry`**:
  - rejilla `52px | 1fr | auto`, alto mínimo 64 y `gap: 12px`;
  - separador `1px var(--line)` entre filas, sin línea en la última dentro de
    una tarjeta;
  - `.entry-name` en Figtree 650 de 16,5 px;
  - `.entry-sub` en 14 px y `--ink-2`.
- **`.entry.compact`**: rejilla de 48 px y alto mínimo 56.
- **`.glyph`** (tesela): 48 px (40 en `compact`), radio 16, `--surface-2`, sin
  borde. `.glyph.accent` pasa a `--primary-soft` con icono `--primary`.
- **`.big`**: la cifra en Outfit 600 tabular de 20 px y el pie en 12 px.
- **`.entry.nested`**: mantiene el `padding-left`. No se añade el icono de
  anidado de la maqueta: `i-nest` no está en el sprite ni en ninguna fase.
- Las filas que no navegan siguen sin chevron. Las que sí, llevan `.ic` en
  `--ink-2`.

### 4.5 Barra de pestañas flotante

El marcado de `_tabbar.html` no cambia: el `nav`, las 5 `a.tab` y
`aria-current`. Cambia el CSS de `garage.css:245-255` y la geometría:

- **La barra:**
  - `.tabbar` es fija y flotante, separada `--nav-gap` (10 px) del borde
    inferior, más el área segura, y 8 px de los lados;
  - radio 26, fondo `--surface`, `border: 1px solid var(--card-border)`, sombra
    `--shadow-float` y `max-width: 560px`. En oscuro, el borde es lo que la
    separa del fondo (§3.1);
  - sin `backdrop-filter`;
  - `.tab-ic` es una píldora de 52×30;
  - la pestaña activa lleva `.tab-ic` en `--primary` e icono en
    `--on-primary`, con la etiqueta en 700 y `--ink`;
  - las inactivas van en `--ink-2`;
  - etiquetas de 12 px (11 px por debajo de 359 px).
- **Huecos que deja la barra flotante:**
  - `body.has-tabbar`: `padding-bottom: calc(var(--nav-space) + 24px)`;
  - `.actionbar`: `bottom: calc(var(--nav-space) + 8px)`;
  - `.fab`: `bottom: calc(var(--nav-space) + 16px)`, con `--shadow-float`.
- **Que el foco no quede tapado:**
  - `html` lleva `scroll-padding-top: calc(64px + env(safe-area-inset-top))` y
    `scroll-padding-bottom: calc(var(--nav-space) + 24px)`;
  - `html:has(.actionbar)` suma 80 px al inferior;
  - desde 1000 px el inferior baja a 16 px.
- **Barra superior:**
  - `.appbar` es opaca, en `--bg`, **sin `min-height`**, y se elimina `--bar`;
  - la altura la da `.appbar-row`: `height: 56px` (hoy 48 px, `garage.css:55`);
  - se mantiene el pliegue a 6 px cuando no hay botones (`garage.css:58-59`): esa
    regla, más específica, sigue con `height: 6px` y añade `min-height: 0`. Un
    `min-height: 56px` en `.appbar` o en `.appbar-row` dejaría la barra a 56 px
    siempre, y Más tendría una franja vacía.
  - `.icon-btn` sigue transparente en la barra, como hoy (no toma el fondo
    `--surface` de la maqueta).

### 4.6 Cabecera de bici con foto (`bike_detail.html:4-8`)

```html
<header class="hero bike-hero card">
  {% if cover %}<img class="cover" src="{% url 'garage:photo-content' cover.pk %}" alt="Foto de {{ object.name }}"
       width="{{ cover.storage_object.width }}" height="{{ cover.storage_object.height }}" referrerpolicy="no-referrer" decoding="async">
  {% else %}<span class="cover cover-empty" aria-hidden="true"><svg class="ic"><use href="#i-bike"/></svg></span>{% endif %}
  <div><h1>{{ object.name }}</h1><p class="lede">…igual que hoy…</p>
    {% if not cover %}<a class="link" href="{% url 'garage:bike-photo-create' object.pk %}"><svg class="ic sm"><use href="#i-camera"/></svg>Añadir foto</a>{% endif %}
    {% with worst=attention.0.wear %}…chip «N avisos» con STATES del estado más grave y su palabra en sr-only (D17), o «Sin avisos» neutro…{% endwith %}</div>
</header>
```

- La imagen de portada no lleva `loading="lazy"`: está arriba y se ve al abrir.
  Su coste está en D2 y §7.1.3.

- **Compacta para conservar la densidad.** La maqueta pone el arte a todo el
  ancho y, a 390 px, no se ve ninguna pieza.
  - Móvil: rejilla `minmax(112px, 38%) | 1fr`, con `.cover` en 4:3,
    `object-fit: cover`, radio 16 y fondo `--primary-soft`.
  - Entre 640 y 999 px: tesela de 170 px.
  - Desde 1000 px: columna lateral fija con `.split` (F4b).
- **Si el almacenamiento cae** (503), el navegador muestra el `alt` dentro de la
  tesela, sobre su fondo. No se usa `onerror`, porque obligaría a un script en
  línea.
- **Privacidad:**
  - sólo se usan fotos de `owned_photos(request.user)` (`views.py:110`);
  - el service worker ya excluye `/garage/photos/` (`sw.js:27`);
  - `referrerpolicy="no-referrer"`, como en `photo_list.html:4`.

### 4.7 Ficha de pieza

- `.hero.piece-hero` lleva:
  - tesela de 64 px con el icono (`object|item_icon`);
  - el `h1`;
  - la `.lede` (`life_text`);
  - el chip de ciclo de vida (§4.2).
- Cada regla es una tarjeta `.panel` que contiene:
  - `.gauge-title`, una clase que se conserva (`tests_lifespan.py:189-190`);
  - el medidor grande;
  - el chip de estado con frase;
  - `.trio` con estilo de pares clave/valor.

### 4.8 Conmutador de tema: Más → Apariencia (D5, D6)

- **Más → Apariencia:**
  - `<form method="post" action="{% url 'garage:appearance' %}">` con
    `fieldset.seg` y `legend` «Apariencia»;
  - 3 radios `name="theme"` con los valores `auto`, `light` y `dark` y las
    etiquetas «Automático», «Claro» y «Oscuro»;
  - un `next` oculto y el botón «Guardar»;
  - la nota «Automático sigue el ajuste del sistema. La elección se recuerda en
    este navegador (en el iPhone, la app instalada y Safari la guardan por
    separado).».
  - `.seg` es una rejilla de 3 en `--surface-2`; la opción marcada va en
    `--primary` con `--on-primary` y 700.
- **Vista nueva `appearance`** (POST con CSRF; **no exige sesión**):
  - no lleva `login_required`. El tema es una preferencia del navegador, no de
    la cuenta, y no lee ni escribe datos del usuario. Con `login_required`, un
    POST con la sesión caducada iría al login con
    `next=/garage/appearance/`, y al volver el GET daría 405;
  - un **GET redirige (302) a `garage:more`**, en vez de responder 405;
  - valida `theme` contra `{auto, light, dark}` y responde 400 si no es válido;
  - con `light` o `dark` fija la cookie `garage_theme` (`Max-Age` de 1 año,
    `Path=/`, `SameSite=Lax`, `Secure` si es HTTPS; no `HttpOnly`, porque la lee
    `garage.js` para la página sin conexión);
  - con `auto` la borra;
  - redirige a `next` sólo si es seguro (patrón de `tests_mobile_review.py:297`)
    y, si no, a `garage:more`.
- **Etiqueta `{% client_theme %}`** en `garage_ui.py`:
  - devuelve `light`, `dark` o `""` según una lista cerrada de valores;
  - devuelve `""` si el contexto trae `auto_theme`.
- **`shell.html`:**
  - `<html … {% if theme %}data-theme="{{ theme }}"{% endif %}>`;
  - con un tema forzado, una sola `meta theme-color` sin `media` y
    `color-scheme` fijo;
  - sin tema forzado, las dos `meta` actuales con `media`.
- **La página sin conexión** pasa `auto_theme=True`. Es pública, la guarda el
  service worker sin credenciales (`sw.js:11`) y tiene `max-age=3600`
  (`app_views.py:52-56`), así que no puede variar por cookie.
- **`garage.js`:**
  - al cambiar un radio aplica `data-theme`, la cookie y `meta theme-color` sin
    recargar, y oculta el botón «Guardar»;
  - con «Automático» quita `data-theme` y vuelve a dejar **las dos** `meta
    theme-color` con su `media` (claro `#F5F3EF`, oscuro `#131118`), como las
    pinta el servidor sin tema forzado. Con un tema forzado deja una sola `meta`
    sin `media`;
  - en la página sin conexión aplica el tema de la cookie al cargar.

  Sigue siendo el único `<script>`, con `defer`.
- **iOS:** la app instalada en la pantalla de inicio tiene sus propias cookies,
  separadas de las de Safari. El tema elegido en Safari no pasa a la app ni al
  revés: se elige en cada una. Lo dice la nota de Apariencia y no se puede
  verificar en local.

### 4.9 Escritorio (D13)

Desde 1000 px:
- `body.has-tabbar` lleva `padding-left: 248px`;
- `.tabbar` pasa a ser una columna fija a la izquierda, con
  `border-right: 1px var(--line)`, sin sombra;
- las pestañas son filas de 50 px con radio 16, y la activa va rellena de
  `--primary`;
- `.brand` («Garage», con un mini-anillo de 34 px en SVG) es un `<span>` sin
  enlace, oculto por debajo de 1000 px;
- `.page` y `.appbar-row` llegan a `max-width: 1080px`, con márgenes de 32 px;
- `.split` y `.cols` dan dos columnas (F4b).

---

## 5. Mapa pantalla por pantalla

**Leyenda de qué tipo de cambio es:**
- **T**: sólo tokens y CSS, sin cambiar el HTML.
- **C**: clases añadidas o componentes del §4.
- **G**: tratamiento genérico de pantallas que la maqueta no tiene. Usa tarjetas,
  campos de 50 px, botones de 50 px, `.glyph` y chips de §4 sin cambiar su
  estructura.

Las fases están en §6.

| Plantilla | Pantalla | En la maqueta | Qué cambia | Fase |
|---|---|---|---|---|
| `shell.html` | documento | — | `data-theme`, `theme-color` y `color-scheme` (§4.8); `@font-face` en el CSS (F1b) | F1a, F1c |
| `base.html` | barra superior y pestañas | — | T: barra superior opaca; sin cambio de HTML | F2d |
| `_tabbar.html` | pestañas | `nav.nav` | T: flotante; marca de escritorio (C). Las líneas Android de la barra (`garage.css:252-255`) se van antes, en F2e | F2e, F2d, F4a |
| `_back.html` | atrás | `.back` | T (`--primary`, chevron de 24 px); se mantiene la bifurcación iOS/Android | F2e |
| `_icons.html` | sprite | — | +`i-search` (F2b); +`i-box`, `i-user`, `i-archive` e `i-sparkle` (F3c). Todos sólo con trazo, sin `fill=` (`tests_categories.py:71`) | F2b, F3c |
| `_ring.html` | anillo | `.ringi` | C: icono de la pieza en el centro; sin `<text>` | F2a |
| `_wear_row.html` | fila de regla | `.row` | C: chip con %; sin `sr-only` duplicado | F2a |
| `index.html` | Garaje | `#garaje` | C: secciones en tarjeta; tarjetas de bici con insignia (D17); fila «salidas por revisar» con icono de `STATES` (F2b); FAB y «+» iguales. **No se lleva** «Última salida» (dato nuevo) | F3a |
| `bike_detail.html` | Bici | `#bici-rallon` | C: cabecera con foto (§4.6); tarjetas; «Montado ahora» con anillo si hay `row.wear`, y tesela si no; gráfico y montajes en tarjeta | F3b, F4b |
| `item_detail.html` | Pieza | `#pieza-*` | C: `piece-hero`, chip de ciclo de vida, tarjeta de medidor; el `aria-label` del medidor no cambia (§4.1) | F3c |
| `maintenance.html` | Taller | `#taller` | C: un grupo por tarjeta en el orden actual (D10); filas Pospuestos y Sin datos con anillo, icono de la pieza **y chip de estado con icono y palabra**, mismos enlaces | F3d |
| `maintenance_alerts.html` | detalles técnicos | — | G: `.card` heredada. Su nota «Próximo…» (`:3`) y `LABELS` no cambian (D7) | F4c |
| `usage_rides.html` | Salidas | `#salidas` | C: tesela de fecha (`.ride-date`, día y mes) en lugar de `.glyph`; filtros como píldoras; «Powered by Strava» se queda | F3e-1 |
| `usage_ride.html` | detalle de salida | — | G: secciones en tarjeta, `.menu` y `.pending` | F4c |
| `ride_review.html` | revisar salida | — | G: `.panel`, `.choice` y `.switches` con tokens (F2c); `.sw` sin variante Android (F2e, `garage.css:221-224`) | F2e, F2c, F4c |
| `_review_effects.html` | efectos | — | T | F2c |
| `_ride_measures.html` | cifras de salida | — | T: `.stats` como casillas | F2c |
| `statistics.html` | Estadísticas | `#estadisticas` | C: `.stats` como teselas; el gráfico de línea con tokens (D14); reparto por bici con `.bar.share` en `--primary` (con respaldo de `var()`: la fila de `:39` no tiene `st-*`); la tesela de «Sin bici · revisar» (`:43`) pasa a la lupa (D8, F2b); `form.as_p` (`:77`) pasa a `_field.html` | F2b, F3e-2, F4c |
| `statistics_metrics.html` | métricas | — | G | F3e-2 |
| `_chart.html` | gráfico | `figure.chart` | T: `--accent` → `--primary`; sin cambio de marcado | F2c |
| `more.html` | Más | `#mas` | C: grupos en tarjeta con `.grp`; **Apariencia** (§4.8) | F1c, F3e-3 |
| `add.html` | Añadir | — | G: `.menu` en tarjeta | F3e-3 |
| `list.html` | Bicis, Material, Categorías | `#material` | C: filtros como píldoras; filas con estilo nuevo; el chip «Retirado/Retirada» no cambia (D19); el orden de los filtros, tampoco | F3e-3 |
| `strava.html` | Strava | `#strava` | C: `.panel` Estado; chip «Conectado» si procede; formularios con campos nuevos; zona de peligro con `--danger-ink` | F3e-3 |
| `export.html` | Exportar | — | G | F4c |
| `form.html` | formularios genéricos (≈30 rutas, §1.4 del inventario), incluido «Registrar» | `#registrar` | G: el formulario en tarjeta; campos de 50 px; `.actionbar` encima de la barra flotante | F2c, F4c |
| `_field.html` | campo | `.field` | T | F2c |
| `_icon_grid.html` | rejilla de iconos | — | T: **se conservan literalmente** las reglas que lee `tests_categories.py:322-328` | F2c |
| `_together.html` | «También en esta visita» | `fieldset.checks` | T: casillas de 56 px en `--surface-2` | F2c |
| `_starter.html` | categorías iniciales | — | T | F2c |
| `lifespan.html` | vida útil | — | G: `.hero` de pieza y campos | F4c |
| `snooze.html` | posponer | — | G: el chip `st-snoozed` ya es de §4.2 | F4c |
| `_snooze_note.html` | nota de aplazamiento | — | T: `.pending` con `--soft` | F2c |
| `source_merge.html` | fusionar fuentes | — | G | F4c |
| `service_event.html` | intervención | — | G: `.hero`, `.stats.two` y filas | F4c |
| `_event_usage.html` | uso entre intervenciones | — | T | F2c |
| `detail.html` | categoría | — | G: `.hero` y `.actionbar` | F4c |
| `_part_lives.html` | vidas por categoría | — | T | F2c |
| `usage_profiles.html` | perfiles | — | G | F4c |
| `usage_profile.html` | perfil | — | G: `.timeline` con `--primary` | F4c |
| `history_index.html` | histórico | — | G: `form.as_p` (`:23`) pasa a `_field.html`; `<button>` sin clase pasa a `.btn.ghost` | F4c |
| `history_preview.html`, `history_execute.html`, `history_run.html` | flujo FIT y trabajos | — | G: `form.as_p` pasa a `_field.html`; botones con clase | F4c |
| `periods.html` | historial de montajes | — | G: `.card` heredada | F4c |
| `photo_list.html` | fotos | — | T: `.photos` con radio 16 y fondo `--surface-2` | F2c |
| `photo_form.html` | añadir o sustituir foto | — | G: campos con `_field.html` (hoy van a mano, `:8`) | F4c |
| `_elevation_hint.html`, `_elevation_rule_note.html` | notas de desnivel | — | sin cambios (son texto) | — |
| `offline.html` | Sin conexión | — | T: tokens y fuentes precargadas; tema automático y luego el de la cookie por JS (§4.8) | F1a–F1c |
| `registration/login.html` | Entrar | — | T: `.login` en tarjeta; lee el tema de la cookie | F1a, F2c |
| `sw.js` | service worker | — | sin cambio de código. La vista que lo genera (`app_views.py:45-49`) añade las fuentes a `ASSETS` **sin `?v=`** (F1b); la versión cambia sola con `VERSIONED` | F1b |

**Lo que no se lleva a la app:**
- de la maqueta, `#sobre`, la píldora «Boceto», `?tema=`, la navegación con
  `:target`, la intercepción de formularios y `body.js`;
- las zonas;
- el gráfico de barras;
- «Última salida»;
- el gasto en una sola moneda con EUR/km.

---

## 6. Fases

### 6.0 Reglas comunes a todas las fases

- **Ninguna fase visible antes de que el usuario responda §8.1.** Antes sólo se
  hace lo de §8.2.
- **Orden de ejecución:** F0 → F1a → F1b → F1c → F2a → F2b → **F2e → F2c →
  F2d** → F3a → F3b → F3c → F3d → F3e-1 → F3e-2 → F3e-3 → F4a → F4b → F4c →
  (F4d, opcional). F2e va antes que F2c y F2d porque quita las líneas Android
  del interruptor y de la barra que esas dos restilizarían (D11).
- **Una fase, una cosa.** No se mezclan refactor y comportamiento.
- **Lo implementa un agente Opus.** Fable orquesta y verifica. No hay commits
  sin que el usuario los pida.
- **Pruebas primero, derivadas del comportamiento.**
  - Primero se ve fallar la prueba nueva y luego se implementa.
  - Excepción: las fases que sólo tocan CSS (F2c, F2d) no tienen comportamiento
    que probar. Las protegen las pruebas de guarda (§3.3 y F0) y la verificación
    visual. Se dice explícitamente en su apartado.

#### 6.0.1 Copia aparte y servidor 8768 (D20)

Todo garage-050, F0 incluida, se hace en un worktree. La demo 8766 y el árbol
principal no se tocan hasta que el usuario apruebe.

1. **Comprobar** que `git -C /Users/maxicombina/src/learning/django/stravagancia
   status --short garage/` sale vacío (el 1 nov lo estaba: el código de
   `garage/` está entero en el commit `576ec9c`). Si no, parar y preguntar.
2. **Crear la copia** (rama nueva desde `garage`; sin push; no cambia ni
   `garage` ni su árbol de trabajo):

   ```bash
   git -C /Users/maxicombina/src/learning/django/stravagancia worktree add \
     -b garage-050-anillos /Users/maxicombina/src/learning/django/stravagancia-garage-050 garage
   ```

   Va fuera de `/private/tmp`, porque un reinicio lo vacía: el worktree de
   garage-045, que estaba en un scratchpad, sale hoy «prunable» en `git worktree
   list`. Lo que no está en el commit tampoco está en la copia: `design/`, las
   specs nuevas y los archivos de garage-044/048 (`tests_local_strava*.py`,
   `test_support/local_strava.py`…). La maqueta se lee del árbol principal,
   sólo para consulta.
3. **Servidor de la copia en 8768**, contra la misma base demo 55433 (sin
   `migrate` ni seed: no hay migración, §7.2):

   ```bash
   GARAGE_STRAVA_USER=demo \
   GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python \
   python3 /Users/maxicombina/src/learning/django/stravagancia/tools/handoff/garage_demo_pg.py run \
     /Users/maxicombina/src/learning/django/stravagancia-garage-050/manage.py \
     runserver 127.0.0.1:8768 --noreload --insecure --settings=strava_app.settings_test
   ```

   - **La ruta de `manage.py` tiene que ser absoluta y de la copia.** El helper
     fija `REPO` y `cwd` al árbol principal (`garage_demo_pg.py:10`, `:22-23`),
     así que `run manage.py …` arrancaría el código principal. Con la ruta
     absoluta, Python pone la carpeta de la copia la primera en `sys.path`. De
     ahí salen el código, las plantillas (`APP_DIRS`) y los estáticos.
   - Los estáticos los sirve `runserver --insecure`, porque `settings_test`
     tiene `DEBUG = False` (`settings_test.py:9`). `BASE_DIR` sale del propio
     archivo de ajustes (`:7`) y no se lee ningún `.env` (la copia no tiene).
   - **Comprobación**, tras el primer cambio de `garage.css` y un reinicio: la
     primera línea de `curl -s http://127.0.0.1:8768/garage/sw.js` (versión)
     es distinta de la de `http://127.0.0.1:8766/garage/sw.js`.
   - **Cookies.** Las cookies no distinguen puertos, y las dos instancias
     comparten base y `SECRET_KEY` de `settings_test`: la sesión de 8766 vale en
     8768. Entrar en 8768 con otro usuario en el Chrome del usuario cerraría su
     sesión de 8766. Por eso las capturas usan un perfil temporal, y si el
     usuario quiere mirar 8768, conviene una ventana de incógnito. La cookie
     `garage_theme` de F1c también se comparte; 8766 la ignora hasta adoptar
     F1c.
   - El service worker y su caché son por origen (puerto incluido): los de 8768
     no tocan los de 8766.
4. **Suite en la copia.** `garage_test_pg.py` también fija `REPO` y `cwd` al
   árbol principal (`garage_test_pg.py:10`, `:21-22`), y `-m pytest` importaría
   desde ahí. Se usa una copia del helper en el scratchpad con `REPO` apuntando
   al worktree (el helper del repositorio no se toca):

   ```bash
   sed 's#^REPO=Path(.*)#REPO=Path("/Users/maxicombina/src/learning/django/stravagancia-garage-050")#' \
     /Users/maxicombina/src/learning/django/stravagancia/tools/handoff/garage_test_pg.py > <scratchpad>/garage_test_pg_wt.py
   export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
   python3 <scratchpad>/garage_test_pg_wt.py run -m pytest -q -p no:cacheprovider
   ```

   - Usa el mismo PostgreSQL 55434. `run` no lee el archivo de estado, pero sólo
     puede correr **una suite a la vez** en 55434.
   - **Referencia de partida:** se mide en la copia **antes de F0** y se anota.
     Será menor que 2801 + 45 (garage-048), porque `tests_local_strava*.py` no
     está en la rama.
   - Desde F1a, además, `cd /Users/maxicombina/src/learning/django/stravagancia-garage-050
     && $GARAGE_TEST_PYTHON -m test_support.contrast garage/static/garage/garage.css`.
5. **Antes de capturar, reiniciar 8768.** `asset_version()` se calcula una vez
   por proceso (`assets.py:17`, `@cache`) y con `--noreload` el servidor no se
   reinicia al cambiar CSS ni plantillas. Sin reiniciar, el `?v=` no cambia y el
   service worker sirve el CSS antiguo desde su caché (`sw.js:33-41`). No se usa
   Docker Compose.
6. **Adoptar.** Cuando el usuario apruebe una fase o un bloque, se lleva al
   árbol principal: commit en la rama y fusión si el usuario pide commits, o
   parche sin commit. La forma se decide con él. Después se reinicia la 8766.
   Hasta entonces, la 8766 sigue igual.

#### 6.0.2 Capturas y auditorías

- **Juego de capturas:**
  - 12 pantallas: Garaje, Salidas, Taller, Estadísticas, Más, Bici, Pieza,
    Material, Registrar intervención, Strava, Entrar y Sin conexión;
  - **6 tamaños:** 320×640, 360×780, 390×844, 844×390 (apaisado), 768×1024 y
    1280×800. Los de 320 y 360 px son los que aprietan: «Estadísticas» a 11 px
    en una pestaña de ~60 px y chips `nowrap` como «Pospuesto · ≥ 100 %» junto
    a «↑ m de más como mín.»;
  - 2 temas: claro y oscuro (antes de F1c, emulando `prefers-color-scheme`);
  - para F2e, además, los agentes de usuario de iPhone y de Pixel.

  En cada fase se capturan sólo las pantallas afectadas, antes y después.
- **Cómo:** Chrome sin interfaz con un **perfil temporal** (`--user-data-dir` en
  el scratchpad), manejado por CDP:
  - `Emulation.setDeviceMetricsOverride` para el tamaño (con `mobile: true` y
    escala 3 en teléfonos);
  - `Emulation.setUserAgentOverride` para iPhone o Pixel;
  - `Emulation.setEmulatedMedia` para `prefers-color-scheme`.

  No se usan iframes: `XFrameOptionsMiddleware` (`settings_test.py:21`) los
  bloquea.
- **Desborde:** en cada captura se comprueba que
  `document.documentElement.scrollWidth` no supera `clientWidth`. Si lo
  supera, es un fallo que se anota con la pantalla y el tamaño.
- **Dónde y con quién se capturan:**
  - siempre en el servidor de la copia, `http://127.0.0.1:8768/garage/`. La
    8766 sólo para las capturas «antes» si 8768 aún no existe (son iguales);
  - siempre con el usuario ficticio **`demo`** (credenciales en
    `docs/garage-progress-state.json`; también en CLAUDE.md, «Retomar ahora»);
  - **nunca** con `maxi` ni con `maxi-manual`, que tienen datos reales;
  - las capturas se guardan **fuera del repositorio** (el scratchpad de la
    sesión) y nunca se copian al repo.

### F0 · Red de pruebas (sólo pruebas, sin cambio de comportamiento)

- **Alcance.** Helpers de HTML y migración de las aserciones que hoy fijan la
  maquetación con expresiones regulares.
- **Archivos:**
  - nuevo `garage/test_html.py`, con `html.parser` de la biblioteca estándar.
    Ofrece `parse(html)`, `find_all(node, tag=None, cls=None, **attrs)`,
    `row_by_href(html, href)`, `accessible_text(node)` (excluye lo
    `aria-hidden` e incluye lo `sr-only`) y `visible_text(node)` (excluye las
    dos cosas);
  - pruebas migradas: `tests_lifecycle.py:226-229` (`rows()`, usada por 11
    funciones), `tests_mobile_bike.py:41,49`, `tests_mobile_item.py:174`,
    `tests_lifespan.py:189-193` y `tests_elevation_review.py:186`.
- **Pruebas nuevas.** Son de caracterización: pasan ya hoy y quedan como guarda.
  Van en `garage/tests_ui_guards.py`:
  - **helpers:** `accessible_text` y `visible_text` sobre un fragmento con
    `aria-hidden` y `sr-only` (4 aserciones);
  - **una sola navegación:** en las 12 páginas de `tests_mobile_shell.py:39-40`
    hay un único `nav.tabbar` con 5 `a.tab` (12 subcasos × 2 aserciones);
  - **sin orígenes externos:** no hay `http://` ni `https://` en `garage.css`, y
    ningún `<link rel="stylesheet">` ni `<link rel="preconnect">` apunta fuera
    (1 aserción más 12 subcasos);
  - **sin fotos en caché:** el cuerpo de `sw.js` contiene
    `url.pathname.startsWith('/garage/photos/')` (1 aserción; hoy sólo se
    comprueba lo de exportar, en `tests_mobile_shell.py:156`).
- **Aceptación.** En la copia (§6.0.1), la suite queda en verde con la
  referencia de partida más las nuevas, y ningún archivo fuera de
  `garage/tests*.py` y `garage/test_html.py` cambia.
- **Verificación visual:** no aplica. Es la única fase que puede hacerse antes de
  que el usuario responda §8.1 (§8.2).

### F1a · Tokens «Anillos» (CSS, metadatos del tema y manifiesto)

- **Alcance:**
  - el bloque de tokens de §3.1, claro y `@media` oscuro;
  - las clases `st-*` con `--c` y `--soft`;
  - la sustitución de `--tile`, `--ink2`, `--accent*`, `--bar`, `--ci` y `--*-i`
    en todo el CSS;
  - `color-mix` sustituido por `--soft`, siempre con respaldo (§3.1);
  - `--danger-ink`, `--knob` y `--knob-shadow`;
  - las pilas de fuentes con respaldo de sistema, sin archivos;
  - `theme-color` y manifiesto.
- **Archivos:**
  - `garage/static/garage/garage.css` (`:1-31` y los usos);
  - `garage/templates/garage/shell.html:7-8`;
  - `garage/app_views.py:32-33`;
  - nuevos `test_support/contrast.py` y `garage/tests_theme_tokens.py`.
- **Pruebas primero** (las de §3.3, salvo la de paridad):
  - **contraste, 72 comprobaciones.** Hoy falla: por ejemplo, `--soon`
    `#fab219` sobre `--surface` da 1,83:1, y los tokens nuevos no existen;
  - **sin literales, 1 aserción.** Hoy falla por `#ffffff` en `garage.css:218`;
  - **clases de estado, 7 subcasos × 2 aserciones.** Hoy falla porque no existe
    `--soft`;
  - **`var()` con respaldo, 1 aserción.** Hoy pasa (es una guarda); falla en
    cuanto se escriba un `var(--soft)` sin respaldo;
  - **`theme-color` y manifiesto, 4 aserciones.**
  - Además se mantienen literalmente `tests_mobile_shell.py:74` y
    `tests_categories.py:322-328`.
- **Aceptación:**
  - 36 pares sin ningún fallo, y la salida del script se adjunta;
  - la suite en verde;
  - el único HTML que cambia son las `meta` de `shell.html`.
- **Verificación visual:** el juego completo, en claro y oscuro, a los 3 anchos.
  Hay que comprobar que ningún texto usa el color del estado.

### F1b · Fuentes autoalojadas (requiere el sí del usuario, D4)

- **Alcance:**
  - `garage/static/garage/fonts/figtree-latin-wght-v1.woff2` y
    `outfit-latin-wght-v1.woff2`, el subconjunto latino variable de Google
    Fonts, el mismo que la maqueta;
  - `OFL-Figtree.txt` y `OFL-Outfit.txt`;
  - en el CSS, dos `@font-face` con rango de pesos (400–700 y 500–700),
    `font-display: swap` y `unicode-range` latino;
  - el comentario de `garage.css:1` pasa a decir «self-hosted fonts».
  - La versión va en el nombre del archivo (`-v1`) para que la caché HTTP no
    sirva una fuente vieja con el mismo nombre. En el CSS se usan URL relativas,
    sin `?v=`.
- **Archivos:** `garage.css`, `garage/assets.py:11-13` (añadir a `VERSIONED`) y
  `garage/app_views.py:16-17` (añadir a `STATIC_ASSETS`, para que se precarguen
  al instalar).
- **Pruebas primero:**
  - cada `url()` de `garage.css` existe en `finders` y está en `VERSIONED` y en
    `STATIC_ASSETS` (2 fuentes × 3 aserciones);
  - junto a cada fuente hay un `OFL-*.txt` (2 aserciones);
  - el cuerpo de `sw.js` incluye las dos URL (2 aserciones);
  - las fuentes suman como mucho 61 440 bytes (1 aserción; la maqueta mide unos
    52 kB).
- **Aceptación.** Con la red cortada después de instalar, la página «Sin
  conexión» se ve en Outfit y Figtree. Esto **sólo se verifica en Chrome de
  escritorio**: no se ha probado en un teléfono.
- **Verificación visual:** comparación antes y después de Garaje, Bici y
  Estadísticas.

### F1c · Tema: cookie, Apariencia y JS (D5, D6)

- **Alcance:** §4.8 y el bloque `:root[data-theme="dark"]` (§3.1).
- **Archivos:**
  - `garage/templatetags/garage_ui.py` (`client_theme`);
  - `shell.html:2,7-9`;
  - `garage/app_views.py`: la vista `appearance` y `auto_theme` en `offline`;
  - `garage/urls.py`;
  - `more.html`;
  - `garage.js`;
  - `garage.css`.
- **Pruebas primero.** Van en `tests_theme.py` y suman unas 30 aserciones; todas
  fallan hoy:
  1. Un POST con `dark` responde 302 a `next` con `Set-Cookie garage_theme=dark`
     (3 aserciones).
  2. Un POST con `auto` borra la cookie (`max-age=0`) (1).
  3. Un POST con un valor fuera de la lista responde 400 y no toca la cookie (2).
  4. Un `next` externo redirige a `/garage/more/` (1).
  5. Un GET responde 405; sin sesión, redirige al login (2).
  6. Con un cliente `enforce_csrf_checks`, sin token responde 403 (1).
  7. Con la cookie en `dark` se pinta `data-theme="dark"`, una sola `meta
     theme-color` con `#131118` y `color-scheme` oscuro; lo mismo con `light`
     (2 subcasos × 3).
  8. Sin cookie, o con `DARK`, `auto` o `"><x`, no hay `data-theme` y hay dos
     `meta` con `media` (4 subcasos × 2).
  9. Más muestra Apariencia con 3 radios y está marcado el que corresponde a
     la cookie (3 subcasos).
  10. La página sin conexión, aun con la cookie, no lleva `data-theme` (1).
  11. La paridad de los bloques oscuros, de §3.3 (1).
  12. Siguen valiendo `tests_mobile_shell.py:52` (un solo script) y la ausencia
      de `style=` (existentes).
- **Aceptación:**
  - el tema forzado se pinta en el servidor y no parpadea al navegar;
  - sin JS, el formulario funciona.
- **Verificación visual:**
  - Más → Apariencia en sus 3 estados;
  - tema forzado oscuro con el sistema en claro, y al revés;
  - foco del teclado en los radios.

  **No verificable en local:** el color de la barra del navegador en Chrome
  Android y en Safari con la app instalada.

### F2a · Anillo con el icono de la pieza (D9)

- **Alcance:** §4.1 y el chip con porcentaje de las filas de regla.
- **Archivos:**
  - `garage/presentation.py` (`Wear.piece_icon`);
  - `garage/services/maintenance_due.py:174`;
  - `_ring.html`;
  - `_wear_row.html`;
  - `garage.css:107-113`;
  - `item_detail.html:16`.
- **Pruebas primero:**
  - **lógica pura**, sin base de datos y con `SimpleNamespace`. `piece_icon`
    devuelve:
    - el icono de la categoría (`bottle`);
    - el deducido por el nombre;
    - `part` por defecto;
    - `bike` en una regla de bici.

    Son 4 aserciones.
  - **pantallas.** En Inicio, Taller y Bici, la fila que enlaza a la ficha tiene
    dentro del `svg.ring[aria-hidden]` un `use href="#i-<clave>"` (3 pantallas ×
    2 aserciones).
  - **7 estados.** El chip contiene `#i-{STATES[s][1]}`, la palabra y
    `percent_text`; con Sin datos, sin «%» (7 subcasos × 3 aserciones).
  - **texto accesible** con `accessible_text` (7 casos):
    - «≥ 95 %» con «km como máx.»;
    - «≈ 95 %» con «estimado»;
    - «+32» con «días de más»;
    - «como mín.»;
    - Sin datos sin «%»;
    - Pospuesto con «Vencido · quedan 5 días»;
    - «2 sin desnivel» y «ninguna salida con desnivel».

    Además, `percent_text` aparece una sola vez (1).
  - **«≥» visible:** `visible_text` de una fila con histórico parcial contiene
    «≥» (1).
  - **sin arco** cuando la proporción es 0 y cuando la regla no tiene métricas
    (2).
  - **`aria-label` del medidor grande** con «≥ N %» y con «≈ N %» (2).
  - **constancia de consultas** en las páginas de Inicio y Taller: con 8 reglas
    más sobre piezas con categoría, el número de consultas no cambia
    (2 pruebas nuevas). Para Bici ya existe `tests_mobile_bike.py:55-66`.
    - Hoy los techos `tests_mobile_home.py:188` (≤ 28) y
      `tests_mobile_workshop.py:363` (≤ 24) no detectan un N+1 pequeño.
    - Orden en que fallan: primero, la prueba del icono; con el icono puesto y
      sin `item__category`, las tres de constancia; con `select_related`, todo
      verde.
- **Aceptación:**
  - la suite en verde;
  - ninguna aserción existente cambia: los textos «km como máx.», «90 %» y
    «Revisar» siguen ahí.
- **Verificación visual:**
  - filas de Garaje, Taller y Bici en claro y oscuro;
  - simulación de daltonismo con CDP (`Emulation.setEmulatedVisionDeficiency`:
    deuteranopía, protanopía y acromatopsia). Cada fila debe seguir
    distinguiéndose por el icono y la palabra del chip.
  - Si el seed ficticio no tiene algún estado, se anota como «verificado sólo por
    pruebas».

### F2b · Icono de «Revisar» y una sola fuente de estados (D8)

- **Archivos:**
  - `_icons.html` (+`i-search`);
  - `presentation.py:13`;
  - `index.html:22` (icono y palabra desde `STATES`, con un filtro
    `state_icon`/`state_word` en `garage_ui.py`);
  - las notas `index.html:45`, `maintenance.html:13`, `maintenance.html:10` y
    `bike_detail.html:23` toman «Próximo» de `STATES["soon"][0]`.
- **Pruebas primero:**
  - cada icono de `STATES` tiene su `<symbol>` en el sprite, con el patrón de
    `tests_categories.py:57-71` (7 aserciones);
  - el chip de salidas por revisar usa `#i-search` (1);
  - ninguna plantilla de `garage/templates` contiene el literal «Próximo»
    (1 aserción con la lista de archivos).
- **Aceptación:** un cambio futuro de vocabulario (D7) es de una línea. La suite
  queda en verde.
- **Verificación visual:** Garaje con salidas por revisar.

### F2c · Superficies: tarjetas, filas, teselas, botones, campos y filtros (sólo CSS)

- **Alcance:** las reglas de §4.2–§4.4 sobre las clases existentes:
  - `.panel`, `.card`, `.sec-h`, `.count` y `.sub-h`;
  - `.entry*`, `.glyph`, `.big` y `.btn*`;
  - los campos (50 px, borde `--field` de 1,5 px y radio 14, con `:focus` y
    `:focus-within`);
  - `.chip-link`, `.menu`, `.messages`, `.install`, `.pending`, `.timeline`,
    `.stats`, `.trio` y `.gauge`;
  - `.choice`, `.sw` (botón en `--knob`), `details.zone`, `.photos` y `.tip`;
  - `@media (forced-colors: active)`: los arcos en `CanvasText` y un borde de
    2 px en chips, pestaña activa y segmento elegido.
- **Archivos:** sólo `garage.css`.
- **Pruebas:** no hay comportamiento nuevo, así que no se escriben pruebas de
  comportamiento. Deben seguir en verde las guardas de F0 y F1a (contraste y sin
  literales) y `tests_categories.py:322-328`.
- **Aceptación:** la suite en verde, el script de contraste sin fallos y el CSS
  sin `data-os` nuevos.
- **Verificación visual:** el juego completo. La densidad se mide en Taller a
  390×844: cuántas filas se ven sin desplazar, antes y después, y se anota.

### F2d · Barra de pestañas flotante y geometría (sólo CSS)

- **Alcance:** §4.5.
- **Archivos:** `garage.css`, en las líneas `:36, 49, 53-59, 181, 195,
  245-255`.
- **Pruebas:** la regla del FAB de `tests_mobile_shell.py:74` debe seguir
  literalmente, y la guarda de navegación única de F0 debe seguir en verde. No
  hay comportamiento nuevo.
- **Aceptación.** Una auditoría de foco (CDP, fuera del repositorio) recorre con
  el tabulador Taller, Bici, «Registrar intervención» y Más a 390×844. Debe
  haber **0 elementos con foco tapados** por la barra de pestañas, la barra de
  acciones o la barra superior. La cifra se apunta antes y después.
- **Verificación visual:** las 12 pantallas a 390 y 768 px, en claro y oscuro,
  más el FAB en Android.

### F2e · Una piel para iOS y Android (D11)

- **Archivos:** `garage.css`, quitando las 11 líneas de D11.
- **Prueba primero:** los selectores `data-os` de `garage.css` son exactamente
  los 6 funcionales de D11 (1 aserción con la lista). Hoy falla porque hay 17
  líneas.
- **Aceptación:** siguen en verde `tests_mobile_shell.py:71-85` y la suite.
- **Verificación visual:** las mismas pantallas con agente de usuario iPhone y
  Pixel. Se ven iguales, salvo el FAB y «+», el «atrás» y las instrucciones de
  instalación.

### F3a · Garaje (D17)

- **Alcance:**
  - «Requiere atención», «Bicis» y «Material sin montar» en `section.sec.card`;
  - tarjetas de bici: tesela con `i-bike`, nombre, «km · h · ↑ m» y la
    insignia de D17;
  - la fila de salidas por revisar mantiene `.ring-ic`, ahora con pista
    `--soft`.
- **Archivos:** `garage/services/home.py:36-42, 122-127, 141-143`
  (`HomeBike.worst`), `index.html:13-78` y `garage.css`.
- **Pruebas primero:**
  - **servicio** (`worst`):
    - con Vencido y Próximo → `due`;
    - sólo Próximo → `soon`;
    - Revisar → `review`;
    - sin avisos → `None`;
    - Pospuesto no cuenta.

    Son 5 casos.
  - **página:** «2 avisos» con `#i-octagon` en la tarjeta de la bici, y «Sin
    avisos» sin clase `st-*` (2);
  - **consultas:** `tests_mobile_home.py:198-211` (snapshot) sigue constante.
- **Opción F3a-bis** (sólo si el usuario la quiere, D2): portada en las tarjetas
  de bici, con una consulta de fotos para todas las bicis. La prueba exige
  +1 consulta constante.
- **Verificación visual:** Garaje en los 3 anchos y los 2 temas.

### F3b · Ficha de bici con foto (D1–D3)

- **Alcance:**
  - la cabecera de §4.6;
  - las secciones en tarjeta;
  - «Montado ahora» con anillo cuando hay `row.wear`.
- **Archivos:** `garage/views.py:109-110` (`photos = list(...)` y `cover`),
  `bike_detail.html` y `garage.css`.
- **Pruebas primero.** Usan los fixtures `backend`, `upload` e `inventory` de
  `tests_photos_domain.py`, como `tests_photo_views.py:29-31`:
  - **con foto:** la cabecera lleva `img` con
    `src="/garage/photos/<pk>/content/"`, `alt="Foto de <nombre>"` y
    `referrerpolicy="no-referrer"` (3 aserciones);
  - **con dos fotos,** la portada es la primera dada de alta (1);
  - **sin foto:** tesela `#i-bike` y enlace a `bike-photo-create` (2);
  - **nunca** aparece la foto de otro usuario (1);
  - **con el almacenamiento caído,** la ficha responde 200 y no filtra la clave
    ni «SECRET» (2);
  - **consultas:** `tests_mobile_bike.py:33` (≤ 34) y `:55-66` siguen en verde,
    porque la lista de fotos se evalúa una sola vez.
- **Aceptación.** A 390×844, con una bici de `demo`, el principio de la primera
  fila de «Requiere atención» o de «Registrado en Garage» se ve sin desplazar.
  Se mide con `getBoundingClientRect` por CDP.
- **Verificación visual:** Bici sin foto (la demo no tiene fotos, garage-010) en
  los 3 anchos y los 2 temas. **Con foto no se puede verificar en la demo** sin
  almacenamiento real; queda cubierto por las pruebas.

### F3c · Ficha de pieza (D19)

- **Archivos:** `_icons.html` (+4 iconos), `item_detail.html:4-34`,
  `garage_ui.py` (etiqueta del chip de ciclo de vida) y `garage.css`.
- **Pruebas primero:**
  - el chip de ciclo de vida muestra la palabra y el icono de `mounted`,
    `available`, `unused` (Sin estrenar), `in_use` y `retired` (5 subcasos ×
    2 aserciones);
  - los 4 iconos nuevos existen en el sprite (4).
  - Siguen valiendo `tests_lifespan.py:189-193` y `tests_mobile_item.py:164-184`.
- **Verificación visual:** fichas de una pieza con vida útil, una sin reglas y
  una retirada.

### F3d · Taller (D10)

- **Archivos:** `maintenance.html:6-52` y `garage.css`.
- **Pruebas primero:**
  - las filas de Pospuestos y de Sin datos llevan el anillo con el icono de la
    pieza (2);
  - sus `href` no cambian: siguen yendo a `maintenance-rule-snooze` y a
    editar la regla o la vida útil (2);
  - el orden de los grupos es el actual (1).
- **Verificación visual:** Taller en los 3 anchos y los 2 temas.

### F3e · Salidas, Estadísticas y Más/Material/Strava

Son tres cambios separados:

- **F3e-1, Salidas** (`usage_rides.html`): la tesela de fecha.
  - Prueba: el texto accesible de la fila contiene la fecha completa local
    (patrón de `TimeZoneCookieTests`) (2).
- **F3e-2, Estadísticas** (`statistics.html`, `statistics_metrics.html`): las
  teselas y el gráfico con tokens.
  - Sin comportamiento nuevo. Siguen `tests_mobile_stats.py:85-109` y
    `tests_elevation_screens.py:285-366`, que leen `<b>…</b><span>…</span>` y
    `stats four`.
- **F3e-3, Más, Añadir, listas y Strava:** las tarjetas, `.grp` y los filtros.
  - Siguen `tests_lifecycle.py:236-263` y `tests_mobile_lists.py:50-70`.
  - En Strava sigue «Powered by Strava» (`tests_strava_views.py:496` y
    siguientes).
- **Verificación visual:** cada pantalla en los 3 anchos y los 2 temas.

### F4a · Escritorio: barra lateral (D13)

- **Archivos:** `_tabbar.html` (`span.brand`, oculto por debajo de 1000 px) y
  `garage.css` (`@media (min-width: 1000px)`).
- **Pruebas primero:** la marca no es un enlace y no hay una segunda
  navegación (2). Sigue `tests_mobile_shell.py:35-36`.
- **Verificación visual:** las 12 pantallas a 1280×800 en los 2 temas. El foco
  debe recorrer la barra lateral en orden.

### F4b · Columnas en escritorio

- **Alcance:** `.split` en Bici (cabecera fija a la izquierda) y `.cols` en el
  Garaje, desde 640 y 1000 px.
- **Archivos:** `bike_detail.html` e `index.html` (envoltorios `div` sin cambiar
  el orden del contenido) y `garage.css`.
- **Pruebas:** el orden de lectura no cambia. Los títulos `h2` salen en el mismo
  orden que hoy (1 aserción por pantalla).
- **Verificación visual:** a 768 y 1280 px.

### F4c · Pantallas secundarias, tratamiento genérico

Es una familia por cambio:

1. **`form.as_p` pasa a `_field.html`** en `history_index.html:23`, los tres
   `history_*` y `statistics.html:77`.
   - Prueba: los campos van envueltos en `div.field`, con su `label` y los
     errores en `.errorlist` (por plantilla).
2. **`<button>` sin clase pasa a `.btn.ghost`**, o a `.btn.danger` si borra.
   - Prueba: no queda ningún `<button>` sin clase en `garage/templates`
     (1 aserción).
3. **`photo_form.html` pasa a usar `_field.html`.**
   - Prueba: `label` y `help` del campo foto (2).
4. **Resto de plantillas G de §5:** sólo CSS, sin pruebas de comportamiento.

- **Verificación visual:** cada pantalla tocada a 390 y 1280 px.

### F4d · Iconos de la app en violeta (opcional, D18)

- **Archivos:** `tools/garage_icons.py:70-75` (pasa a `#5536C8`), los PNG
  regenerados y `app_views.py:32-33`, si cambia también el `theme_color` de la
  marca.
- **Prueba:** sigue `tests_mobile_shell.py:176-187`. La versión cambia sola.
- **No verificable en local:** cómo se ve el icono instalado en iOS y Android.

---

## 7. Riesgos y fuera de alcance

### 7.1 Riesgos

1. **Pruebas que fijan la maquetación.** Las aserciones afectadas, según el
   cambio, son:
   - unas 19 por las clases de fila: `rows()` y otras regex;
   - unas 14 por las cifras `<b>/<span>`;
   - 5 por los chips;
   - unas 21 por scripts o `style=` en línea;
   - 12 por la navegación única;
   - 2 por reglas CSS leídas como texto (`tests_mobile_shell.py:74`,
     `tests_categories.py:322-328`).

   **Mitigación:** se conservan las clases, las cifras `<b>/<span>`, el chip de
   lista, el `<nav>` único, el script único y las reglas CSS que se leen como
   texto (D15). F0 migra las regex frágiles antes de tocar plantillas.
   Esperado: 0 aserciones existentes rotas por fase. Si una fase rompe alguna,
   se justifica en su revisión.
2. **PWA sin red:**
   - Las fuentes sólo están sin red si se precargan (F1b, `STATIC_ASSETS`) y se
     versionan (`VERSIONED`).
   - La página sin conexión no conoce la cookie: sale en automático y el tema lo
     aplica el JS.
   - El `?v=` queda congelado mientras no se reinicie el proceso (§6.0); esto
     sólo afecta a la demo y al desarrollo.
3. **Rendimiento:**
   - **Sprite en línea.** Pesa 12 400 bytes y va en cada respuesta HTML. Los 5
     iconos nuevos le suman unos 1,5 kB por página.
   - **Fuentes.** Suman unos 52 kB que se descargan una vez y se guardan en el
     service worker. Con `font-display: swap` hay un breve salto de fuente en la
     primera visita.
   - **N+1.** El icono del anillo provoca un N+1 si falta `item__category`
     (§4.1, con pruebas de constancia en F2a).
   - **Más barato.** Quitar `backdrop-filter` de la barra superior y de la de
     pestañas aligera el pintado.
4. **Foco detrás de la barra flotante.** La barra tapa 72 + 10 px más el área
   segura, y además está la barra de acciones fija. Lo cubren
   `scroll-padding-*` y la auditoría de foco de F2d.
   - **No verificado:** Safari iOS con el teclado abierto en formularios largos.
5. **Daltonismo:**
   - el anillo sólo comunica el estado por el color, porque el centro lleva el
     icono de la pieza;
   - por eso **todo anillo va con su chip de estado en la misma fila**, con
     icono y palabra (lo prueba F2a);
   - rojo y verde se confunden en deuteranopía; se verifica con la emulación de
     CDP y `forced-colors` (F2c).
6. **«En curso» comparte el violeta de la marca** y puede leerse como «normal»
   (README de la maqueta:180). El chip dice «En curso · ≥ N %», lo que
   compensa. Si el usuario lo nota en las pruebas, se cambia el token de
   `st-progress`.
7. **Densidad.** La maqueta enseña unas 5 piezas por pantalla, frente a las 8–9
   de hoy. Se mitiga con filas de 64 px, una cabecera de bici compacta y la
   columna `.big`, y se mide en F2c y F3b.
8. **`<use>` dentro del SVG del anillo.** Algunos símbolos traen sus propios
   atributos (`i-chainring` con `stroke-width="2.4"`, `i-more` con relleno), así
   que el aspecto puede variar algo entre iconos. Se revisan los 43 en una
   captura de la rejilla de iconos de categorías.
9. **Foto con el almacenamiento caído:** se ve el `alt` dentro de la tesela.
   Aceptable, porque no es posible ocultarla sin JS en línea.
10. **Navegadores:**
    - la app ya usa `:has()` (`garage.css:58`);
    - **no se ha probado** con Safari antiguo, Firefox ni teléfonos reales.

### 7.2 Fuera de alcance

- El **selector de pieles**. Sólo se deja la estructura (D12).
- El **almacenamiento real de fotos** (garage-010: bucket y credencial) y
  `photos-delete`/limpieza. Sin él, la portada sólo se verifica por pruebas.
- **Migraciones: no se espera ninguna.** Las opciones que la habrían necesitado
  están descartadas: el tipo de bici para las ilustraciones (D3), el campo de
  portada (D2) y el tema en el perfil (D5). Si alguna fase acabara
  necesitándola, sería la `0013`, sólo aditiva y sólo local: nunca en Neon y
  nunca con Docker Compose.
- Zonas de la bici, gráfico de barras, «Última salida» y gasto con EUR/km.
- El cambio de vocabulario a «Pronto»/«faltan» (D7) y el de los iconos de la app
  (D18), salvo que el usuario los pida.
- Despliegue (garage-023), Strava real y OAuth (garage-040).

---

## 8. Qué necesita del usuario y qué puede avanzar la IA sin él

### 8.1 Lo que necesita del usuario

1. Un **sí explícito para descargar las fuentes** Outfit y Figtree (OFL) a
   `garage/static/garage/fonts/` (D4, fase F1b). Sin él, la app usa las fuentes
   del sistema.
2. Que **confirme**:
   - D1: «a» es la foto de la bici;
   - D2: la portada es la primera foto;
   - D5 y D6: el tema se guarda en una cookie y se elige en Más → Apariencia,
     sin botón en cada barra;
   - D7: «Próximo» o «Pronto»;
   - D8: la lupa para «Revisar»;
   - D9: el chip «palabra · %» y la columna `.big`;
   - D10: los grupos del Taller y la ausencia de zonas;
   - D11: una sola piel para iOS y Android;
   - D14: el gráfico de línea;
   - D18: los iconos de la app en violeta, ahora o no.
3. Que **mire las capturas** de cada fase en la demo (usuario `demo`) y dé su
   opinión. **Sólo él puede probar en su iPhone o Android**:
   - la barra del navegador;
   - la app instalada;
   - Safari con el teclado abierto.
4. Que diga **si esto va antes o después** de lo pendiente en las pruebas
   locales: garage-047 (fricciones de la interfaz) y garage-044/048 (descargar
   el histórico de Strava). Según CLAUDE.md, el orden lo prioriza con él.
5. Para ver la portada con una foto real: garage-010, con su bucket y su
   credencial.

### 8.2 Lo que puede avanzar la IA sin él

Siempre con agentes Opus, pruebas primero, sin commits y sin tocar Neon:

- **F0**, la red de pruebas: no cambia nada visible.
- **F1a**, los tokens: la paleta es justo la que eligió.
- **F2a, F2c, F2d y F3d.** Con los valores por defecto de D9 y D10, que son
  reversibles y no contradicen el dominio.
- **F2e.** Si se acepta D11 por defecto; es reversible.
- **Preparar la auditoría de contraste y foco** fuera del repositorio, y las
  capturas de «antes» con el usuario `demo`.
- **Crear la tarea en Beads con una subtarea por fase.** Esto lo hace Fable.

**Lo que espera al usuario:**
- F1b, las fuentes (D4);
- F1c, el tema: conviene confirmar D5 y D6 antes, aunque los valores por defecto
  son seguros;
- F2b, la lupa (D8);
- F3a-bis y F4d, que son opcionales;
- cualquier cambio de vocabulario (D7).

---

## 9. Revisión adversarial (sin terminar de aplicar)

Revisor: agente Opus, 1 nov 2026. Falta la tabla R# | gravedad | veredicto
(corregido / refutado / parcial) | motivo breve. El agente que aplicaba los
hallazgos los contrastó con el código («casi todos se confirman; algunos sólo en
parte»), pero no llegó a dejar el veredicto de cada uno: hay que rehacerlo. Ver el
alcance en la cabecera.

### 9.1 Notas de la sesión principal para aplicarlos

- R1: la regla del proyecto es que ninguna fase visible se implementa antes de que el usuario confirme los D# y el orden. §8.2 debe quedar en lo que la IA puede hacer sin él (preparación, auditorías, capturas «antes», F0 si existe y no cambia nada visible).
- R2: buena idea: implementar en un worktree aparte (sin push) con su propio runserver en 8768 contra la base 55433, para no cambiar la 8766 que el usuario usa mientras da feedback. Incorpóralo en §6.0 con los comandos concretos (helper tools/handoff/garage_demo_pg.py run, settings_test; comprueba cómo sirve los estáticos con --insecure). La 8766 sólo cambia cuando el usuario apruebe.
- R3: el permiso de fuentes ya está dado («baja, claro», 1 nov) y las fuentes están en ~/.cache/stravagancia/fonts-anillos/ con PROCEDENCIA.md (sha256, unicode-range). Quita el bloqueo, y añade la prueba de sha256 con valores fijos en la prueba.
- R19: fontTools no está instalado en el venv de macOS (/Users/maxicombina/.cache/stravagancia/venv-macos) y no se debe instalar nada en él sin pedirlo; propone cómo comprobar `tnum` sin instalar (o déjalo como comprobación visual en capturas) y márcalo.
- R20: para capturas a 320/360/390 px usar CDP (Emulation.setDeviceMetricsOverride) con Chrome sin interfaz y perfil temporal, no iframes.

### 9.2 Hallazgos, literales

R1 · alta · §8.2 contradice la cabecera, §8.1 y CLAUDE.md. La cabecera (l.7-8) pide no implementar ninguna fase antes de que el usuario mire los D#; §8.2 deja a la IA avanzar sola F1a, F2a, F2c, F2d, F2e y F3d con los valores por defecto de D9 y D10, que están marcados [confirmar con el usuario]; §8.1.4 aún pregunta si va antes o después de garage-047/044. CLAUDE.md: «Pruebas locales con el usuario… recogerlo en Beads y priorizarlo con él antes de tocar nada». Corrección: en §8.2 dejar sólo F0, preparación de auditorías y capturas «antes»; toda fase visible espera a la confirmación de los D# y del orden.
R2 · media · §6.0 «siempre en la demo 8766… reiniciar la demo»: la 8766 es la demo que el usuario usa para feedback (garage-047) y Strava con maxi; runserver sirve plantillas y CSS del árbol de trabajo, así que cada fase a medias le cambia la UI. Corrección: worktree aparte sin push con su runserver (p. ej. 8768) contra la misma base 55433; la 8766 sólo cambia cuando el usuario apruebe.
R3 · media · D4, F1b y §8.1.1 dan por pendiente un permiso que ya existe (Beads garage-050 «el usuario autorizó bajar las fuentes», handoff l.51-52). PROCEDENCIA.md lleva los sha256; la spec renombra los archivos a *-wght-v1.woff2 y no menciona comprobar el sha256. La descripción de Beads dice «tema en localStorage» y D5 elige una cookie. Corrección: quitar el bloqueo de F1b y el punto 1 de §8.1; prueba que compare el sha256 de los archivos copiados con valores escritos en la prueba; actualizar Beads cuando se confirme D5.
R4 · media · F1b y §7.1.2 «Las fuentes sólo están sin red si se precargan (STATIC_ASSETS)»: app_views.py:48 precarga asset_url(path), URL con ?v=; el CSS pedirá url(fonts/…woff2) sin ?v=; sw.js:36 hace cache.match(request) sin ignoreSearch, así que la entrada precargada nunca coincide; la fuente sólo entra en caché al vuelo en una página ya controlada; tras cada cambio de versión sw.js:17 borra la caché anterior. Resultado: sin red justo tras instalar o actualizar se ve la fuente del sistema y los 52 kB se bajan dos veces. Las pruebas propuestas («url() está en VERSIONED y STATIC_ASSETS», «sw.js incluye las URL») pasarían igual. Corrección: precargar con la URL exacta sin ?v= (el nombre ya lleva -v1); probar que urljoin(URL del CSS, url()) sea igual carácter a carácter a una entrada de ASSETS del sw.js generado.
R5 · media · §4.1 marca <use class="ring-ic" …> y F3a «mantiene .ring-ic»: .ring-ic ya existe (garage.css:113: width/height 52px, display grid, border…) y la usa index.html:19; esa regla caería sobre el <use>; en SVG 2 width/height pueden actuar como propiedades geométricas y anular el 24×24. Corrección: clase propia (.ring > use.ring-glyph) y añadirla a la lista de choques de D15.
R6 · media · §4.5 «.appbar … con min-height: 56px» y «se mantiene el pliegue a 6 px»: el pliegue reduce .appbar-row a 6 px (garage.css:58-59); con min-height 56px en .appbar la barra mide 56 px siempre y Más queda con franja vacía; un min-height en .appbar-row ganaría al height 6px. Corrección: height 56px en .appbar-row, sin min-height en .appbar, y regla de pliegue height 6px; min-height 0.
R7 · media · F2b «ninguna plantilla contiene el literal «Próximo»… cambio futuro de una línea»: falta maintenance_alerts.html:3 («Próximo significa…»); services/maintenance_due.py:18 LABELS = {… "soon": "Próximo", … "current": "Vigente"} con «Vigente» en vez de «Al día»; maintenance.html:10 y bike_detail.html:23 usan «próximo» en minúscula en frase (con «Pronto» quedaría «lo vencido o pronto»); más usos de «revisar» con icono fijo: statistics.html:43 («Sin bici», st-review con #i-help), avisos .pending st-review con #i-alert en strava.html:6, :8, :18, form.html:5, lifespan.html:21, usage_ride.html:8, ride_review.html:24. Corrección: incluir maintenance_alerts.html y LABELS en F2b o retirar la promesa; decidir icono de «Sin bici · revisar»; dejar explícito que .pending st-review son avisos genéricos, no el estado Revisar.
R8 · media · §3.1 «Los color-mix de … 297 … pasan a usar var(--soft)»: .bar.share en statistics.html:39 y :45 no tiene ancestro st-*; fill: var(--soft) sin respaldo es inválido al calcular y como fill se hereda la pista se pinta negra. Corrección: respaldos siempre (var(--soft, var(--surface-2)), var(--c, var(--primary))) y prueba de guarda: todo var(--soft o var(--c fuera de un bloque .st-* lleva respaldo.
R9 · media · el interruptor .sw no tiene par de contraste en §3.2; --knob #FFFFFF en claro y oscuro; knob/primary en oscuro 2,19:1 < 3:1; carril apagado sin token (con --surface-2, 1,19:1); garage.css:218 box-shadow 0 2px 4px var(--shadow) queda inválida si --shadow pasa a lista; en forced-colors el interruptor desaparece. Corrección: carril apagado en --field (blanco sobre él 3,53:1), botón encendido en oscuro en --on-primary (8,19:1), token de sombra propio, pares knob/field, knob/primary, field/surface y regla .sw en forced-colors.
R10 · media · fases que se pisan: F2d edita garage.css:245-255, que incluye 252-255 de data-os (F2e); §5 asigna a F2c «.sw sin variante Android» (líneas 221-224, también F2e); entre F2d y F2e, en Android la línea 255 (.tab[aria-current] .tab-ic { background: var(--accent-soft) }) tapa la pastilla violeta: 1,21:1 contra la barra (lo que la maqueta descartó, README:130-131). Corrección: F2e antes que F2d, o mover la retirada de 252-255 a F2d, y quitar .sw de F2c.
R11 · media · §7.1.5 «todo anillo va con su chip de estado en la misma fila (lo prueba F2a)», pero F3d pone filas Pospuestos y Sin datos con anillo e icono de pieza; esas filas (maintenance.html:19-25 y :33-39) no tienen chip; su único icono de estado es el .glyph reloj/interrogación, que F3d sustituye; pruebas de F2a sólo cubren _wear_row. Corrección: chip con icono y palabra («Pospuesto», «Sin datos») en esas filas y prueba en F3d.
R12 · baja · F3c «la palabra sale de services/lifecycle.py:20-30»: no hay constante «Montado»; RETIRED_TEXT = «Retirado el» necesita fecha; el docstring dice que es la única fuente y F3c no incluye lifecycle.py; en la lista «Retirado» sigue siendo chip st-nodata sin icono (list.html:19, fijado por tests_lifecycle.py:277), en la cabecera sería .chip.life: dos aspectos para el mismo estado; la .lede ya repite life_text. Corrección: palabras de chip en lifecycle.py con prueba, y documentar la excepción de la lista o unificar aspecto.
R13 · baja · F2b/F3c añaden símbolos al sprite: tests_categories.py:71 exige que no haya fill= después de id="i-chainring"; i-sparkle e i-user suelen ir con relleno. Corrección: sólo trazo, o colocarlos antes de i-chainring.
R14 · baja · §4.6/§7.3: portada no está en riesgos de rendimiento: photo-content responde no-store y redirige a URL firmada distinta cada vez (photo_views.py:52-64); fotos hasta 2000 px WebP (garage/photos.py:18, :125) sin miniatura; cada visita baja la imagen entera para una tesela de 112 px, y otra vez en «Fotos privadas» (photo_list.html:4); enlace «Añadir foto» duplicado (photo_list.html:2). Corrección: añadir a §7.3 y D2 y decidir con el usuario si se acepta o se espera a miniaturas (garage-010/022).
R15 · baja · F3e-1 tesela de fecha: started_at puede ser nulo («Inicio desconocido», usage_rides.html:13); la prueba del texto accesible pasa aunque la tesela aria-hidden muestre el día en UTC. Corrección: probar el día visible con dos zonas (caso «Nocturna» 01:30 UTC de TimeZoneCookieTests) y el caso sin inicio.
R16 · baja · §4.8 vista appearance «con sesión»: POST con sesión caducada lleva al login con next=/garage/appearance/ y al volver GET → 405; en iOS la app instalada tiene cookies propias separadas de Safari; con «Automático» el JS tiene que recrear las dos meta theme-color con media. Corrección: permitir la vista sin sesión (con CSRF) o redirigir GET a more; documentar iOS y la restauración de las meta.
R17 · baja · forced-colors: .ring use { stroke: var(--ink) } no se fuerza; con data-theme="light" y contraste alto oscuro el icono queda invisible; si todos los .chip-link reciben el mismo borde de 2 px el filtro elegido no se distingue. Corrección: stroke: currentColor con .ring { color: var(--ink) }, y .chip-link.on con borde más grueso o subrayado.
R18 · baja · §4.2/§4.5 omiten un borde de la maqueta: border 1px solid var(--card-border) en .nav, filtros e .icon-btn (design/option-1/index.html:67, :229, :294); en oscuro surface sobre bg 1,09:1, --shadow none y --shadow-float invisible: la barra flotante y los filtros pierden el borde. Corrección: añadir ese borde.
R19 · baja · F1b cobertura de glifos y cifras tabulares: el unicode-range de PROCEDENCIA no incluye U+2265 ≥, U+2248 ≈ ni U+2192 → (item_detail.html:60); saldrán en la fuente del sistema. Sin verificar si Outfit tiene tnum (no hay fontTools); --num deja de ser monoespaciada. Corrección: comprobar con fontTools antes de cambiar --num y revisar en capturas los chips con ≥ y ≈.
R20 · baja · §6.0 capturas: faltan 320 y 360 px («Estadísticas» a 11 px en pestaña de ~60 px; chips nowrap como «Pospuesto · ≥ 100 %» junto a «↑ m de más como mín.»), falta un apaisado; Chrome sin interfaz no baja de 500 px de ventana y el truco del iframe no sirve con XFrameOptionsMiddleware (strava_app/settings.py:64). Corrección: 320, 360 y apaisado, comprobación de desborde (scrollWidth > clientWidth), Emulation.setDeviceMetricsOverride.
R21 · baja · §4.1 añadir percent_text al aria-label de item_detail.html:16 «para que diga al menos»: percent_text produce «≥»/«≈», no «al menos»; el chip de :21 ya lo expone y se leería dos veces. Corrección: no hacerlo, o en palabras ocultando la duplicación.
R22 · baja · F2a convierte el icono deducido en el centro de cada anillo; sigue pendiente que el usuario confirme el «cambio visible» de la deducción de iconos (spec 041 §7.7, CLAUDE.md). Corrección: listar esa dependencia en §8.1 y F2a.
R23 · baja · F2a constancia de consultas en Inicio: Inicio pinta como mucho 6 filas (home.py:17, :133); si el estado de partida ya llega a 6, añadir 8 reglas no añade filas y no detecta N+1. Corrección: menos de 6 filas al partir y reglas nuevas que requieran atención, o medir en Taller.
R24 · baja · F3a «Material sin montar» y «km · h · ↑ m»: el título real es «Equipación y material sin montar» (tests_mobile_home.py:190); «↑ ≥» y que «↑» aparezca una sola vez están fijados por tests_elevation_screens.py:348 y tests_elevation_review.py:216. Corrección: decir que título y marca del mínimo no cambian.
R25 · baja · D17/§4.6 chip «N avisos» con icono del estado más grave: la gravedad sólo se ve (icono aria-hidden, la palabra es un recuento). Corrección: sr-only «el más grave: Vencido».
R26 · baja · aceptación de F3b se cumple sola: «Registrado en Garage» va antes (bike_detail.html:10-19). Corrección: exigir la primera fila de «Requiere atención» (o su mensaje vacío) entera por encima de la barra flotante a 390×844.
R27 · baja · pruebas que reflejan implementación: F2e compara con la lista exacta de 6 selectores; §3.3 test_state_classes (7×2); la aceptación de F2a ««90 %» sigue ahí» siempre se cumple (notas fijas de index.html:45 y maintenance.html:13). Corrección: buscar el porcentaje dentro del chip de la fila y medir F2e por lo que se ve, con capturas por agente de usuario.
R28 · baja · D12 «estructura preparada» para pieles: :root[data-skin=x] (0,2,0) empata con @media … :root:not([data-theme="light"]) (0,2,0); dependería del orden y cada piel necesitaría tres bloques. Corrección: documentar el patrón o quitar la afirmación.
R29 · baja · citas: rutas tests_*.py citadas están en garage/ aunque la spec dice relativas a la raíz (y en la raíz hay otros tests_*.py); «Powered by Strava» está en tests_strava_views.py:62, :117 y :183-192, no en :496; upload (tests_photos_domain.py:88) es función auxiliar, no fixture; D13 dice 12 subcasos y test_active_tab_follows_the_section tiene 11; credenciales de demo están en docs/garage-progress-state.json, no en CLAUDE.md; D2 cita photos = list(...) en views.py:110 pero hoy es un QuerySet (el list(...) es lo que hay que añadir).
Total: 1 alta, 10 media, 18 baja.
