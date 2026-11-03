# Opción 1 · «Anillos»

**Dirección cercana a ProBikeGarage, sin copiarla, y continuista con el estilo actual de Garage.** Abre `index.html` en el
navegador (funciona con `file://`, sin servidor). La pantalla «Sobre esta dirección» (Más → Boceto, o la píldora «Boceto» del Garaje)
repite dentro del propio boceto la intención, los tokens, los contrastes y los trade-offs de este documento.

## Intención

Una app móvil amable en la que cada pieza lleva su anillo de desgaste y el color del estado dice, de un vistazo, qué toca revisar o cambiar.
Pensada para quien viene de ProBikeGarage o de las apps nativas de deporte y quiere ir de la bici a la pieza sin leer tablas.

De ProBikeGarage toma **la idea**, no la piel: la estructura bici → componentes, un anillo por pieza que se llena con el uso y un
triángulo de aviso en la bici. La paleta (violeta y papel cálido), las fuentes, los iconos (dibujos SVG propios), las formas y los
textos son de esta propuesta.

**Es la opción continuista.** El componente central, el anillo de fila (52 px, `viewBox` 56, trazo 6, extremo redondeado, pista
punteada `3 5` para «Sin datos»), es el de `garage.css` (líneas 107-111); también los chips con icono pequeño y palabra, los iconos de
cada estado (octógono, triángulo, indicador, marca y pregunta, como en `garage/presentation.py`), la fila de 64 px con hueco de 12, la
barra superior fija y las 5 pestañas abajo. Cambian la piel (Outfit y Figtree, el violeta, tarjetas con aire y sombra), el icono de la
pieza dentro del anillo en lugar del porcentaje, la barra de pestañas flotante y la barra lateral en escritorio. Si se quiere más
distancia sin perder la idea de ProBikeGarage, lo siguiente a cambiar sería la forma del medidor (anillo segmentado o barras «queda X de
Y»), no sólo su color.

## Qué hay en el boceto

Pantallas navegables (cada una es una sección con `id`; los enlaces usan `:target`):

| Pantalla | Ancla | Desde |
|---|---|---|
| Garaje (inicio: Requiere atención, bicis, última salida, material sin montar) | `#garaje` | pestaña Garaje |
| Bici: Orbea Rallon (piezas por zona, anidadas, anillos) | `#bici-rallon` | Garaje |
| Bici: Canyon Grizl | `#bici-grizl` | Garaje |
| Material (filtros Todos · Montados · Disponibles · En uso · Retirados, sin JS) | `#material` | Garaje, Más |
| Ficha: Horquilla Fox 38 Factory (regla vencida, vida útil sin definir, montajes, historial) | `#pieza-fox38` | Garaje, Rallon, Taller |
| Ficha: Cadena SRAM GX Eagle (vida útil «Pronto», recambio sin estrenar) | `#pieza-cadena` | Garaje, Rallon, Taller |
| Ficha: Neumático Maxxis Assegai (líquido tubeless dentro, vencido) | `#pieza-assegai` | Garaje, Rallon, Taller |
| Taller (Vencido, Pronto, En curso, Al día, Sin datos, últimas intervenciones) | `#taller` | pestaña Taller |
| Registrar intervención (formulario con «También en esta visita») | `#registrar` | Taller, bici, fichas |
| Salidas (km, tiempo, desnivel, bici, origen Strava) | `#salidas` | pestaña Salidas |
| Estadísticas (12 meses, km por mes, reparto por bici, gasto) | `#estadisticas` | pestaña Estadísticas |
| Más | `#mas` | pestaña Más |
| Strava (estado, Sincronizar ahora, Importar histórico, bicis vinculadas) | `#strava` | Más, Salidas |
| Sobre esta dirección (intención, estados, tokens, contrastes, trade-offs, supuestos) | `#sobre` | Más, píldora «Boceto» del Garaje |

- **Modo claro/oscuro:** sigue `prefers-color-scheme` y además hay un conmutador (botón luna/sol arriba a la derecha de cada pantalla,
  con nombre fijo «Modo oscuro» y `aria-pressed`, y «Apariencia» en Más: Automático · Claro · Oscuro). La elección **se recuerda** en
  `localStorage` (`garage-opcion1-tema`). `?tema=claro` o `?tema=oscuro` en la URL lo fuerza sin guardarlo (útil para comparar) y se
  mantiene al enviar los formularios del boceto.
- **Responsive:** móvil primero (375–430 px) con barra de pestañas flotante; tableta (640–999 px) con tarjetas en dos columnas y
  cabecera de bici horizontal; escritorio (≥ 1000 px) con barra lateral, columna fija de la bici y contenido a dos columnas.
- **JavaScript mínimo** (unas 20 líneas): el conmutador de tema, marcar la pestaña activa (`aria-current`) y el título de la página, y
  que «Guardar intervención» o «Sincronizar ahora» vayan a su pantalla sin recargar. Sin JS la navegación sigue funcionando con
  `:target`, la pestaña activa se resalta por CSS (`:has`) y los formularios hacen un GET normal.

## Tokens

### Paleta

| Token | Uso | Claro | Oscuro |
|---|---|---|---|
| `--bg` | fondo de pantalla (papel cálido) | `#F5F3EF` | `#131118` |
| `--surface` | tarjetas, barra de pestañas | `#FFFFFF` | `#1D1A23` |
| `--surface-2` | teselas de icono, cifras, chips neutros, carril del selector | `#EFEBE4` | `#29252F` |
| `--line` | separadores (decorativos) | `#E4DFD7` | `#2F2B37` |
| `--ink` | texto principal | `#1C1A21` | `#F3F1F6` |
| `--ink-2` | texto secundario, iconos neutros, pestañas inactivas | `#5D5866` | `#B3ADBD` |
| `--field` | borde de campos de formulario | `#8C8694` | `#7F7889` |
| `--primary` | marca, enlaces, botón principal, «En curso», pestaña activa, segmento elegido | `#5536C8` | `#B6A2FF` |
| `--on-primary` | texto e iconos sobre `--primary` | `#FFFFFF` | `#1B1035` |
| `--primary-soft` | ilustración, píldora «Boceto», chip «Sin estrenar» y «En curso» | `#ECE6FD` | `#2D2550` |
| `--focus` | anillo de foco (3 px) | `#C2410C` | `#FF9A5C` |
| `--due` / `--due-soft` | Vencido: anillo e icono / fondo del chip y pista | `#D2312F` / `#FCE4E2` | `#FF7B72` / `#3D1F22` |
| `--soon` / `--soon-soft` | Pronto y Revisar: anillo e icono / fondo del chip y pista | `#B86200` / `#FFEFD2` | `#F2B13B` / `#3A2B12` |
| `--ok` / `--ok-soft` | Al día: anillo e icono / fondo del chip y pista | `#1E8449` / `#DDF3E5` | `#4FCB83` / `#15301F` |
| `--nodata` / `--nodata-soft` | Sin datos y Pospuesto: anillo e icono / fondo del chip y pista | `#7A7482` / `#EEEBF0` | `#A29CAB` / `#2A2730` |

Reglas: el color de estado **nunca va solo** (cada chip lleva icono y palabra; el anillo tiene sus cifras en el texto de la fila) y
**el texto nunca usa el color del estado**, siempre `--ink` o `--ink-2`. «Revisar» (lupa) y «Pospuesto» (reloj), que existen en la
app pero no en el garaje de ejemplo, reutilizan los colores de Pronto y de Sin datos con su propio icono, así que la paleta no crece.
Los estados del ciclo de vida (Montado, Disponible, Sin estrenar, En uso, Retirado) van en chips neutros con icono propio, para no
confundirlos con los de mantenimiento. La pestaña activa y el segmento elegido en «Apariencia» se marcan con `--primary` relleno
(7,64:1 en claro y 7,84:1 en oscuro contra la barra), no con un tinte suave; la etiqueta activa pasa además a peso 700 y a `--ink`.

### Contraste WCAG 2.x (calculado por script)

Calculado con la fórmula de luminancia relativa de WCAG. La misma lista de pares genera esta tabla y la de «Sobre esta dirección»;
`contrast.py` **lee los tokens del CSS del propio `index.html`** y los pares de la tabla de la página, recalcula cada cifra y comprueba
que coincide con la que muestra la página (y que el oscuro de `prefers-color-scheme` y el del conmutador son idénticos). Texto normal
≥ 4,5:1; bordes, iconos, anillos y la marca de lo elegido ≥ 3:1. Cada par aparece una vez; si también se usa como borde o icono, manda
el mínimo de texto. Resultado: **28 pares, 56 comprobaciones (claro y oscuro), 0 fallos**.

| Par (primer plano sobre fondo) | Uso | Mínimo | Claro | Oscuro |
|---|---|---|---|---|
| `ink` sobre `bg` | texto de pantalla y títulos | 4,5:1 | #1C1A21 / #F5F3EF → 15,54 | #F3F1F6 / #131118 → 16,70 |
| `ink` sobre `surface` | texto en tarjetas y barra de pestañas; etiqueta de la pestaña activa | 4,5:1 | #1C1A21 / #FFFFFF → 17,23 | #F3F1F6 / #1D1A23 → 15,29 |
| `ink` sobre `surface-2` | cifras, chips neutros, casillas, segmentos no elegidos | 4,5:1 | #1C1A21 / #EFEBE4 → 14,50 | #F3F1F6 / #29252F → 13,37 |
| `ink` sobre `primary-soft` | chip «Sin estrenar», «En curso» y muestras | 4,5:1 | #1C1A21 / #ECE6FD → 14,19 | #F3F1F6 / #2D2550 → 12,55 |
| `ink` sobre `due-soft` | chip y aviso Vencido | 4,5:1 | #1C1A21 / #FCE4E2 → 14,22 | #F3F1F6 / #3D1F22 → 13,21 |
| `ink` sobre `soon-soft` | chips Pronto y Revisar | 4,5:1 | #1C1A21 / #FFEFD2 → 15,20 | #F3F1F6 / #3A2B12 → 12,20 |
| `ink` sobre `ok-soft` | chip y aviso Al día | 4,5:1 | #1C1A21 / #DDF3E5 → 14,79 | #F3F1F6 / #15301F → 12,70 |
| `ink` sobre `nodata-soft` | chips Sin datos y Pospuesto | 4,5:1 | #1C1A21 / #EEEBF0 → 14,58 | #F3F1F6 / #2A2730 → 13,08 |
| `ink-2` sobre `bg` | antetítulos y entradillas | 4,5:1 | #5D5866 / #F5F3EF → 6,21 | #B3ADBD / #131118 → 8,59 |
| `ink-2` sobre `surface` | texto secundario, pestañas inactivas, chevrones | 4,5:1 | #5D5866 / #FFFFFF → 6,88 | #B3ADBD / #1D1A23 → 7,87 |
| `ink-2` sobre `surface-2` | etiquetas de cifras, fecha de salida, iconos de chips neutros | 4,5:1 | #5D5866 / #EFEBE4 → 5,79 | #B3ADBD / #29252F → 6,88 |
| `primary` sobre `bg` | enlace «atrás» | 4,5:1 | #5536C8 / #F5F3EF → 6,90 | #B6A2FF / #131118 → 8,56 |
| `primary` sobre `surface` | enlaces; arco y barras «En curso»; pastilla de la pestaña activa | 4,5:1 | #5536C8 / #FFFFFF → 7,64 | #B6A2FF / #1D1A23 → 7,84 |
| `primary` sobre `primary-soft` | píldora «Boceto»; arco «En curso» sobre su pista | 4,5:1 | #5536C8 / #ECE6FD → 6,30 | #B6A2FF / #2D2550 → 6,43 |
| `on-primary` sobre `primary` | botón principal, filtro elegido, icono de la pestaña activa, segmento elegido | 4,5:1 | #FFFFFF / #5536C8 → 7,64 | #1B1035 / #B6A2FF → 8,19 |
| `primary` sobre `surface-2` | segmento elegido sobre su carril; barra de reparto sobre su pista | 3,0:1 | #5536C8 / #EFEBE4 → 6,43 | #B6A2FF / #29252F → 6,86 |
| `due` sobre `surface` | arco e icono Vencido sobre la tarjeta | 3,0:1 | #D2312F / #FFFFFF → 4,98 | #FF7B72 / #1D1A23 → 6,80 |
| `due` sobre `due-soft` | arco Vencido sobre su pista; icono del chip | 3,0:1 | #D2312F / #FCE4E2 → 4,11 | #FF7B72 / #3D1F22 → 5,88 |
| `soon` sobre `surface` | arco e icono Pronto / Revisar sobre la tarjeta | 3,0:1 | #B86200 / #FFFFFF → 4,39 | #F2B13B / #1D1A23 → 9,09 |
| `soon` sobre `soon-soft` | arco Pronto sobre su pista; icono del chip | 3,0:1 | #B86200 / #FFEFD2 → 3,87 | #F2B13B / #3A2B12 → 7,25 |
| `ok` sobre `surface` | arco e icono Al día sobre la tarjeta | 3,0:1 | #1E8449 / #FFFFFF → 4,72 | #4FCB83 / #1D1A23 → 8,33 |
| `ok` sobre `ok-soft` | arco Al día sobre su pista; icono del chip | 3,0:1 | #1E8449 / #DDF3E5 → 4,05 | #4FCB83 / #15301F → 6,92 |
| `nodata` sobre `surface` | anillo punteado Sin datos | 3,0:1 | #7A7482 / #FFFFFF → 4,52 | #A29CAB / #1D1A23 → 6,44 |
| `nodata` sobre `nodata-soft` | icono de los chips Sin datos y Pospuesto | 3,0:1 | #7A7482 / #EEEBF0 → 3,82 | #A29CAB / #2A2730 → 5,51 |
| `field` sobre `surface` | borde de los campos del formulario | 3,0:1 | #8C8694 / #FFFFFF → 3,53 | #7F7889 / #1D1A23 → 4,04 |
| `focus` sobre `bg` | anillo de foco sobre el fondo | 3,0:1 | #C2410C / #F5F3EF → 4,67 | #FF9A5C / #131118 → 8,95 |
| `focus` sobre `surface` | anillo de foco sobre una tarjeta | 3,0:1 | #C2410C / #FFFFFF → 5,18 | #FF9A5C / #1D1A23 → 8,19 |
| `focus` sobre `surface-2` | anillo de foco dentro de casillas y del selector de tema | 3,0:1 | #C2410C / #EFEBE4 → 4,36 | #FF9A5C / #29252F → 7,16 |

Además, una **auditoría del DOM renderizado** en Chrome sin interfaz (CDP) recorre todos los elementos con texto de las 14 pantallas,
calcula su color y el fondo efectivo y aplica 4,5:1 (o 3:1 si es texto grande); también los arcos de los anillos contra la tarjeta y
contra su pista, los iconos de chips y pestañas y los bordes de campos. Resultado en la sección «Verificación hecha».

Candidatos descartados por el cálculo: ámbar vivo `#F2A100` (2,13:1 sobre blanco) y `#E08A00` (2,69:1) para «Pronto», que no
llegaban a 3:1 en el anillo; `#C97400` pasaba justo (3,10:1 sobre su fondo de chip) y se oscureció a `#B86200` (3,87:1) para tener
margen. En el violeta, `#7C5CFA` daba 4,40:1 con texto blanco encima (no llega a 4,5) y se usó `#5536C8` (7,64:1). La pestaña activa
con `--primary-soft` (1,21:1 contra la barra) y el segmento elegido con `--surface` sobre `--surface-2` (1,19:1) se descartaron en la
revisión: no llegaban a 3:1.

### Tipografía

Dos familias de Google Fonts (OFL), pedidas como **variables** (`Figtree:wght@400..700`, `Outfit:wght@500..700`, `display=swap`), así
que el peso 650 de las filas es real y no se redondea a 700:

- **Outfit** (500–700): geométrica y redondeada; títulos, cifras de anillo, números destacados.
- **Figtree** (400–700): humanista y muy legible a tamaños pequeños; texto, etiquetas, chips, pestañas y formularios.
- Sin red caen a `ui-rounded` / `SF Pro Rounded` y `system-ui` (SF Pro en Apple, Roboto en Android, Segoe UI en Windows).

| Rol | Tamaño / interlineado (px) | Familia y peso |
|---|---|---|
| Cifra del medidor de la ficha | 34 en un SVG de 160 dibujado a 180 px: unos 38 en pantalla | Outfit 600 |
| Título de pantalla | 30 / 33 (34 / 37 desde 640 px) | Outfit 700 |
| Cifra de resumen (Estadísticas) | 26 / 30 | Outfit 600 |
| Título de tarjeta o sección | 20 / 25 | Outfit 600 |
| Nombre de bici (y de salida, en 600) | 19 / 23 | Outfit 700 |
| Nombre de fila | 16,5 / 21 | Figtree 650 |
| Texto | 16 / 24 | Figtree 400 |
| Secundario | 14 / 20 | Figtree 400 |
| Chip, etiqueta, grupo en mayúsculas | 13 / 16 | Figtree 600 |
| Etiqueta de pestaña (700 en la activa) | 12 / 15 | Figtree 600 y 700 |

### Radios, espaciado, sombras y tamaños

- **Radios:** 10 (información emergente del gráfico) · 14 (campos del formulario) · 16 (teselas de icono, botones, cifras, fila de la barra lateral) · 20 (tesela grande de la ficha) · 22 (tarjetas) · 26 (barra de pestañas flotante) · 28 (cabecera de bici) · píldora (chips, filtros, selector de tema y pastilla de la pestaña activa).
- **Espaciado:** base de 4 px: 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40. Márgenes de pantalla 16 px (móvil) y 32 px (escritorio); 16–20 px
  entre tarjetas; relleno de tarjeta 16 px.
- **Sombras:** en claro `0 1px 2px rgba(28,26,33,.06), 0 10px 24px -14px rgba(28,26,33,.22)`; en oscuro no hay sombra y la tarjeta lleva un borde de 1 px `#2F2B37`.
- **Anillos:** 52 px en filas, 60 px en «Requiere atención», 180 px en la ficha; trazo 6 px (13 px en la ficha), extremo redondeado;
  el arco muestra lo gastado (se llena con el uso); «Sin datos» con pista punteada y sin arco.
- **Objetivos táctiles:** ≥ 44 px en todo lo que se pulsa (filas de 64 px, pestañas de 60 px, botones de 50 px, chips de filtro y
  segmentos de 44 px). Las barras del gráfico no se pulsan ni reciben foco: la cifra de cada una está en su texto para lectores de
  pantalla y en «Ver como tabla»; con ratón muestran una información emergente.

### Accesibilidad

Semántica con `main`, `nav`, `section` + `h1`–`h3`, listas, `label` en cada campo y `fieldset/legend` en grupos; foco visible de 3 px
en `--focus` que no queda tapado por la barra de pestañas flotante (`scroll-padding-bottom` por debajo de 1000 px) ni por la barra
superior fija (`scroll-padding-top`); los campos muestran el foco también cuando Chrome lo lleva al botón del calendario; estados con
icono y palabra además del color; pestaña activa y segmento elegido con relleno de 3:1 o más, peso 700 y `aria-current` / radio
marcado; `prefers-reduced-motion` desactiva la entrada animada y el «encogido» al pulsar; «Ver como tabla» lleva un chevron que gira
al abrirse; `forced-colors` mantiene visibles arcos, chips, pestaña activa y segmento elegido.

## Trade-offs honestos

- **Es la opción continuista.** El anillo de fila (52 px, trazo 6, extremo redondeado, pista punteada para «Sin datos»), los chips con icono y palabra, los iconos de cada estado y la fila de 64 px son los del estilo actual «B Instrumentos» de `garage.css`. Cambian la piel (fuentes, violeta, tarjetas con aire), el icono de la pieza dentro del anillo en vez del porcentaje y la barra lateral en escritorio. Aporta menos novedad que una dirección nueva; a cambio, cuesta poco llevarla a la app.
- **Menos densidad.** Tarjetas con aire y anillos de 52 px: en un móvil caben unas 5 piezas por pantalla, frente a 8–9 del estilo actual. Con 30 piezas, la ficha de la bici obliga a desplazarse mucho.
- **Cifras menos precisas a primera vista.** El anillo dice «cuánto» de un vistazo; el número exacto queda en segundo plano (texto de 14 px).
- **Más color.** Cinco colores de estado más el violeta de marca: alegre, pero cansa antes y exige disciplina para no colorear lo que no es estado. El ámbar en claro tuvo que oscurecerse (`#B86200`) para cumplir 3:1 y queda menos «vivo» que en oscuro.
- **«En curso» comparte color con la marca.** Es tranquilo a propósito, pero un violeta en un anillo se lee como «normal» aunque en Garage signifique histórico incompleto.
- **Fuentes externas.** Dos familias de Google Fonts (unos 52 kB en WOFF2 variable, subconjunto latino: Figtree 20 kB + Outfit 32 kB); sin red cae al sistema y pierde parte del carácter redondeado.
- **Parecido a ProBikeGarage.** Quien venga de allí se orienta antes; a cambio, Garage gana menos identidad propia.
- **Envejece con la moda.** Tarjetas redondeadas, sombras suaves y barra flotante son el lenguaje de las apps de 2020–2026; puede verse fechado antes que una dirección más sobria.
- **Coste de implementar bajo-medio.** Como el anillo y los chips ya existen, el cambio es sobre todo de `garage.css` (fuentes, colores, tarjetas, barra flotante y lateral) y de las plantillas de filas (`_wear_row.html`, `_ring.html`: icono en vez de porcentaje); hay que dibujar y mantener los iconos de componente. El modelo de datos no cambia.

## Supuestos

- Garaje ficticio, el mismo en las tres opciones; «hoy» es el domingo 1 de noviembre de 2026. Fechas, importes, km de los neumáticos y de las piezas de la Grizl, el uso del Assegai, el reparto mensual y las intervenciones anteriores son inventados y cuadran entre sí (comprobado con un script): la Rallon hace 1.860 km desde el cambio de cadena del 12/05, la horquilla lleva 58 h desde el servicio del 05/08 y el amortiguador 89 h desde el del 26/06.
- El casete lleva los mismos 1.860 km que la cadena porque se cambiaron juntos el 12/05/2026; el casete anterior no se dibuja en Retirados porque el juego de datos sólo da la cadena retirada.
- «Pronto» es el estado que la app llama hoy «Próximo» (90 % del umbral). «En curso» se pinta tranquilo, con el color de marca; el boceto no añade el «≥» del histórico incompleto.
- «Revisar» y «Pospuesto» existen en la app pero no en el garaje de ejemplo, así que sólo aparecen en «Sobre esta dirección». Usan los colores de Pronto y de Sin datos con su propio icono (lupa y reloj): la paleta no crece.
- El neumático Assegai no tiene reglas propias: su aviso viene del líquido tubeless que lleva dentro, y la alerta del líquido abre la ficha del neumático.
- Sólo hay fichas completas de la horquilla, la cadena y el neumático; el resto de filas no navega (no tiene flecha). Posponer, editar, montar y retirar no están dibujados.
- Material vive en Más, como en la app actual; por eso su «atrás» vuelve a Más aunque se llegue desde el Garaje.
- Salidas enseña las 4 más recientes (las del encargo). Octubre suma 450 km en Estadísticas porque antes del 24/10 hubo más salidas.
- Guardar el formulario o «Sincronizar ahora» vuelve a la pantalla correspondiente sin recargar ni cambiar datos: el script intercepta el envío, así que `?tema=` se conserva. Sin JavaScript, el formulario hace un GET normal.
- El modo claro u oscuro se recuerda en `localStorage` (`garage-opcion1-tema`); `?tema=claro` u `?tema=oscuro` en la URL lo fuerza sin guardarlo.
- JavaScript mínimo: conmutador de tema, pestaña activa (`aria-current`), título de la página y envíos del boceto. La navegación funciona sin JS con `:target`.
- «Powered by Strava» como texto; no se usa el logotipo de Strava.

## Verificación hecha

Fuera del repositorio, en `/private/tmp/claude-501/design-work/option-1/`:

- `build.py` genera este `index.html` y este `README.md` desde las mismas listas (pares de contraste, escala, radios, trade-offs y
  supuestos), así que la página y el documento no pueden contarse cosas distintas.
- `contrast.py`: recalcula los 28 pares desde el CSS del `index.html` y compara con la tabla de la página: 0 fallos.
- `verify/data_check.py`: fechas, días de la semana, sumas del gráfico y del reparto, gasto y ritmos de la Rallon (km y horas desde
  cada intervención) cuadran.
- Auditoría del DOM (`audit.js` por CDP, las 14 pantallas, también las ocultas, porque el estilo calculado existe igual):
  **1.195 comprobaciones y 0 fallos** en cada modo (claro forzado, oscuro forzado, automático con el sistema en claro y en oscuro),
  sin fondos translúcidos detrás de texto. Incluye las marcas de estado: pastilla de la pestaña activa contra la barra 7,64 / 7,84,
  segmento elegido contra su carril 6,43 / 6,86 y filtro elegido contra el fondo 6,90 / 8,56 (claro / oscuro).
- Segunda auditoría por pantalla visible (`verify/inpage.js`, 14 pantallas × 375, 768 y 1280 px × claro y oscuro = 84 casos,
  6.224 textos): 0 textos y 0 elementos no textuales por debajo del mínimo y 0 desbordes horizontales. Lo que aún marca son falsos
  positivos revisados: etiquetas de campos de 50 px contadas como objetivos pequeños, las cifras del eje del gráfico (colocadas fuera
  de su caja a propósito), la tabla de «Ver como tabla» cerrada y cajas de `code` partidas en dos líneas.
- Foco con teclado (`verify/func.mjs`, `verify/func390.mjs`): Tab por 10 pantallas a 375×667 y 390×844, **0 elementos enfocados
  bajo la barra de pestañas o la barra superior** (antes del arreglo: hasta 20 por pantalla y 3 tapados del todo).
- Barra lateral a 1280 px (`verify/side.mjs`): icono y etiqueta centrados en cada fila de 50 px. Etiqueta «Estadísticas» de 65 px
  dentro de una pestaña de 69,8 px a 375 px.
- Formularios (`verify/func2.mjs`): con `?tema=oscuro`, «Guardar intervención» lleva a `index.html?tema=oscuro#taller` y
  «Sincronizar ahora» se queda en `#strava`, los dos en oscuro y sin recargar.
- Capturas con Chrome sin interfaz y perfil temporal propio en claro y oscuro (pantallas completas a 375, 768 y 1280 px y detalles de
  la barra de pestañas, el selector de tema, «Ver como tabla» y el foco) en `verify/shots/`.
- No verificado: lectores de pantalla reales (VoiceOver/TalkBack), Safari/Firefox, y la carga de fuentes en un móvil real.
