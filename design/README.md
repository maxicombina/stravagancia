# Garage · tres direcciones visuales

Tres propuestas de aspecto para Garage, hechas el 1 de noviembre de 2026. Las tres usan el mismo garaje ficticio para que se puedan
comparar: una Orbea Rallon de enduro con 3 avisos y una Canyon Grizl de gravel al día. Ninguna toca la app: son maquetas HTML
autocontenidas. Este documento las compara y termina con una recomendación.

## Cómo abrirlas

Abre cada `index.html` en el navegador con doble clic, arrastrándolo a la ventana o con
`open design/option-1/index.html` (y luego `option-2` y `option-3`). Funcionan con `file://`, sin servidor.

| | Abrir | Documento |
|---|---|---|
| 1 · Anillos | [option-1/index.html](option-1/index.html) | [option-1/README.md](option-1/README.md) |
| 2 · Bitácora | [option-2/index.html](option-2/index.html) | [option-2/README.md](option-2/README.md) |
| 3 · Telemetría | [option-3/index.html](option-3/index.html) | [option-3/README.md](option-3/README.md) |

- **Pantallas.** En las tres hay Garaje, las dos bicis, Material, la ficha de una pieza, Taller, Registrar intervención, Salidas,
  Estadísticas, Más, Strava y «Sobre esta dirección». Esta última está dentro de Más y repite la intención, los tokens, los
  contrastes y los trade-offs. La opción 1 tiene tres fichas (horquilla, cadena y neumático), la 3 tiene dos (cadena y horquilla)
  y la 2 sólo la de la cadena. Las filas sin ficha no son enlaces.
- **Claro y oscuro.** Las tres siguen el modo del sistema (`prefers-color-scheme`) y tienen un conmutador visible que se recuerda
  en `localStorage`:
  - **1:** botón luna/sol arriba a la derecha. Además, en Más → Apariencia se elige Automático, Claro u Oscuro.
  - **2:** botón «Modo oscuro» arriba (se ve en negativo cuando está activo). Para volver al modo del sistema hay un botón en
    «Sobre esta dirección» → Supuestos.
  - **3:** botón de tema arriba con tres estados: Sistema, Claro y Oscuro. Elegir Sistema borra lo guardado.
  - En las tres, añadir `?tema=claro` o `?tema=oscuro` a la URL fuerza un tema sin guardarlo. Por ejemplo,
    `index.html?tema=oscuro#taller`.
- **Fuentes.** Las tres cargan dos familias de Google Fonts, así que la primera vez necesitan conexión. Sin red usan las fuentes
  del sistema y pierden parte del carácter.

## Las tres direcciones

### 1 · Anillos: [abrir](option-1/index.html)

> Una app móvil amable en la que cada pieza lleva su anillo de desgaste y el color del estado dice, de un vistazo, qué toca revisar
> o cambiar. Pensada para quien viene de ProBikeGarage o de las apps nativas de deporte y quiere ir de la bici a la pieza sin leer
> tablas.

Es la dirección **parecida a ProBikeGarage, sin copiarla**: toma la estructura bici → componentes, un anillo por pieza y el
triángulo de aviso. La paleta (violeta sobre papel cálido), las fuentes (Outfit y Figtree), los iconos y los textos son suyos.
También es **la más continuista**: su anillo de fila es el de la app actual (`garage.css`, «Instrumentos») con otra piel.

### 2 · Bitácora: [abrir](option-2/index.html)

> Garage como el cuaderno de un mecánico: cada bici y cada pieza tiene su página, con el desgaste anotado en cifras y el historial
> escrito como un diario. Para quien disfruta repasando el historial y las notas de cada pieza y quiere una herramienta sobria, que
> informe sin gritar.

Usa una serifa (Newsreader) para el texto y las cifras, y una máquina de escribir (Courier Prime) para fechas, etiquetas y sellos.
El estado se marca con un sello y una regla graduada fina, no con bloques de color. No hay tarjetas ni sombras. En escritorio
tiene un índice a la izquierda y notas al margen.

### 3 · Telemetría: [abrir](option-3/index.html)

> Telemetría trata el garaje como un banco de pruebas: todas las cifras a la vista, en una rejilla estricta, con barras alineadas
> que se comparan de un vistazo, como los canales de un registro de datos. Encaja con quien mantiene su bici con mentalidad de
> mecánico o de ingeniero, quiere todos los números a la vez y compara piezas como datos.

Usa una sans condensada (IBM Plex Sans Condensed), cifras en monoespaciada (JetBrains Mono) y radio 0 en todo. El desgaste es una
barra de 0 a 125 % con una marca al 90 % (Pronto) y otra al 100 % (Vencido). Los neutros son grafito con un tinte verde y no hay
color de marca: el color sólo indica estado. En escritorio usa barra lateral y una rejilla de 12 columnas.

## Comparación

Las cifras de contraste, densidad y peso de las fuentes están medidas (ver «Verificación»). Las valoraciones de legibilidad, coste y
envejecimiento son juicio mío y están razonadas debajo de la tabla.

| Criterio | 1 · Anillos | 2 · Bitácora | 3 · Telemetría |
|---|---|---|---|
| Personalidad | Amable, colorida, de app nativa | Artesanal, cálida, sobria | Técnica, fría, de instrumento |
| Fuentes | Outfit + Figtree (geométrica y humanista) | Newsreader + Courier Prime (serifa y máquina de escribir) | IBM Plex Sans Condensed + JetBrains Mono |
| Texto base / mínimo | 16 px / 12 px (etiqueta de pestaña) | 17 px / 13 px (etiquetas en Courier) | 15 px / 12 px (chips, uso en móvil) |
| Paleta | Violeta de marca y 5 colores de estado sobre papel cálido | Papel y tinta; lacre, ocre y verde sólo en sellos y marcas | Grafito con tinte verde, sin marca; rojo, ámbar, cian y verde |
| Medidor de desgaste | Anillo (el de la app actual) con el icono de la pieza dentro | Regla graduada fina | Barra de 0 a 125 % con marcas al 90 y al 100 % |
| Radios | 10 a 28 px y píldoras | 0, 2 y 4 px | 0 en todo |
| Uso del espacio | Tarjetas con aire. Escritorio: barra lateral y dos columnas | Columna de lectura y tablas. Escritorio: índice y notas al margen | Tablas a todo el ancho. Escritorio: barra lateral y 12 columnas |
| **Densidad en móvil** (Bici Rallon a 390 × 844 px) | **Baja.** Ninguna pieza sin desplazar (la ilustración ocupa la primera pantalla); 119 px por pieza; pantalla de 2.650 px | **Baja.** 1 pieza sin desplazar; 140 px por pieza; 2.640 px | **Alta.** 8 piezas sin desplazar; 53 px por pieza; 1.419 px |
| **Legibilidad** | Alta para saber qué toca: color, icono y frase («8 h de más»). Las cifras quedan en segundo plano (14 px) | Alta para leer historial y notas. Baja para escanear: hay que leer el sello, y las etiquetas en Courier de 13 px cuestan más | Alta para comparar cifras (alineadas, tabulares). Media para leer: condensada a 15 px, sublíneas de 12–13 px cortadas con «…» en móvil |
| **Accesibilidad: contraste** (AA, script sobre los tokens del HTML) | 28 pares × 2 temas, 0 fallos. Mínimos: texto 5,79:1; no texto 3,53:1 | 14 pares × 2 temas, 0 fallos. Mínimos: texto 5,39:1; no texto 3,34:1 | 47 pares × 2 temas, 0 fallos. Mínimos: texto 5,62:1; no texto 3,52:1 |
| **Accesibilidad: contraste en la página renderizada** (mi auditoría: todas las pantallas a 390, 768 y 1280 px, en claro y en oscuro) | 6.188 textos, 0 por debajo de AA | 6.144 textos, 0 por debajo de AA | 7.996 textos, 0 por debajo de AA |
| Accesibilidad: lo demás | Estado con icono y palabra. Rojo, ámbar y verde no se distinguen con daltonismo (lo cubre la palabra) | La que menos depende del color: palabra, forma del borde del sello y marca al margen | Estado con piloto cuadrado, palabra y franja. Mismo problema de rojo, ámbar y verde |
| **Fuentes externas** | Sí: 51 KiB (woff2, subconjunto latino) | Sí: **295 KiB** | Sí: 87 KiB |
| **Coste de implementar en esta app** | **Bajo-medio** | **Medio-alto** | **Alto** |
| **Cómo envejece** | Regular: sigue la moda de las apps de 2020–2026 | La que peor: lo editorial y la máquina de escribir se fechan rápido | La que mejor: estética de herramienta, sin adornos |
| Distancia del estilo actual «Instrumentos» | Poca: mismo anillo, chips e iconos de estado con otra piel | Mucha | Media-alta: mantiene las cifras en monoespaciada; cambia el medidor, la maquetación y la paleta |
| Parecido a ProBikeGarage | Buscado: la idea, no la piel | Ninguno | Ninguno |

### Legibilidad y accesibilidad

- **Contraste.** Las tres cumplen AA en claro y en oscuro: el texto llega a 4,5:1 y los bordes, iconos, barras, anillos y el foco
  llegan a 3:1. Ninguna anda justa en el texto: el par más bajo de las tres está entre 5,39 y 5,79:1. Donde más cerca quedan del
  mínimo es en lo que no es texto: el borde de los campos en la 1 (3,53), las reglas y bordes en la 2 (3,34) y el relleno ámbar
  sobre la pista en la 3 (3,52). La 1 y la 3 documentan que tuvieron que oscurecer el ámbar de «Pronto» en claro para llegar a
  3:1; el ámbar vivo de siempre no pasa sobre blanco.
- **De un vistazo.** La 1 es la más inmediata: el anillo y el chip de color se ven antes de leer. La 3 ordena los avisos por grupos
  de estado y los marca con franja y piloto, así que se lee rápido una vez aprendida la escala. La 2 obliga a leer, y lo hace a
  propósito.
- **Lo que nadie ha probado.** Ninguna se ha probado con lectores de pantalla reales (VoiceOver, TalkBack), ni en Safari, Firefox o
  un teléfono real. Las tres comprobaciones automáticas se hicieron en Chrome de escritorio sin interfaz.

### Coste de implementar en esta app

Hoy Garage son plantillas Django, `garage/static/garage/garage.css` (371 líneas), `garage.js` (194 líneas) y una PWA cuyo service
worker (`garage/templates/garage/sw.js`) guarda en caché sólo lo estático **del mismo origen**. Hay costes que comparten las tres:

- **Autoalojar las fuentes.** El service worker ignora otros orígenes, así que con Google Fonts la PWA sin red nunca tendría las
  fuentes, y Google recibiría la IP de quien abre la app. Habría que copiar los woff2 a `static/` y añadirlos a la lista de
  archivos que se guardan al instalar. Hoy la app no carga ninguna fuente.
- **Conmutador de tema.** Hoy la app sólo sigue al sistema. `garage.js` ya tiene un ayudante de `localStorage`, pero hacen falta el
  atributo en `<html>`, una segunda copia de los tokens oscuros y la `theme-color` de `shell.html`.
- **iOS y Android.** `garage.css` distingue ahora iOS de Android (`data-os`). Las tres maquetas lo ignoran, así que hay que decidir
  si se mantiene.
- **Vocabulario.** Las maquetas dicen «Pronto», como pedía el encargo; la app dice «Próximo».
- **Matices del dominio.** No todas las maquetas dibujan «≥» (histórico incompleto), «estimado» ni «Pospuesto», y la app los
  necesita en cualquier dirección.

Lo propio de cada una:

- **1 · Anillos: bajo-medio.**
  - `_ring.html` se queda. Cambia el porcentaje por el icono de la pieza, y para eso valen los iconos de categoría que ya existen
    (garage-041).
  - `garage.css` cambia sobre todo en fuentes, colores, tarjetas, barra de pestañas flotante y barra lateral de escritorio (nueva en
    `base.html`).
  - La cabecera de la bici, con su ilustración grande, habría que compactarla; si no, la ficha de una bici real se hace muy larga.
- **2 · Bitácora: medio-alto.**
  - El CSS se reescribe casi entero y `_ring.html` pasa a ser una regla graduada.
  - Taller, Salidas, Estadísticas, los montajes de la ficha y las bicis de Strava pasan de listas `<ul class="rows">` a `<table>`.
  - El Taller se reagrupa en cinco estados, cuando hoy son tres grupos.
  - Hay que montar el índice lateral y las notas al margen.
  - Son 295 KiB de fuentes que la PWA tendría que guardar al instalarse: 3,4 veces la 3 y 5,8 veces la 1.
- **3 · Telemetría: alto.**
  - `_ring.html` pasa a ser la barra de 0 a 125 %. Ya existe una base: `WearMetric.bar_width` en `garage/presentation.py` dibuja una
    barra en la ficha, pero corta en el 100 % y no tiene marcas.
  - `_wear_row.html` y las filas de Bici y Taller pasan a tablas con celdas que aparecen según el ancho. En móvil, el estado y la
    barra se repiten en otro nodo; por esa duplicación la maqueta pesa 159 KB.
  - Hay que montar el layout de barra lateral y rejilla en `base.html` y las tiras de KPI en cada pantalla.
  - Es la que más plantillas toca. Necesita sus pilotos de estado cuadrados, pero no ilustraciones.

### Cómo envejece cada una

- **1:** tarjetas redondeadas, sombras suaves y barra flotante son el lenguaje de las apps de estos años. Envejece con la
  plataforma: cuando iOS o Android cambien de piel, se verá de la generación anterior. El color abundante cansa antes.
- **2:** lo editorial y de papel, y sobre todo la máquina de escribir, es una moda reconocible. Su estructura (tablas, filetes,
  buena tipografía) aguanta mejor que su voz.
- **3:** radio 0, rejilla y cifras alineadas es la estética de las herramientas de medida, que cambia poco. Su riesgo es el
  contrario: parecer fría desde el primer día, no pasarse de moda.

## ¿Son distintas de verdad?

Sí en los cinco ejes del encargo. No comparten ninguna familia tipográfica. La paleta va de violeta con cinco colores, a papel y
tinta casi sin color, a grafito sin marca. La densidad en móvil va de ninguna a 8 piezas en la primera pantalla. El espacio se
organiza en tarjetas, en una columna de lectura o en una rejilla de tablas. Y la personalidad es amable, artesanal o técnica.
Aun así, hay tres parecidos que conviene saber:

- **La 2 y la 3 son la pareja más cercana en estructura.** Las dos cambian el anillo por un medidor horizontal con marcas, ponen el
  estado en una etiqueta con borde y letras mayúsculas, ordenan en tablas por grupos y usan un índice lateral en escritorio.
  Difieren en todo lo demás: serifa y máquina de escribir frente a condensada y monoespaciada; papel cálido casi sin color frente a
  grafito con rellenos de estado saturados; texto con aire frente a filas de 53 px. Hasta la revisión compartían también la
  monoespaciada (IBM Plex Mono); ya no. Elegir entre ellas es elegir tono y densidad, no medidor.
- **La 1 se parece a la app actual más que a las otras dos.** Es lo pedido («similar a ProBikeGarage»), y ProBikeGarage y el estilo
  actual comparten la idea del anillo. Si se busca un cambio de verdad, la 1 lo es en la piel, no en los componentes.
- **El fondo de página en claro es casi igual en las tres**: un blanco roto con una diferencia de color entre 4 y 6 (ΔE76). Es lo
  esperable en un fondo accesible. La diferencia de paleta está en el acento y en cuánto color se usa, no en el fondo.

## Trade-offs (resumen; el detalle está en cada README)

- **1 · Anillos** sacrifica densidad (en la ficha de una bici real hay que desplazarse mucho), precisión a primera vista (el número
  exacto queda en 14 px) e identidad propia (se parece a ProBikeGarage y a la app actual). El color cansa, y «En curso» comparte
  violeta con la marca, así que se lee como «normal». El anillo se llena al 100 % y no puede mostrar cuánto se ha pasado una pieza:
  la horquilla al 116 % se ve igual que al 100 % y el exceso sólo está en el texto.
- **2 · Bitácora** sacrifica la lectura de un vistazo y la densidad en móvil. Las etiquetas en Courier se leen peor. Tiene el mayor
  peso de fuentes, no tiene aspecto nativo e iguala iOS y Android. Sus reglas comunican menos que un anillo cuando una pieza tiene
  varias reglas.
- **3 · Telemetría** sacrifica calidez y tiene curva de aprendizaje: hay que explicar una vez la escala de 125 % y sus dos marcas.
  En móvil recorta con «…» (en Taller la bici suele quedar fuera) y sólo muestra «Margen», «Cuenta desde» y «Origen» desde 1280 px.
  El rojo, ámbar y verde no sirven con daltonismo sin la palabra. Las versalitas son sintetizadas y es la más cara de llevar a la
  app.

## Recomendación

**Recomiendo la 3, «Telemetría», como dirección**, llevada a la app por fases y con algunas cosas de las otras dos. Por qué:

1. **Es la que mejor dibuja el dominio.** Garage compara uso con umbrales: Pronto al 90 %, Vencido al 100 % y lo que se pasa de ahí.
   La barra de 0 a 125 % con sus dos marcas lo muestra tal cual, incluida la horquilla al 116 %. El anillo de la 1 (y el de la app
   actual, porque `ring()` nunca pasa de una vuelta) se queda lleno al 100 % y deja el exceso en el texto.
2. **Tiene densidad donde hace falta.** En la pantalla de la bici, a 390 px, se ven 8 piezas sin desplazar; en la 1 ninguna y en la
   2 una. Con las 9 piezas del ejemplo es incómodo; con las 20 o 30 de una bici real decide si la pantalla sirve.
3. **Es la que mejor envejece, y es una evolución, no una piel nueva.** Mantiene lo que ya define a «Instrumentos» (las cifras en
   monoespaciada) y cambia lo que limita: el medidor, la maquetación y la paleta.
4. **Cumple AA en todo**, con la tabla de pares más amplia (94 comprobaciones), y sus fuentes pesan lo razonable para una PWA
   (87 KiB).

Lo que cuesta, dicho claro: es la más cara de implementar y la más fría, y quien la use por primera vez tiene que aprender la escala.
Para repartir el coste, la llevaría en tres fases:

1. Tokens, radio 0, fuentes autoalojadas y barra de 0 a 125 % en lugar del anillo, extendiendo `WearMetric.bar_width` con el tope
   en 1,25 y las marcas.
2. Filas de dos líneas en Bici y Taller, y tira de KPI arriba.
3. Escritorio: barra lateral y columnas extra.

Es una estimación; no lo he probado en la app.

**De la 1 tomaría:**

- El icono de categoría en cada fila. La app ya tiene 42 categorías con icono, y ayuda a escanear a quien no lee tablas.
- La frase humana del estado en el resumen del Garaje («faltan 140 km», «8 h de más»). La app ya calcula esas cifras
  (`big` y `big_caption` en `presentation.py`).
- El tono más amable para el primer bloque, «Requiere atención».

**De la 2 tomaría:**

- El historial de cada pieza como diario fechado, con sus notas.
- El orden del Taller del dominio (Vencido, Sin datos, Pronto, En curso, Al día), que es el de `docs/garage-domain.md`. La 1 y la 3
  ponen «Sin datos» al final.

**Cuándo elegir otra:**

- **La 1**, si lo que pesa es el coste y que quien venga de ProBikeGarage se oriente sin esfuerzo. Es la más barata y la más amable,
  pero es el anillo actual con otra piel, y su densidad en la ficha de la bici habría que arreglarla igual.
- **La 2 no la elegiría para la app.** Es la de más identidad y la más bonita como pieza de diseño, pero la más débil para la tarea
  principal («¿qué toca?»). También tiene las fuentes más pesadas para una PWA sin red y es la que peor envejece. Quedó peor para
  este uso, aunque su diario merece la pena.

## Supuestos tomados sin preguntar

- Comparo las tres tal como quedaron tras la revisión y las correcciones del 1 de noviembre de 2026. No he editado ningún
  `index.html`.
- «Hoy» en las maquetas es el domingo 1 de noviembre de 2026.
- El garaje del encargo es idéntico en las tres. Las cifras secundarias que cada opción inventó (fecha de la importación del
  histórico de Strava, km por mes, importes, fechas de intervenciones anteriores) **no coinciden entre opciones** y no deben
  compararse: cada una sólo cuadra consigo misma. Todo es ficticio; no hay datos personales.
- «Parecida a ProBikeGarage» es la opción 1: toma la idea (bici → componentes, anillo por pieza, triángulo de aviso), no su
  paleta, sus fuentes, sus iconos ni sus textos.
- La densidad la medí en el mismo teléfono simulado (390 × 844 px, claro, con las fuentes de Google cargadas). Cuento las piezas
  visibles sin desplazar y la distancia entre una pieza y la siguiente. La altura de cada pantalla es sólo orientativa, porque cada
  opción añade contenido secundario distinto.
- El coste de implementar es cualitativo, comparado con el código actual (`garage.css`, `garage.js`, plantillas y `sw.js`). No lo
  he estimado en horas ni he hecho ningún prototipo dentro de la app.
- En la app, las fuentes irían autoalojadas en `static/` (el service worker sólo guarda lo del mismo origen). Los pesos son los del
  subconjunto latino de Google Fonts, descargados el 1 de noviembre de 2026; en español no hace falta el latino extendido.
- Doy por bueno añadir un conmutador de tema que se recuerde. Hoy la app sólo sigue al sistema.
- «Pronto» en lugar de «Próximo» es una decisión de vocabulario aparte, no de dirección visual.
- Para recomendar, pesé más: móvil primero, bicis con muchas piezas, uso personal y de unos amigos, PWA sin red y mantenimiento por
  una persona con ayuda de IA. Por eso valoré la densidad, el encaje con el dominio, el envejecimiento y el peso de las fuentes por
  encima de la calidez y del coste inicial.
- Las valoraciones de legibilidad y de envejecimiento son juicio, no medida. Las cifras de contraste, densidad y peso sí están
  medidas.

## Verificación

Hecha el 1 de noviembre de 2026, con los scripts fuera del repositorio, en `/private/tmp/claude-501/design-work/readme/`, y Chrome
sin interfaz con un perfil temporal propio:

- **Contraste de los tokens.** Ejecuté los scripts de contraste de cada opción sobre copias de los `index.html`, porque el de la
  opción 2 reescribe la página. Resultados: opción 1, 28 pares y 56 comprobaciones, 0 fallos; opción 2, 14 pares obligatorios × 2
  temas, 0 fallos, con los dos bloques oscuros idénticos; opción 3, 47 pares y 94 comprobaciones, 0 fallos. Los hashes de los tres
  `index.html` no cambiaron.
- **Contraste renderizado** (`inpage.js` y `run.mjs`). Recorrí las 14, 12 y 13 pantallas de cada opción a 390, 768 y 1280 px, en
  claro y en oscuro, y comparé cada texto visible con su fondo efectivo. Resultado: 6.188, 6.144 y 7.996 textos, **0 por debajo de
  AA**. En la opción 2 hay 110–122 textos sobre la línea de margen, que es un degradado decorativo de 1 px; los medí contra el
  color de fondo y también pasan. Esta auditoría sólo mide texto. Lo que no es texto (anillos, barras, bordes) lo midieron las
  auditorías de cada opción y su revisión.
- **Desbordamiento.** Ninguna pantalla tiene desbordamiento horizontal en ningún ancho, y todas las pantallas enlazadas se muestran.
- **Enlaces e ids.** No hay enlaces internos rotos (52, 42 y 36), ni ids duplicados, ni restos de «lorem».
- **Tema.** Las tres siguen al sistema en claro y en oscuro, y el conmutador es visible en las tres.
- **Fuentes.** Las fuentes de las tres se cargan desde Google Fonts. Los woff2 del subconjunto latino son 2, 4 y 5 archivos y
  pesan 52.412, 301.688 y 89.352 bytes.
- **Medidor y orden del Taller.** Comprobado en el HTML: el anillo de la horquilla de la opción 1 es una vuelta completa al 116 %, y
  los grupos del Taller de la 1 y de la 3 terminan en «Sin datos».
- **Densidad.** Medida a 390 × 844 y confirmada mirando las capturas.
- **Capturas.** A 390 y 1280 px, en claro y en oscuro, de Garaje, Bici, Material, ficha, Taller, Salidas, Registrar y Strava, en
  `shots/`, con hojas de comparación (`sheet-*.png`).
- **No verificado:** teléfonos reales, Safari, Firefox, lectores de pantalla, navegadores sin `:has()` y el aspecto con las
  fuentes del sistema en un iPhone o un Android reales.
