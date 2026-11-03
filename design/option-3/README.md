# Opción 3 · Telemetría

**Intención.** Telemetría trata el garaje como un banco de pruebas: todas las cifras a la vista, en una rejilla estricta, con barras alineadas que se comparan de un vistazo, como los canales de un registro de datos. Encaja con quien mantiene su bici con mentalidad de mecánico o de ingeniero, quiere todos los números a la vez y compara piezas como datos. No encaja con quien busca una app cálida o mínima.

Maqueta: [`index.html`](index.html), autocontenida (CSS en `<style>`, iconos SVG propios, 51 líneas de JS). Dentro, **Más → Sobre esta dirección** (`#sobre`) repite esto con muestras de color, contrastes, escala, radios y espaciado.

## Cómo verla

- Abre `index.html` directamente (`file://`); no hace falta servidor.
- Pantallas (todas enlazadas entre sí y con la navegación): `#garaje` (inicio), `#bici-rallon`, `#bici-grizl`, `#material`, `#pieza-cadena`, `#pieza-fox38`, `#taller`, `#registrar`, `#salidas`, `#estadisticas`, `#mas`, `#strava` y `#sobre`.
- **Tema**: el botón de la barra superior tiene tres estados, **Sistema · Claro · Oscuro**, y muestra el actual: el icono (círculo a medias, sol o luna) y, desde 768 px, el texto «Tema: …». Su `aria-label` dice el estado y el siguiente. El orden del ciclo hace que cada pulsación cambie algo visible: Sistema → el contrario del sistema → el del sistema → Sistema. Claro y Oscuro **se recuerdan** en `localStorage` (clave `garage-telemetria-tema`) y Sistema borra lo guardado. `?tema=claro` u `?tema=oscuro` fuerzan un tema sin guardarlo; `?tema=sistema` borra lo guardado.
- **Fuentes**: vienen de Google Fonts. Sin red, iOS y macOS usan Avenir Next Condensed, Android usa `sans-serif-condensed` y, si no hay ninguna, `system-ui` (SF Pro en Apple, Roboto en Android). Las condensadas del sistema no se han probado en teléfonos reales. Lo que sí se ha probado es el peor caso, sólo `system-ui` a 375 px: no se corta nada, pero algunos nombres largos ocupan dos líneas. Para la PWA sin red, **autoalojar las dos familias es un requisito**, no una opción (ver «Fuentes»).

## En qué se separa del estilo actual «Instrumentos»

| | Instrumentos (hoy, `garage.css`) | Telemetría |
|---|---|---|
| Unidad básica | Fila de lista con anillo de 52 px (≈ 74 px de alto) | Fila de **tabla** con columnas alineadas; en móvil, **53 px** en dos líneas |
| Desgaste | Anillo circular con el % dentro | **Barra horizontal** de 0 a 125 % con marcas de aviso (90 %) y de umbral (100 %) |
| Comparar piezas | Una a una | Las barras de una tabla comparten escala y origen, así que se comparan en vertical |
| Color de interfaz | Acento cobalto en enlaces, botones y anillos | **Monocroma**: el color sólo marca el estado; no hay acento de marca |
| Neutros en oscuro | Azul noche (`#0a0c11`, `#141822`, `#8f98aa`) | **Grafito con tinte fósforo** (`#0e1311`, `#151b18`, `#9db5a8`). ΔE76: fondo 4,5; panel 10,0; texto 7,2; líneas 14,8; texto secundario 20,4 |
| Neutros en claro | Gris azulado y blanco puro | Gris verdoso de papel de registro (`#e3e9e6`, panel `#f8fbf9`). ΔE76: fondo 5,1; panel 2,2 |
| Estados | Verde, ámbar, rojo; «En curso» con el cobalto | Rojo, ámbar y verde, y **cian** para «En curso» |
| Tipografía | Sistema, más la monoespaciada del sistema | IBM Plex Sans **Condensed** + **JetBrains Mono**, etiquetas en **versalitas** |
| Radios | 10–16 px, píldoras | **0 en todo** |
| Iconos de estado | Octógono, alerta, indicador, círculo con marca | **Pilotos cuadrados** de panel (ver «Componentes») |
| Escritorio | Una columna de 760 px | Barra lateral y rejilla de 12 columnas; las tablas ocupan todo el ancho |

Las dos tienen modo oscuro con `prefers-color-scheme`, así que eso no las diferencia. Lo que separa sus paletas es el tinte de los neutros, que se puede medir (ΔE arriba), y la ausencia de acento.

**Frente a la opción 2.** También usa tablas densas y cifras monoespaciadas, pero en su caso son IBM Plex Mono, Newsreader, radios de 0, 2 y 4 px e iconos de octógono, triángulo y círculo, sobre papel cálido. Telemetría usa otra monoespaciada (JetBrains Mono) y una sans condensada, sin serifa; un único radio de 0; iconos cuadrados de panel, y neutros fríos con tinte verde.

## Tokens

### Color

Los nombres son los de las variables CSS. `*-t` es la variante para **texto** (chips y cifras de estado); la base es para **rellenos, franjas y rayas**. Separarlas permite un ámbar saturado en las barras sin bajar del 4,5:1 en el texto.

| Token | Claro | Oscuro | Uso |
|---|---|---|---|
| `--bg` | `#e3e9e6` | `#0e1311` | Fondo de la página |
| `--panel` | `#f8fbf9` | `#151b18` | Paneles, tablas, barras de navegación |
| `--panel-2` | `#eff3f1` | `#1c2420` | Filas de grupo, hover, pestaña activa en escritorio |
| `--field` | `#ffffff` | `#111714` | Fondo de campos de formulario |
| `--rule` | `#cfd8d3` | `#28332e` | Líneas finas de la rejilla (decorativas) |
| `--rule-strong` | `#6b7a72` | `#6d8077` | Bordes de campos, filtros, botón secundario, etiquetas de ciclo de vida |
| `--track` | `#dbe3df` | `#27322d` | Pista de las barras |
| `--ink` | `#0c120f` | `#e2ece6` | Texto principal, cifras, botón principal, foco |
| `--ink-2` | `#45544c` | `#9db5a8` | Texto secundario, cabeceras, unidades, marca de aviso |
| `--due` / `--due-t` | `#c9281e` / `#ab2018` | `#ff6a5c` / `#ff8a7e` | Vencido |
| `--soon` / `--soon-t` | `#a46800` / `#7e5000` | `#f2ad2e` / `#f6bf55` | Pronto, Revisar |
| `--prog` / `--prog-t` | `#0a6a9c` / `#085a85` | `#35b4e6` / `#6fcaef` | En curso |
| `--ok` / `--ok-t` | `#14793b` / `#0f6630` | `#3fcf7f` / `#62dc98` | Al día |
| `--nodata` / `--nodata-t` | `#66756d` / `#45544c` | `#83978d` / `#9db5a8` | Sin datos (y rayas de su barra) |

### Contraste WCAG 2.x (calculado con script)

Mínimos: texto ≥ 4,5:1; barras, rayas, franjas de estado, marcas, bordes de campo y foco ≥ 3:1. Todo el texto de la maqueta es «normal» salvo las cifras grandes, y a esas también se les exige 4,5:1.

| Par (primer plano / fondo) | Claro | Oscuro | Mínimo | Uso |
|---|---|---|---|---|
| `ink` / `bg` | #0c120f / #e3e9e6 → **15,39** | #e2ece6 / #0e1311 → **15,51** | 4,5 | Texto principal y cifras |
| `ink` / `panel` | #0c120f / #f8fbf9 → **18,18** | #e2ece6 / #151b18 → **14,46** | 4,5 | Texto principal y cifras |
| `ink` / `panel-2` | #0c120f / #eff3f1 → **16,92** | #e2ece6 / #1c2420 → **13,14** | 4,5 | Texto principal y cifras |
| `ink` / `field` | #0c120f / #ffffff → **18,94** | #e2ece6 / #111714 → **15,02** | 4,5 | Texto principal y cifras |
| `ink-2` / `bg` | #45544c / #e3e9e6 → **6,50** | #9db5a8 / #0e1311 → **8,58** | 4,5 | Texto secundario, cabeceras en versalitas, unidades |
| `ink-2` / `panel` | #45544c / #f8fbf9 → **7,68** | #9db5a8 / #151b18 → **7,99** | 4,5 | Texto secundario, cabeceras en versalitas, unidades |
| `ink-2` / `panel-2` | #45544c / #eff3f1 → **7,15** | #9db5a8 / #1c2420 → **7,27** | 4,5 | Texto secundario, cabeceras en versalitas, unidades |
| `due-t` / `bg` | #ab2018 / #e3e9e6 → **5,78** | #ff8a7e / #0e1311 → **8,20** | 4,5 | Texto, icono y borde del chip «Vencido» |
| `due-t` / `panel` | #ab2018 / #f8fbf9 → **6,83** | #ff8a7e / #151b18 → **7,65** | 4,5 | Texto, icono y borde del chip «Vencido» |
| `due-t` / `panel-2` | #ab2018 / #eff3f1 → **6,36** | #ff8a7e / #1c2420 → **6,95** | 4,5 | Texto, icono y borde del chip «Vencido» |
| `soon-t` / `bg` | #7e5000 / #e3e9e6 → **5,62** | #f6bf55 / #0e1311 → **11,16** | 4,5 | Texto, icono y borde del chip «Pronto / Revisar» |
| `soon-t` / `panel` | #7e5000 / #f8fbf9 → **6,64** | #f6bf55 / #151b18 → **10,40** | 4,5 | Texto, icono y borde del chip «Pronto / Revisar» |
| `soon-t` / `panel-2` | #7e5000 / #eff3f1 → **6,18** | #f6bf55 / #1c2420 → **9,45** | 4,5 | Texto, icono y borde del chip «Pronto / Revisar» |
| `prog-t` / `bg` | #085a85 / #e3e9e6 → **6,07** | #6fcaef / #0e1311 → **10,15** | 4,5 | Texto, icono y borde del chip «En curso» |
| `prog-t` / `panel` | #085a85 / #f8fbf9 → **7,17** | #6fcaef / #151b18 → **9,46** | 4,5 | Texto, icono y borde del chip «En curso» |
| `prog-t` / `panel-2` | #085a85 / #eff3f1 → **6,67** | #6fcaef / #1c2420 → **8,60** | 4,5 | Texto, icono y borde del chip «En curso» |
| `ok-t` / `bg` | #0f6630 / #e3e9e6 → **5,76** | #62dc98 / #0e1311 → **10,90** | 4,5 | Texto, icono y borde del chip «Al día» |
| `ok-t` / `panel` | #0f6630 / #f8fbf9 → **6,80** | #62dc98 / #151b18 → **10,16** | 4,5 | Texto, icono y borde del chip «Al día» |
| `ok-t` / `panel-2` | #0f6630 / #eff3f1 → **6,33** | #62dc98 / #1c2420 → **9,23** | 4,5 | Texto, icono y borde del chip «Al día» |
| `nodata-t` / `bg` | #45544c / #e3e9e6 → **6,50** | #9db5a8 / #0e1311 → **8,58** | 4,5 | Texto, icono y borde del chip «Sin datos» |
| `nodata-t` / `panel` | #45544c / #f8fbf9 → **7,68** | #9db5a8 / #151b18 → **7,99** | 4,5 | Texto, icono y borde del chip «Sin datos» |
| `nodata-t` / `panel-2` | #45544c / #eff3f1 → **7,15** | #9db5a8 / #1c2420 → **7,27** | 4,5 | Texto, icono y borde del chip «Sin datos» |
| `bg` / `ink` | #e3e9e6 / #0c120f → **15,39** | #0e1311 / #e2ece6 → **15,51** | 4,5 | Botón principal y filtro activo (invertidos) |
| `panel` / `ink` | #f8fbf9 / #0c120f → **18,18** | #151b18 / #e2ece6 → **14,46** | 4,5 | Texto invertido sobre ink en paneles (filtro activo) |
| `due` / `track` | #c9281e / #dbe3df → **4,22** | #ff6a5c / #27322d → **4,73** | 3,0 | Relleno de barra «Vencido» sobre la pista |
| `soon` / `track` | #a46800 / #dbe3df → **3,52** | #f2ad2e / #27322d → **6,83** | 3,0 | Relleno de barra «Pronto» sobre la pista |
| `prog` / `track` | #0a6a9c / #dbe3df → **4,52** | #35b4e6 / #27322d → **5,58** | 3,0 | Relleno de barra «En curso» sobre la pista |
| `ok` / `track` | #14793b / #dbe3df → **4,20** | #3fcf7f / #27322d → **6,61** | 3,0 | Relleno de barra «Al día» sobre la pista |
| `due` / `panel` | #c9281e / #f8fbf9 → **5,30** | #ff6a5c / #151b18 → **6,21** | 3,0 | Franja lateral de fila y marca de KPI «Vencido» |
| `due` / `panel-2` | #c9281e / #eff3f1 → **4,93** | #ff6a5c / #1c2420 → **5,65** | 3,0 | Franja lateral «Vencido» en fila con hover |
| `soon` / `panel` | #a46800 / #f8fbf9 → **4,42** | #f2ad2e / #151b18 → **8,98** | 3,0 | Franja lateral de fila y marca de KPI «Pronto» |
| `soon` / `panel-2` | #a46800 / #eff3f1 → **4,12** | #f2ad2e / #1c2420 → **8,16** | 3,0 | Franja lateral «Pronto» en fila con hover |
| `prog` / `panel` | #0a6a9c / #f8fbf9 → **5,67** | #35b4e6 / #151b18 → **7,34** | 3,0 | Franja lateral de fila y marca de KPI «En curso» |
| `prog` / `panel-2` | #0a6a9c / #eff3f1 → **5,28** | #35b4e6 / #1c2420 → **6,67** | 3,0 | Franja lateral «En curso» en fila con hover |
| `ok` / `panel` | #14793b / #f8fbf9 → **5,27** | #3fcf7f / #151b18 → **8,69** | 3,0 | Franja lateral de fila y marca de KPI «Al día» |
| `ok` / `panel-2` | #14793b / #eff3f1 → **4,90** | #3fcf7f / #1c2420 → **7,90** | 3,0 | Franja lateral «Al día» en fila con hover |
| `nodata` / `panel` | #66756d / #f8fbf9 → **4,66** | #83978d / #151b18 → **5,64** | 3,0 | Franja lateral de fila y marca de KPI «Sin datos» y rayas/marco de su barra |
| `nodata` / `panel-2` | #66756d / #eff3f1 → **4,33** | #83978d / #1c2420 → **5,12** | 3,0 | Franja lateral «Sin datos» y rayas/marco de su barra en fila con hover |
| `nodata` / `bg` | #66756d / #e3e9e6 → **3,94** | #83978d / #0e1311 → **6,05** | 3,0 | Marca «Sin datos» sobre el fondo (KPI en tira, móvil) |
| `ink-2` / `track` | #45544c / #dbe3df → **6,12** | #9db5a8 / #27322d → **6,08** | 3,0 | Barra neutra (salidas, material más usado) |
| `ink` / `track` | #0c120f / #dbe3df → **14,49** | #e2ece6 / #27322d → **10,99** | 3,0 | Barra de reparto por bici |
| `ink-2` / `panel` | #45544c / #f8fbf9 → **7,68** | #9db5a8 / #151b18 → **7,99** | 3,0 | Marca de aviso (90 %) fuera de la barra |
| `ink` / `panel` | #0c120f / #f8fbf9 → **18,18** | #e2ece6 / #151b18 → **14,46** | 3,0 | Marca de umbral (100 %) y anillo de foco |
| `ink` / `bg` | #0c120f / #e3e9e6 → **15,39** | #e2ece6 / #0e1311 → **15,51** | 3,0 | Anillo de foco sobre el fondo |
| `rule-strong` / `field` | #6b7a72 / #ffffff → **4,51** | #6d8077 / #111714 → **4,33** | 3,0 | Borde de campos (interior) |
| `rule-strong` / `panel` | #6b7a72 / #f8fbf9 → **4,33** | #6d8077 / #151b18 → **4,16** | 3,0 | Borde de campos, filtros y botón secundario |
| `rule-strong` / `panel-2` | #6b7a72 / #eff3f1 → **4,03** | #6d8077 / #1c2420 → **3,78** | 3,0 | Borde de etiquetas de ciclo de vida en hover |

**Cómo se verificó.** Los scripts están fuera del repositorio, en la carpeta temporal `/private/tmp/claude-501/design-work/option-3/`.

1. `contrast.py` lee los tokens de los bloques `tokens:oscuro` y `tokens:claro` del propio `index.html` y comprueba que el bloque `[data-tema="claro"]` repite exactamente los tokens claros. Después calcula los 47 pares × 2 modos de la tabla. Resultado: **94 comprobaciones, 0 por debajo del mínimo**. El margen más justo es el relleno ámbar sobre la pista en claro (3,52 frente a 3,0). El mismo script genera la tabla de `#sobre`.
2. `audit/audit.js` se ejecuta en Chrome headless sobre **las 13 pantallas, en claro y en oscuro, a 375, 390, 768 y 1280 px**. Recorre cada elemento visible con texto, compara su color calculado con el fondo efectivo (subiendo por los ancestros) y revisa también los rellenos de barra (frente a la pista y al panel), las marcas del 90 % y del 100 %, las franjas y marcas de estado (`box-shadow`), las rayas y el marco de «Sin datos», y los bordes de chips, campos, filtros y botón secundario. Resultado: **3.028 + 3.028 + 3.360 + 3.666 comprobaciones, 0 fallos**.

**Pares que fallaban y cómo se arreglaron**

- *Al elegir la paleta*: el ámbar saturado habitual, `#e09400`, da 2,50:1 sobre blanco y no vale ni como texto ni como barra. Se separó en dos tokens: relleno `#a46800` (3,52 sobre la pista y 4,42 sobre el panel) y texto `#7e5000` (6,64). Con el verde pasó lo mismo: `#1f9d55` daba 3,49:1 como texto, y quedó en `#14793b` para el relleno y `#0f6630` para el texto.
- *Barra «Sin datos»*: en la versión anterior, las rayas y el contorno usaban `--track`, que da 1,28:1 en claro y 1,32:1 en oscuro sobre el panel (1,15 y 1,22 en hover), y apenas se veían. Ahora usan `--nodata`: 4,66 y 5,64 sobre el panel, y 4,33 y 5,12 en hover. El par está en la tabla y en la auditoría.
- *Marca de aviso dentro de la barra*: `ink-2` sobre el relleno rojo no llega a 3:1. Las marcas sobresalen 4 px por arriba y por abajo (6 px en la barra grande), y lo que se lee es esa parte, que queda sobre el panel (7,68 en claro y 7,99 en oscuro).
- *Primera pasada de la auditoría*: dio entre 68 y 83 «fallos» por ancho, todos en oscuro y con colores del modo claro. Era un artefacto: el script leía los colores en mitad de la transición de 0,12 s. Con las transiciones desactivadas durante la auditoría, quedaron 0 fallos.

### Fuentes

| Rol | Familia | Pesos | Respaldo |
|---|---|---|---|
| Texto, etiquetas, tablas | **IBM Plex Sans Condensed** (Google Fonts, SIL OFL) | 400, 500, 600, 700 | Avenir Next Condensed (iOS, macOS), `sans-serif-condensed` (Android), Roboto Condensed, Arial Narrow, `system-ui` |
| Cifras, fechas, unidades | **JetBrains Mono** (Google Fonts, SIL OFL; variable) | 400–600 | `ui-monospace`, SF Mono, Roboto Mono, Menlo, Consolas |

La condensada deja sitio para más columnas a 375 px. La monoespaciada da cifras tabulares, así que las columnas de números se alinean solas; además tiene una x alta y un 0 que no se confunde con la O. Las etiquetas usan `font-variant-caps: all-small-caps`; Plex no trae versalitas reales y el navegador las sintetiza.

**Autoalojarlas es un requisito.** Una PWA sin red no llega a Google Fonts, y el respaldo real de iOS sin la condensada es SF Pro, que es bastante más ancha. Hay que servir los WOFF2 desde `static/`: el subconjunto latino ocupa **87 KB** (89.352 bytes, medido en Google Fonts: 4 archivos de Plex Sans Condensed de 14 KB cada uno y 1 archivo variable de JetBrains Mono de 31 KB). La app actual no carga fuentes. Los respaldos sólo evitan que la maqueta se rompa: con `system-ui` a 375 y 390 px no hay desbordes ni texto cortado (comprobado con un script), pero los nombres largos, como «Neumático Maxxis Assegai 29×2.5», ocupan dos líneas.

### Escala tipográfica (px)

| Token | Tamaño | Uso |
|---|---|---|
| `--t-xs` | 12 | Chips de estado (mayúsculas), leyendas, unidades pequeñas, uso/umbral en móvil |
| `--t-sm` | 13 | Línea secundaria de las filas, cifras de tabla, etiquetas de la tira de KPI en móvil |
| `--t-md` | 15 | Cuerpo, celdas, nombre de pieza, cabeceras de columna en versalitas |
| `--t-lg` | 18 | Título de panel en versalitas |
| `--t-xl` | 22 (móvil) · 28 (≥ 1280) | Título de pantalla |
| `--n-md` / `--n-lg` | 17 (tira móvil) · 24 · 28 | Cifras de KPI (crecen con el ancho) |
| `--n-xl` | 38 · 44 | Lectura principal de la ficha |

Los campos de formulario van a 16 px para que iOS no amplíe la página al enfocarlos.

### Radios

Un único radio: `--r0` = **0**. Paneles, tablas, barras, chips, etiquetas, campos, filtros y botones son rectángulos, como los pilotos de un panel. La única forma que no es rectangular son los anillos de foco del navegador.

### Espaciado

Base 4: `--s1` 2 · `--s2` 4 · `--s3` 8 · `--s4` 12 · `--s5` 16 · `--s6` 24 · `--s7` 32. Las filas de tabla llevan 8 px de relleno vertical desde 768 px y 7 px en móvil. Los márgenes laterales son de 12 px en móvil.

### Rejilla y puntos de corte

- **< 768 px** (móvil, 375–430): una columna, paneles de borde a borde separados por 8 px y barra de pestañas inferior fija (58 px más la zona segura).
  - **Fila de regla en dos líneas, 53 px**. Arriba, el nombre a la izquierda y, a la derecha, una barra de 64 px con el %. Abajo, el estado (icono y palabra en su color) · la regla · la bici, y a la derecha el uso sobre el umbral. La sub-línea se recorta con «…» si no cabe. El enlace ocupa todo el alto de la fila (≥ 44 px).
  - Los **KPI de cabecera** pasan a una tira de lectura: etiqueta y cifra en línea, en una o dos líneas. Los KPI de estado llevan una marca lateral de 3 px.
  - En Garaje, Taller y Salidas, el botón principal se pone a la derecha del título.
  - Medido a 375 × 844: la primera fila de reglas empieza en y = 305 en Taller (antes 408) y en y = 346 en la Rallon (antes 433). En la primera pantalla caben 7 reglas en Taller y 8 en la Rallon, frente a las 4 de antes. La Rallon mide 1.419 px de alto (antes 1.849).
- **≥ 768 px** (tableta): carril lateral de 88 px con icono y texto; rejilla de 12 columnas, con paneles de 6 o de 12. Aparecen las columnas «Estado» y «Uso / umbral», y la barra pasa debajo del nombre, a todo el ancho de la columna.
- **≥ 1280 px** (escritorio): barra lateral de 216 px con un resumen (Strava, salidas, reglas). Aparecen «Margen», «Cuenta desde», «Bici» y «Origen». Las tablas principales ocupan el ancho completo.
- **≥ 1680 px**: la tabla principal pasa a 8/12 y los paneles secundarios se colocan al lado.

## Componentes que definen la dirección

- **Barra de desgaste de 0 a 125 %**: el relleno usa el color del estado; la marca fina es el aviso (90 %) y la gruesa, el umbral (100 %). Lo que pasa del umbral se ve como relleno más allá de la marca gruesa (116 % de la Fox 38). «Sin datos» se dibuja sin relleno, con rayas y marco en `--nodata`.
- **Estado = palabra + piloto + color.** Los iconos son pilotos cuadrados de panel, todos con la misma silueta y lenguaje propio:
  - Vencido: encendido, un cuadrado relleno con «!» calado.
  - Pronto y Revisar: apagado, con «!».
  - En curso: un canal con su marca de umbral.
  - Al día: con visto.
  - Sin datos: discontinuo, con una raya (sin señal).

  Se distinguen sin color: lleno frente a vacío, y luego la marca interior. Cada fila con estado lleva además una franja lateral de 3 px.
- **Ciclo de vida monocromo**, para no competir con el mantenimiento: Montado (borde continuo), Disponible y Sin estrenar (discontinuo), En uso (punteado), Retirado (tachado).
- **KPI en rejilla de líneas finas** al principio de cada pantalla desde 768 px; en móvil, como tira de lectura.
- **Lectura grande** en la ficha: cifra, % y barra de 14 px con su escala.
- **Barra neutra** (gris, sin marcas) para lo que no es desgaste: km de cada salida respecto a la más larga, reparto por bici y material más usado. Siempre lleva leyenda.

## Accesibilidad

Verificado con scripts en Chrome headless (a 375, 390, 430, 768, 1280 y 1440 px):

- Contraste: ver arriba (0 fallos).
- Navegación: los 13 destinos internos existen y son pantallas, y cada hash muestra exactamente una. `aria-current="page"` está en la pestaña correcta, el foco pasa al `h1` de la pantalla nueva y ningún ancho tiene desbordamiento horizontal. Sin hash, se abre Garaje.
- Sin las fuentes web (sólo `system-ui`) a 375, 390, 430 y 768 px no hay tablas con scroll horizontal, elementos fuera de la pantalla ni etiquetas de filtro cortadas.
- Formularios: todos los campos tienen `label` y los ids son únicos.
- Filtro de Material: Montados 12, Disponibles 2, En uso 1, Retirados 1 y Todos 16, como se esperaba. En móvil se ve «Dispon.», y el nombre accesible sigue siendo «Disponibles».
- Objetivos táctiles ≥ 44 × 44 px en enlaces, botones, filtros, casillas, campos y el `summary` de «Todos los tokens de color» (antes medía 21 px). En las filas compactas de móvil, el enlace ocupa todo el alto de la fila.
- Foco visible: contorno de 2 px en `ink` con 2 px de separación (−4 px dentro de la barra de pestañas).
- Semántica: `nav`, `main`, un `h1` por pantalla, un `h2` por panel, y tablas con `caption` y `th scope`. En Taller hay **un `tbody` por grupo de estado**, cada uno con su fila `th scope="rowgroup"`. El filtro y «También en esta visita» usan `fieldset`/`legend`. Las barras son `aria-hidden`; el dato está en texto.
- `prefers-reduced-motion`: la animación de llenado de las barras y las transiciones sólo existen con `no-preference`.
- Tema: el botón dice el estado actual («Tema: Oscuro»), no el destino, y se puede volver a «Sistema».

**No verificado** (no se ha ejecutado):

- Lector de pantalla real (VoiceOver o TalkBack).
- Navegación con teclado físico.
- Safari y Firefox: `:has()` necesita Safari 15.4+ y Firefox 121+, y el truco de `max-width: 0` en celdas no se ha probado en ellos.
- Teléfonos reales.
- Las condensadas del sistema como respaldo (Avenir Next Condensed en iOS, `sans-serif-condensed` en Android).

## Trade-offs: qué sacrifica

- **Calidez y lectura rápida.** Pide leer tablas: quien sólo quiere saber «¿qué toca?» tiene más ruido que con una lista de tarjetas. Es la más fría de las direcciones posibles: sin color de marca ni fotos, parece más una herramienta de trabajo que «mi garaje».
- **Curva de aprendizaje.** La escala hasta 125 % y las dos marcas hay que explicarlas una vez (hay leyenda). Una barra «llena» no llega al borde.
- **Densidad en móvil, con recortes.** A 375 px las reglas caben en filas de 53 px, con 7 u 8 en la primera pantalla. A cambio:
  - La sub-línea (estado · regla · bici) se corta con «…»: en Taller, la bici suele quedar fuera.
  - La barra móvil es corta (64 px), y el aviso y el umbral quedan a 5 px uno del otro.
  - «Margen», «Cuenta desde» y «Origen» sólo se ven desde 1280 px.
  - Con la fuente del sistema, los nombres largos ocupan dos líneas.
- **Oscuro de referencia.** Al sol, el modo claro se lee mejor. Las líneas finas (`--rule`) casi desaparecen en pantallas con poco contraste; no llevan información, pero la rejilla pierde fuerza. El tinte verde de los neutros es sutil y, en pantallas mal calibradas, puede parecer un gris sucio.
- **Coste de implementar.** No es un cambio de tema:
  - Hay que pasar de filas a tablas en plantillas como `_wear_row.html` y añadir celdas por tamaño (`lt-md`, `md-up`, `lg-up`).
  - En móvil, el estado y la barra se repiten en otro sitio de la fila, en un segundo nodo oculto según el ancho.
  - Hay que montar un layout de barra lateral en `base.html`.
  - La maqueta pesa unos 159 KB por esa duplicación.
- **Dependencia de fuentes.** Hay que autoalojar 87 KB de WOFF2 para la PWA. Sin ellas, el carácter condensado se pierde.
- **Versalitas sintetizadas.** Son algo más finas que unas reales.
- **Daltonismo.** Rojo, ámbar y verde se confunden. Lo cubren la palabra, la forma del piloto y el orden por grupos, pero el «vistazo de color» no sirve para todos.

## Supuestos tomados (sin preguntar)

- **Datos**: los del encargo, idénticos en las tres opciones. Donde el encargo no daba cifras, las inventé de forma coherente y ficticia, con una regla: las salidas de una bici suman a **todas** sus piezas montadas, así que una pieza que cuenta desde antes nunca puede tener menos uso. Ritmo de la Rallon: 15,4 km/h (4.812 km en 312 h), unos 13 km al día en verano.
  - Rallon, fechas desde las que cuenta cada regla, de más antigua a más reciente: cadena y casete el 12/05/2026 (1.860 km, 121 h); Float X el 18/06/2026 (89 h ≈ 1.370 km, que es el 71 % de 125 h); pastillas Magura el 20/07/2026 (940 km); Fox 38 el 24/07/2026 (58 h ≈ 890 km); neumáticos y líquido el 24/08/2026 (480 km; 69 días hasta hoy, «vencido hace 9 días»). La bici y las piezas originales se montaron el 14/03/2024.
  - Grizl (desde el 15/01/2025): G-One desde el 15/01/2026 (1.480/3.500 km), cadena GRX desde el 01/08/2026 (420 km) y pastillas Shimano desde el 10/08/2026 (380/1.500 km).
  - Uso de la cadena: 1.860 km, 121 h, 78 salidas y ↑ 38.000 m. La elongación se midió el 14/08/2026, a 1.250 km.
  - Intervenciones e importes: horquilla 95,00 EUR el 25/05/2026 y otros 95,00 el 24/07/2026 (a 52 h de la anterior); amortiguador 140,00 EUR el 18/06/2026; sustitución de la cadena 54,90 EUR el 12/05/2026; medición de elongación el 14/08/2026. Total: 384,90 EUR. La más reciente sigue siendo el purgado de frenos del 03/10/2026.
  - Importación histórica: 346 salidas el 19/10/2026, más 4 de la sincronización diaria, que dan las 350.
  - Material sin montar: casco con 1.240 km en el perfil «Montaña» y pastillas usadas con 310 km (desmontadas el 20/07/2026).
- **Vocabulario**: «Pronto» (del encargo) en vez de «Próximo» (de la app). «Revisar» para la salida sin bici, como en la app.
- La salida **Rodillo Z2 sin bici** cuenta como «por revisar» en Garaje y en Salidas, como hace la app con cualquier salida sin bici. La cabecera de «Requiere atención» lo dice en palabras: «3 avisos · 1 por revisar».
- **«Estadísticas»** está en la barra de pestañas, así que hay una pantalla mínima: totales, reparto por bici y material más usado, todo derivado de los datos anteriores.
- **Fichas**: sólo existen la de la cadena GX Eagle (Pronto, con vida útil y comparación con la cadena anterior y la de repuesto) y la de la Fox 38 (Vencido). El resto de piezas aparece sin enlace. En «Más», Categorías, Perfiles, Exportar e Instalar se marcan «Fuera de esta maqueta» para no dejar enlaces rotos.
- **Material** cuelga de «Más», como en la app.
- **Registrar intervención** viene rellenado para la Fox 38, con el líquido tubeless marcado en «También en esta visita». «Guardar» lleva a Taller: la maqueta no guarda nada. En móvil, «Efecto al guardar» junta Antes → Después en una sola columna.
- **Tema**: el oscuro es el de referencia y el que se ve si el sistema no pide claro; si el sistema pide claro, se respeta. Hay tres estados (Sistema, Claro y Oscuro): los dos últimos se recuerdan y «Sistema» vuelve a seguir al sistema.
- La regla de los bujes la puse «cada 12 meses» para tener un caso «Sin datos» creíble: falta la fecha de referencia.
