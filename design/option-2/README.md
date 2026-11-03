# Opción 2 · Bitácora (cuaderno de taller)

> Garage como el cuaderno de un mecánico: cada bici y cada pieza tiene su página, con el desgaste anotado en cifras y el historial escrito como un diario.
> Para quien disfruta repasando el historial y las notas de cada pieza y quiere una herramienta sobria, que informe sin gritar.

Abre `index.html` directamente (`file://`, sin servidor). Todo está en un único archivo: CSS en `<style>`, iconos SVG propios en línea y unas 50 líneas de JS.

- **Navegación:** cada pantalla es una `<section id>` y se muestra con `:target`, así que funciona sin JS. Pantallas: `#garaje` (inicio), `#bici-rallon`, `#bici-grizl`, `#material`, `#pieza-cadena` (ficha), `#taller`, `#registrar`, `#salidas`, `#estadisticas`, `#mas`, `#strava` y `#sobre` («Sobre esta dirección»: tokens, contrastes, trade-offs y supuestos dentro de la propia maqueta, con un enlace a este README).
- **Tema:** sigue `prefers-color-scheme`. El botón «Modo oscuro» es un conmutador (`aria-pressed`): cuando el modo oscuro está activo se ve en negativo y con la luna rellena. Fija la elección y **se recuerda** en `localStorage` (`garage-bitacora-tema`). En «Sobre esta dirección» → Supuestos hay un botón para volver al modo del sistema. Para forzar un tema sin tocar nada: `index.html?tema=oscuro#taller` o `?tema=claro`.

## La idea

| Eje | Decisión |
|---|---|
| Personalidad | Libro de registro: cálido, artesanal y sobrio. Nada parpadea ni se rellena de color. |
| Tipografía | Una serifa con tamaños ópticos para todo lo que se lee **y para las cifras** (numerales de caja alta, tabulares en tablas, filas y ejes). Una **máquina de escribir** para lo que se anota o se sella: fechas, etiquetas en mayúsculas y sellos. |
| Paleta | Papel cálido en claro; pizarra y tinta en oscuro. Cuatro tonos con significado (lacre, ocre, verde y tinta azul) y el resto, neutros. |
| Estado | Se marca, no se pinta: **sello** con la palabra en mayúsculas de máquina de escribir y un borde que cambia de forma (doble = Vencido, simple = Pronto y Al día, sin borde = En curso, discontinuo = Sin datos), una **regla graduada** fina en lugar de anillos o barras gruesas y, en las listas de mantenimiento (Taller y Requiere atención), una **marca al margen** (octógono, triángulo, círculo a medias, visto, interrogación). |
| Piezas | En las listas de piezas (Material, Material sin montar y el árbol de cada bici), el margen lleva el **glifo de la categoría** (horquilla, amortiguador, cadena, casete, pastillas, neumático, líquido, rodamientos, casco), como hace la app actual con sus iconos de categoría. |
| Densidad | Alta pero tranquila: muchas filas, líneas de 1 px, sin tarjetas ni sombras. |
| Espacio | Móvil: una columna con la línea de margen rojiza del cuaderno a la izquierda de las listas. Tableta (≥ 600 px): misma columna más ancha; las tablas recuperan la columna «Uso». Escritorio (≥ 1024 px): **índice** a la izquierda (pestañas con puntos guía) y, desde 1200 px, **notas al margen** a la derecha. |
| Material | Montado · Disponible (Sin estrenar) · En uso · Retirado no son alarmas: van sin color, con un glifo pequeño (círculo lleno, vacío, a medias y tachado) y la palabra. |

## Tokens

### Color y contraste

Los valores salen del propio `index.html` (bloques `/* tokens:claro */`, `/* tokens:oscuro */` y su copia en `@media (prefers-color-scheme: dark)`). El script de contraste comprueba también que las dos copias del tema oscuro son idénticas. WCAG 2.x: texto ≥ 4,5:1; bordes, reglas, marcas, barras y anillo de foco ≥ 3:1.

| Token | Uso | Claro | Oscuro |
|---|---|---|---|
| `--paper` | Papel: fondo de página | `#f3eee3` | `#1a1c1f` |
| `--leaf` | Hoja: barra de pestañas y campos | `#faf7f0` | `#222529` |
| `--ink` | Tinta: texto principal, botón principal | `#26221d` | `#ebe3d3` |
| `--ink-2` | Tinta 2: texto secundario, En curso, Sin datos, barras y glifos de categoría | `#5c5348` | `#b3aa9a` |
| `--accent` | Tinta azul: enlaces | `#234a85` | `#9fbbe8` |
| `--due` | Lacre: Vencido | `#a3301c` | `#f0937c` |
| `--soon` | Ocre: Pronto | `#85570a` | `#e0b05c` |
| `--ok` | Verde: Al día | `#3b6a2c` | `#9ccb84` |
| `--rule-strong` | Línea fuerte: bordes de campo, escala de las reglas | `#8c8070` | `#7b7568` |
| `--rule` | Línea fina: separadores (decorativa) | `#d6ccba` | `#3a3d42` |
| `--margin` | Margen del cuaderno (decorativa) | `#e6bfb0` | `#4d3a35` |
| `--focus` | Anillo de foco | `#234a85` | `#9fbbe8` |

| Par | Uso | Claro | Oscuro | Mínimo AA |
|---|---|---:|---:|---|
| `--ink` sobre `--paper` | Texto principal | 13,66:1 | 13,38:1 | 4,5:1 |
| `--ink` sobre `--leaf` | Texto en campos y pestaña activa | 14,77:1 | 12,06:1 | 4,5:1 |
| `--ink-2` sobre `--paper` | Texto secundario, etiquetas, En curso, Sin datos; barras del gráfico y glifos de categoría (≥ 3:1) | 6,51:1 | 7,43:1 | 4,5:1 |
| `--ink-2` sobre `--leaf` | Pestañas inactivas, marcador de campo | 7,05:1 | 6,69:1 | 4,5:1 |
| `--accent` sobre `--paper` | Enlaces | 7,60:1 | 8,74:1 | 4,5:1 |
| `--due` sobre `--paper` | Sello y marca Vencido | 6,06:1 | 7,46:1 | 4,5:1 |
| `--due` sobre `--leaf` | Contador de avisos en la barra | 6,55:1 | 6,72:1 | 4,5:1 |
| `--soon` sobre `--paper` | Sello y marca Pronto | 5,39:1 | 8,57:1 | 4,5:1 |
| `--ok` sobre `--paper` | Sello y marca Al día | 5,53:1 | 9,18:1 | 4,5:1 |
| `--paper` sobre `--ink` | Botón principal, filtro activo, botón de tema activo y etiqueta emergente del gráfico | 13,66:1 | 13,38:1 | 4,5:1 |
| `--rule-strong` sobre `--paper` | Bordes de campo y de botón secundario, reglas | 3,34:1 | 3,73:1 | 3:1 |
| `--rule-strong` sobre `--leaf` | Borde de campo por dentro | 3,61:1 | 3,36:1 | 3:1 |
| `--focus` sobre `--paper` | Anillo de foco | 7,60:1 | 8,74:1 | 3:1 |
| `--focus` sobre `--leaf` | Anillo de foco sobre hoja | 8,21:1 | 7,88:1 | 3:1 |
| `--rule` sobre `--paper` | Líneas finas entre filas y rejilla del gráfico | 1,37:1 | 1,57:1 | decorativa |
| `--margin` sobre `--paper` | Línea de margen | 1,46:1 | 1,60:1 | decorativa |

El par más justo es el ocre de «Pronto» en claro (5,39:1). Las líneas finas, la rejilla del gráfico y la línea de margen son decorativas a propósito: nunca son la única frontera de un control ni la única forma de leer un valor. Los campos llevan borde `--rule-strong` (≥ 3:1) y una raya inferior de 2 px en `--ink`.

### Fuentes

| Papel | Fuente | Respaldo |
|---|---|---|
| Titulares, texto, botones, notas en cursiva **y cifras** | **Newsreader** (Google Fonts, OFL), variable con tamaños ópticos 6–72, pesos 400–700 y cursiva 400–600. Cifras con `lining-nums tabular-nums` en tablas, filas, ejes y recuentos; `proportional-nums` en las cifras grandes sueltas (ficha técnica de la bici, cifra grande de la ficha) | Iowan Old Style, Palatino, Book Antiqua, Georgia, serif |
| Fechas, etiquetas en mayúsculas, sellos, migas, pestaña de tema, campos de fecha y hora | **Courier Prime** (Google Fonts, OFL), máquina de escribir, 400 y 700 | ui-monospace, SF Mono, Menlo, Consolas, Courier New, monospace |

Dos familias enlazadas desde Google Fonts con `display=swap`. Sin conexión, la maqueta se ve con el respaldo (con Georgia, las cifras salen de estilo antiguo: no tiene numerales de caja alta). Se comprobó en Chrome que la Newsreader servida por Google Fonts trae cifras tabulares (diez «1» y diez «0» miden lo mismo con `tabular-nums`: 228,16 px a 40 px; 151,33 y 246,48 px en proporcional) y numerales de caja alta.

La máquina de escribir no es una monoespaciada técnica: aquí no alinea cifras (eso lo hacen las tabulares de la serifa). Sólo pone la voz del cuaderno en lo que se anota o se sella. Courier Prime sólo trae 400 y 700: las etiquetas van en 400 y los sellos en 700.

### Escala tipográfica

Escala de segunda mayor (≈ 1,125) en el texto, con saltos dobles en los titulares. Base: 17 px.

| Token | Tamaño | Uso |
|---|---|---|
| `--t-xs` | 13 px (0,8125 rem) | Etiquetas en mayúsculas, fechas cortas y sellos (Courier Prime); cifras de los ejes del gráfico (serifa) |
| `--t-sm` | 15 px (0,9375 rem) | Metadatos, notas, cifras de tabla (serifa tabular) |
| `--t-md` | 17 px (1,0625 rem) | Texto, botones, campos (los de fecha y hora, 16 px) |
| `--t-lg` | 19 px (1,1875 rem) | Entradilla en cursiva, títulos de fila |
| `--t-xl` | 22 px (1,375 rem) | Títulos de sección (con «§» y filete) |
| `--t-2xl` | 28 px (1,75 rem) | Cifras grandes (serifa): 4.812 km |
| `--t-3xl` | 34–48 px (`clamp`) | Título de página |

Interlineado: 1,5 en el texto, 1,04 en el título y 1,3 en los títulos de fila. Ningún campo de formulario baja de 16 px (iOS Safari amplía la página al enfocar uno más pequeño).

### Radios

| Token | Valor | Uso |
|---|---|---|
| `--r-0` | 0 | Tablas, reglas, filetes |
| `--r-1` | 2 px | Botones, campos, sellos, filtros, etiqueta emergente |
| `--r-2` | 4 px | Remate superior de las barras de «Km por mes» |

### Espaciado

Base de 4 px: `--s-1` 4 · `--s-2` 8 · `--s-3` 12 · `--s-4` 16 · `--s-5` 24 · `--s-6` 32 · `--s-7` 48 · `--s-8` 64. Medida de lectura: 40 rem en móvil y tableta; columna principal de unos 43 rem en escritorio, con notas al margen de 14 rem.

### Líneas y sombras

No hay sombras. Se usa 1 px para separar filas, doble raya para cerrar (totales, cabecera y barra de pestañas) y la línea de margen rojiza de 1 px en las listas, donde viven las marcas y los glifos.

## Accesibilidad

- Contraste AA verificado por script (abajo), en claro, en oscuro y en el oscuro del sistema.
- Estado nunca sólo por color: palabra en el sello + forma del borde, y marca al margen en las listas de mantenimiento. Las reglas graduadas llevan `role="img"` y `aria-label` con la cifra.
- Foco visible: anillo de 3 px en `--focus` con separación de 2 px, también en los filtros (radios ocultos visualmente) y en las columnas del gráfico.
- Objetivos táctiles de al menos 44 px, medidos en el navegador en las 12 pantallas a 500 y 1280 px: pestañas de 48–60 px, botones y campos de 48 px, y filtros, migas, enlaces de acción, «Ver como tabla» y botón de tema de 44 px o más. Las filas enlazadas se pueden tocar enteras (enlace estirado). Los enlaces dentro de tablas, del diario y de notas tienen un área táctil ampliada con relleno y margen negativo, sin mover la maquetación. Las columnas del gráfico miden de 26 px de ancho (a 375 px) a 42 px (a 1280 px), por 143 px de alto.
- Campos de formulario de 16 px o más (fecha y hora, 16 px en Courier Prime; el resto, 17 px).
- Semántica: `header`, `main`, `nav` con `aria-label`, una `h1` por pantalla y `h2`/`h3` por sección; listas `ol`/`ul`; tablas con `caption`, `th scope` y `colgroup`; formulario con `label for`, `fieldset` y `legend`.
- «Km por mes»: una sola serie, sin leyenda (la nombra el título). Cada columna se puede enfocar y tiene `aria-label` («mayo de 2026: 380 km»); al pasar el ratón o enfocarla aparece la cifra. Dos valores rotulados (el máximo y el último mes completo) y la tabla completa en «Ver como tabla» (`<details>`, sin JS): la etiqueta emergente nunca es la única forma de leer un valor.
- Al cambiar de pantalla, el JS mueve el foco a su `h1`, actualiza `aria-current` (`page` en la pestaña o la entrada exacta, `true` en el grupo) y cambia el `<title>`.
- `prefers-reduced-motion`: la única animación (entrada de la hoja, 220 ms) se desactiva.
- En móvil, las tablas del taller ocultan la columna «Uso» y llevan la cifra dentro de la primera celda, sin duplicarla para los lectores de pantalla; la columna Estado mide lo que el sello más ancho y el nombre se queda el resto.

## Lo que sacrifica (trade-offs)

1. **Lectura de un vistazo.** Sin bloques de color, un vencido se ve menos que en una interfaz de tarjetas rojas: hay que leer la fila. Lo compensan la marca al margen y el sello de doble raya, pero grita menos, y eso es a propósito.
2. **Densidad en móvil.** Mucho texto bien compuesto ocupa: la ficha de una pieza, la bici y el taller son largos y piden desplazarse.
3. **Etiquetas de máquina de escribir.** Courier Prime a 13 px es más fina y más ancha que una sans: las etiquetas y los sellos se leen algo peor y ocupan más que en una interfaz técnica. Por eso van en mayúsculas, son cortas y nunca llevan las cifras que hay que comparar.
4. **Dos fuentes web.** Tal como están enlazadas pesan unos **295 KiB** en woff2 (subconjunto latino, descargado y medido el 01/11/2026): 272 KiB son la Newsreader variable con tamaños ópticos (redonda 129 y cursiva 144) y 22 KiB, la Courier Prime (11 + 11). Sin el eje de tamaños ópticos bajaría mucho. Hoy Garage no usa fuentes externas: habría que servirlas desde la app, guardarlas en la caché de la PWA para usarla sin conexión y aceptar que, mientras se cargan, se ve el respaldo. Si se enlazan desde Google Fonts, Google recibe la IP de quien abre la app.
5. **Sin aspecto nativo.** No imita iOS ni Android. La app actual distingue los dos sistemas y esta dirección los iguala.
6. **Envejecimiento.** Lo editorial y lo de papel es una moda reconocible y con los años puede parecer «estilo 2020»; la máquina de escribir subraya el gesto. La estructura (tablas, reglas, tipografía) envejece mejor que la textura, y aquí casi no hay textura: no hay fondos de papel, ruido ni ilustraciones.
7. **Gráficos.** Las reglas lineales comunican menos que los anillos actuales cuando una pieza tiene varias reglas. El gráfico «Km por mes» de cada bici (está en la maqueta, en `#bici-rallon` y `#bici-grizl`) queda igual de sobrio: barras finas en `--ink-2`, rejilla decorativa, dos cifras rotuladas y la tabla a un toque. Informa, pero no luce.
8. **Coste de implementar: medio-alto.** El CSS actual se reescribe casi entero (tipografía, filas, sellos y reglas en lugar de anillos) y **las plantillas cambian de estructura**:
   - Taller, Salidas, Estadísticas, Montajes de la ficha y Bicis de Strava pasan de `<ul class="rows">` a `<table>` (hoy la única tabla es la accesible de `_chart.html`).
   - El Taller se reagrupa: hoy es «Requiere atención» (vencido y próximo), «Sin datos» y «En curso y al día»; aquí son cinco grupos (Vencido, Sin datos, Pronto, En curso, Al día), cada uno con su tabla.
   - Lo montado en la bici se agrupa por categoría, con el árbol de piezas anidadas.
   - `_ring.html` se convierte en una regla graduada y `_chart.html` en columnas finas con tabla desplegable.
   - El índice lateral y las notas al margen de escritorio son trabajo nuevo en `base.html` y en cada plantilla que tenga notas.
   - Los iconos de categoría actuales se pueden reutilizar tal cual o redibujar con este trazo (los de la maqueta son propios, dibujados aquí).

## Supuestos

- **Datos:** el juego ficticio común a las tres opciones. Inventado aquí, por necesidad de la pantalla: la nota de la cadena, el detalle «delantero y trasero» del purgado de frenos, la sustitución de la cadena el 12/05/2026 (la fecha en que se retiró la anterior), «Al 71 %» del amortiguador sin horas absolutas, el importe vacío del formulario, los kilómetros de cada mes de «Km por mes» y la fecha de la importación del histórico de Strava (18/10/2026, desde el 01/01/2019). Los meses de la Rallon cuadran con los datos: desde el 12/05 suman los 1.860 km de la cadena, y los 12 meses (3.290 km) caben en sus 4.812 km; los de la Grizl suman 1.545 de 2.140 km.
- **Calculado a partir de los datos:** el líquido tubeless venció el 23/10/2026 (60 días desde el 24/08), la cadena está al 93 % y le quedan 140 km, y el total de las 4 salidas es 165,5 km, 8:58 y 2.740 m.
- Se usa **«Pronto»**, como pide el encargo; la app actual dice «Próximo». Su definición es la del dominio: **alcanzar** el 90 % de un umbral.
- **Orden del Taller:** Vencido, Sin datos, Pronto, En curso, Al día, el orden de estado de `docs/garage-domain.md` (vencido, desconocido, próximo, vigente): una regla sin datos puede estar vencida sin que se sepa. La app junta «En curso y al día»; aquí van aparte para que el taller se lea como un libro de cuentas.
- **Strava:** la sincronización automática se explica con texto, como en la app (el Worker de Cloudflare la pide cada día a las 9:05, hora de Madrid); la importación del histórico tiene su propia fecha. Las cifras de estado son la conexión, la última sincronización (hoy 09:05), las salidas importadas (350) y las bicis vinculadas (2).
- Sólo la cadena SRAM GX Eagle montada tiene ficha. Las demás filas no son enlaces, en vez de llevar a una ficha equivocada. El formulario viene preparado para la horquilla vencida y ofrece en «También en esta visita» el líquido, la cadena y el amortiguador.
- El filtro de Material empieza en **«Todos»** para que se vean los cuatro estados; cada filtro muestra su recuento. Es CSS puro (radios + `:has()`).
- Material y la ficha cuelgan de la pestaña Garaje, como en la app (`tab_for`). Strava y «Sobre esta dirección» cuelgan de Más.
- En Más, Categorías, Perfiles de uso, Exportar e Instalar aparecen como «no está en la maqueta», sin enlace.
- Los nombres de bici y de modelo no se parten (espacio no separable en «Orbea Rallon», «Canyon Grizl» y «Float X»; «G-One» sin cortar) y los separadores «·» quedan al final de la línea, nunca al principio.
- Fecha de hoy en la maqueta: domingo 1 de noviembre de 2026.
- JS imprescindible y nada más: el tema antes de pintar (evita el destello), el conmutador, `aria-current`, el foco y el título. La navegación, los filtros, la etiqueta emergente y la tabla del gráfico funcionan sin JS.

## Cambios tras la revisión del 1 nov 2026

| Hallazgo | Cambio |
|---|---|
| Campos de 15 px (zoom en iOS) | Fecha y hora a 16 px en Courier Prime; el importe hereda 17 px. Medido: ningún campo por debajo de 16 px. |
| Misma monoespaciada que la opción 3 | IBM Plex Mono fuera. Cifras en las tabulares de Newsreader; fechas, etiquetas y sellos en Courier Prime. |
| Conmutador de tema sin cambio visible | La regla iba a un `path` dentro del `<symbol>`; ahora va al `<svg>` y el botón activo se ve en negativo. Medido: relleno `none` → color del texto. |
| «Sin datos» al final del Taller | Va detrás de «Vencido», con una nota que lo explica. |
| Sin iconos de categoría; punto igual a «Disponible» | Glifos de categoría propios en Material, Material sin montar y el árbol de cada bici; el punto desaparece. |
| Respaldo sin `:has()` roto | `.screen:target` va en su propia regla. Simulado: antes sólo se veía el Garaje; ahora, el Garaje y la pantalla pedida. |
| Coste subestimado; sin gráfico mensual | Coste medio-alto con la lista de cambios de plantilla; «Km por mes» añadido a las dos bicis. |
| Cortes de línea en móvil; «30» sin decimal | Columna Estado a la medida del sello en móvil, nombres y cifras sin partir, «30,0». |
| «haber pasado el 90 %» | «alcanzar el 90 %». |
| «Sobre esta dirección» incompleta | Trade-offs y supuestos iguales que aquí, y enlace a este README. |
| Dos «09:05» en Strava | La automática se explica con texto; el histórico tiene su fecha. |

## Verificación (ejecutada el 1 nov 2026, tras la revisión)

Scripts y capturas fuera del repositorio, en `/private/tmp/claude-501/design-work/option-2/`:

- `contrast.py`: lee los tokens del HTML, comprueba los 14 pares obligatorios (y 2 decorativos) en los dos temas y que las dos copias del tema oscuro coinciden. Además escribe la tabla de «Sobre esta dirección». Resultado: **14 × 2 cumplen, 0 fallos**. Los cambios de la revisión no tocaron ningún color; los nuevos usos (botón de tema activo, barras, glifos, etiqueta emergente) caen en pares ya medidos.
- `check.js` + `run_checks.sh`: inyecta un comprobador en una copia de la maqueta y recorre **12 pantallas × 3 temas (claro, oscuro, oscuro del sistema) × 2 anchos (500 y 1280 px)**. Mide cada texto visible contra su fondo efectivo y cada marca, glifo, relleno de regla, barra del gráfico, sello y borde de campo contra el suyo. Resultado: **72 ejecuciones, 6.174 textos y 912 gráficos o bordes, 0 fallos**; en cada ejecución se mide la pantalla pedida. El par de texto más bajo fuera de la muestra de la paleta es `#85570a` sobre `#f3eee3` (5,39:1) en claro y `#b3aa9a` sobre `#222529` (6,69:1) en oscuro.
- Integridad: todos los enlaces internos llevan a un id que existe; ni ids duplicados ni `label` sin campo; una `h1` por pantalla.
- `targets.js` + `run_targets.sh`: miden en el navegador el tamaño de cada enlace, botón y campo en las 12 pantallas a 500 y 1280 px. Resultado: **0 objetivos por debajo de 44 px**. Aparte, «Ver como tabla» mide 116 × 44 px y las columnas del gráfico, 26 × 143 px (375 px, medido dentro de un iframe), 36 × 143 px (500 px) y 42 × 143 px (1280 px).
- Prueba funcional en Chrome sin interfaz: el conmutador alterna, guarda y vuelve al sistema, y ahora también cambia de aspecto (fondo transparente → `--ink`, relleno de la luna `none` → color del texto); `aria-current` y el foco en la `h1` funcionan; el filtro «Retirados» deja sólo la cadena retirada.
- Navegador sin `:has()`, simulado con una copia en la que `:has(` pasa a ser una pseudoclase desconocida: con el CSS anterior, `#taller`, `#registrar` y `#strava` mostraban sólo el Garaje; con el actual muestran el Garaje y la pantalla pedida.
- Fuentes: con la URL actual de Google Fonts se descargaron los woff2 del subconjunto latino (295 KiB en total) y se comprobó en Chrome que se cargan las cuatro caras (Courier Prime 400 y 700, Newsreader redonda y cursiva).
- Capturas con Chrome sin interfaz y perfil temporal, a 375, 390, 768 y 1280 px, en claro, en oscuro y en el oscuro del sistema (`shots2/`, 28 capturas tras la revisión, una de ellas con la etiqueta emergente del gráfico enfocada; las anteriores siguen en `shots/`). Chrome sin interfaz en macOS no baja de 500 px de ancho de ventana, así que las capturas usan un iframe del tamaño exacto. Lo que se corrigió al verlas: barras del gráfico demasiado gruesas, meses del eje amontonados en móvil (ahora uno de cada dos por debajo de 600 px), «ui-monospace» partido y la leyenda de material, que se cortaba antes del «·».

**No verificado:** Safari de iOS y Chrome de Android reales (sólo Chrome de escritorio sin interfaz, con la página en un iframe del ancho del teléfono): en particular, que iOS ya no amplíe al enfocar los campos se deduce del tamaño medido (16 px), no se ha probado en un iPhone. Tampoco Firefox, lectores de pantalla (VoiceOver, TalkBack) ni un navegador real sin `:has()` (Safari/iOS < 15.4, Firefox < 121); allí el filtro de Material no filtra y el Garaje queda siempre visible encima de la pantalla pedida.
