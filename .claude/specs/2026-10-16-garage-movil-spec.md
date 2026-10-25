# Especificación garage-031: Garage en el móvil (web instalable, estilo B)

Fecha: 16 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-031`.
Boceto aprobado: `docs/mockups/garage-movil.html`, estilo **B «Instrumentos»**.
Rama `codex/garage-plan`; sin commits, staging, push ni despliegue.
Revisión independiente del 16 oct incorporada (ver §15).

## 1. Objetivo

Que Garage se use cómodamente desde el teléfono, instalado como una app, en
iPhone (Safari) y Android (Chrome), con una sola base de código: plantillas
Django renderizadas en el servidor, CSS y JS propios mínimos, sin SPA, sin
frameworks ni CDN, sin apps de tienda. Lo usarán el usuario (iPhone) y amigos
(Android). Cifras grandes, anillos de desgaste, iconos, gráficos, menú inferior.

Terminada cuando, desde un teléfono, se puede instalar Garage, ver qué requiere
atención, abrir la ficha de un componente con su desgaste, uso mensual,
montajes e intervenciones, y revisar una salida (bici y material) viendo su
efecto antes de guardar. Las demás páginas siguen funcionando dentro del marco.

## 2. Alcance y división

Se divide en cuatro subtareas, en este orden (cada una con pruebas propias):

| Subtarea | Contenido | Depende de |
|---|---|---|
| 031a | Marco común, PWA, login, estilo genérico, Más, Añadir (§4, §5) | — |
| 031b | Presentación del desgaste e Inicio (§6, §7) | 031a |
| 031c | Uso mensual, gráfico y ficha de componente (§8, §10) | 031b |
| 031d | Revisión de salida y lista de Salidas (§9, §11) | 031b |

No incluye: rediseño de Taller, Estadísticas, ficha de bici, formularios largos,
fotos con cámara, notificaciones push (garage-027), API (garage-024), Strava
(garage-030). **Sin cambios de modelo ni migraciones.** Las migraciones
`garage.0001`–`0008` ya existen en la base de producción (aplicadas por el
contenedor Docker el 12 oct): no se pueden editar.

## 3. Decisiones

| Tema | Decisión |
|---|---|
| Tecnología | Plantillas Django + `garage/static/garage/garage.css` + `garage.js` (vanilla, `defer`). Sin htmx ni librerías. Sin scripts ni estilos inline. |
| Estilo | B «Instrumentos»: filas compactas con separadores, cifras grandes en `ui-monospace`, anillos de desgaste, cabeceras de sección en mayúsculas pequeñas, acento cobalto. |
| Letra | Fuentes del sistema (San Francisco / Roboto). Nada externo. |
| Iconos | Sprite SVG `garage/_icons.html`, trazo 1,8, `currentColor`. |
| Tema | Tokens CSS; oscuro con `prefers-color-scheme`. Sin selector manual. |
| Plataforma | El servidor pone `data-os="android"|"ios"` en `<html>` por user agent (sin salto visual). Diferencias: icono de volver, botón Añadir (arriba / flotante), aviso de instalación, interruptores. |
| Fluidez | `@view-transition { navigation: auto; }` salvo `prefers-reduced-motion`; vista previa de la revisión por `fetch` de un fragmento. |
| Zona horaria | Cookie `garage_tz` escrita por `garage.js`, validada con `zoneinfo`; si no, `GARAGE_DEFAULT_TIME_ZONE` o `Europe/Madrid`. Sólo afecta a las pantallas nuevas; las plantillas antiguas siguen en UTC. |
| Versión de estáticos | `garage/assets.py`: `ASSET_VERSION` = 10 primeros hex del SHA-256 de `garage.css`+`garage.js`. Se añade `?v=` en `shell.html` y en el service worker, y forma parte del nombre de su caché. |
| Sesión | Sin cambios (2 semanas). Ampliarla lo decide el usuario. |

Paleta estilo B: ver `garage.css` (tokens claro y oscuro; estados bien
`#0ca30c`, aviso `#fab219`, vencido `#d03b3b`, con variantes de icono por modo).
Un estado nunca va sólo con color: siempre icono + palabra.

## 4. Marco común (031a)

- `garage/shell.html`: documento completo que **no** extiende el `base.html`
  raíz de Strava. Cabecera con `viewport-fit=cover`, `theme-color` claro/oscuro,
  manifiesto, `apple-touch-icon`, favicons, metadatos `apple-mobile-web-app-*`,
  CSS y JS con `?v=`. Bloques: `title`, `body_class`, `appbar`, `content`, `fab`, `tabbar`.
- `garage/base.html` (reescrito): extiende `shell.html`; barra superior con
  bloques `appbar_back` (por defecto, enlace si el contexto trae `back_url`) y
  `appbar_actions`; mensajes con `role="status"`; bloque `garage_content`
  intacto, así que **todas las plantillas actuales funcionan sin cambios**;
  menú inferior.
- Menú inferior (5 pestañas, iconos + texto, ≥ 48 px, zona segura inferior),
  `aria-current` por variable `tab` o por nombre de URL:

| Pestaña | Destino | Nombres de URL |
|---|---|---|
| Garaje | `index` | todo lo no listado (bici, objeto, montaje, lecturas, fotos, `add`) |
| Salidas | `usage-ride-list` | `usage-ride-*`, `ride-review*`, `history*` |
| Taller | `maintenance` | `maintenance*`, `service-*` |
| Estadísticas | `statistics` | `statistics` |
| Más | `more` | `more`, `category-*`, `usage-profile-*`, `export*` |

- **Más** (`more/`): Bicis, Material, Categorías, Perfiles de uso, Exportar,
  instrucciones de instalación y cerrar sesión (POST). (Las excepciones son la
  propia pestaña Salidas; el histórico se enlaza desde Salidas.)
- **Añadir** (`add/`): Bici, Material nuevo, Material ya usado, Salida manual,
  Importar FIT, Mantenimiento hecho, Categoría.
- Login (`registration/login.html`): extiende `shell.html` sin menú; conserva
  «Entrar en Garage» y `next=/garage/`; `autocomplete` correctos.
- Estilo genérico para lo existente (tarjetas, formularios, tablas en
  contenedor desplazable, paginación, `details`, botones ≥ 44 px). Sin
  desplazamiento horizontal a 360 px.

## 5. Instalación (031a)

- `manifest.webmanifest` (público, `application/manifest+json`): `id`/`start_url`
  `/garage/`, `scope` `/`, `display` `standalone`, `lang` `es`, colores, iconos 192,
  512 y 512 `maskable`. Con `scope` `/` el login queda dentro de la app; también
  quedan dentro las páginas antiguas del sitio (documentado).
- `sw.js` en `/garage/sw.js` (público, `no-cache`, alcance `/garage/`):
  - precarga estáticos con `?v=` y la página sin conexión (pedida con
    `credentials: 'omit'`) en `garage-<ASSET_VERSION>`; borra cachés antiguas;
  - navegaciones GET: red; si falla, la página sin conexión. Nunca guarda HTML
    de páginas con sesión; POST, fragmentos, fotos y exportaciones no se tocan;
  - estáticos de `/static/garage/`: caché primero con actualización en segundo plano.
- `offline/` (público): extiende `shell.html`, sin datos de usuario, sin CSRF.
- Iconos en `garage/static/garage/icons/` generados por `tools/garage_icons.py`.
- Aviso de instalación descartable (Inicio): iPhone no instalado →
  «Compartir → Añadir a pantalla de inicio»; Android → botón con
  `beforeinstallprompt`. En iOS instalado, el usuario entra una vez (cookies
  propias de la app). Las descargas de exportación pueden fallar dentro de la app
  instalada en iOS; se documenta.
- Prueba en teléfono real: tras desplegar con HTTPS (garage-023).

## 6. Presentación del desgaste (031b)

`garage/presentation.py` (puro): `wear(due) -> Wear`.

| Estado | Condición | Palabra | Texto |
|---|---|---|---|
| `due` | dominio `due` | «Vencido» | `+N unidad de más` |
| `review` | dominio `unknown`, valor conocido ≥ 90 % | «Revisar» | «≥ 95 %» |
| `soon` | dominio `soon` | «Próximo» | `N unidad quedan` |
| `nodata` | valor desconocido | «Sin datos» | anillo discontinuo |
| `progress` | dominio `unknown`, valor conocido < 90 % | «En curso» | «≥ 62 %» |
| `current` | dominio `current` | «Al día» | `N unidad quedan` |

- Orden de gravedad: due > review > soon > nodata > progress > current. La
  métrica titular es la más grave (a igualdad, mayor `valor/umbral`), así nunca
  se ve «Al día» o «En curso» si alguna métrica no tiene datos.
- Cota inferior («≥», «como máx.») sólo con cobertura parcial **y sin lectura
  estimada**. Con lectura estimada: «≈ 95 % · estimado» y «Restante estimado».
- Porcentajes hacia abajo; miles con «.» y decimales con «,».

## 7. Inicio (031b)

1. **Requiere atención**: reglas en due, review y soon (máx. 6; luego «Ver todo
   en Taller»), más «N salidas por revisar» y «N reglas sin datos» (→ Taller).
   Pie con el texto del 90 % (las pruebas exigen «90 %»).
2. **Salidas por revisar**: inicio conocido, sin bici y sin clave `bike` en
   `manual_overrides` (la clave con `None` ya significa «desconocida marcada
   explícitamente»; el formulario manual siempre la envía).
3. **Bicis**: activas, km y horas de sus salidas (agregado sobre `Ride`), y
   avisos due/review/soon de reglas de la bici o de objetos montados ahora en
   ella, directa o anidadamente.
4. **Equipación y material sin montar**: objetos activos sin montaje abierto;
   «En uso» si están en un perfil vigente (subtítulo: bici o «Cualquier bici» y
   deporte), luego «Guardado». Cifra: km registrados (`Sum` de `ItemUsage`), o
   «pendiente» si el uso aún no está reconstruido.
5. Aviso de instalación; en Android, botón flotante «Añadir».

Sin escrituras. Presupuesto ≤ 26 consultas (incluidos SAVEPOINT/RELEASE).

## 8. Ficha de componente (031c)

`inventory_detail` usa `garage/item_detail.html` (extiende `garage/base.html`)
para `kind == "item"`; bicis y categorías siguen con `detail.html`.

1. Cabecera: icono por palabras clave de categoría/nombre, nombre, estado de
   montaje («En Carretera desde …», «Sin montar», «Retirado el …»), foto.
2. **Desgaste**: una tarjeta por regla del objeto (más grave primero): anillo
   grande con la cifra titular, palabra de estado y mini barras de cada métrica
   (km, horas, salidas, días). Sin reglas: botón «Crear regla».
3. **Uso**: «Registrado en Garage» (`row.observed` de `statistics`) y, si hay
   lectura de por vida, el total con ella. Uso pendiente si no está reconstruido.
4. **Km por mes**: 12 meses locales (§10).
5. **Montajes**: línea de tiempo desde `statistics`.
6. **Intervenciones** y **costes**: eventos del objeto; coste por km por moneda
   o su motivo cuando no se puede calcular (lo habitual sin cobertura completa).
7. Todo lo existente: fotos, «Material montado sobre este objeto», lecturas
   previas, «Historial completo», acciones de montaje, editar, retirar.
8. Barra fija: «Registrar mantenimiento» (`service-event-create?item=<id>`; la
   vista valida que el objeto es propio y lo preselecciona) y «Mover» si está
   montado. «Crear regla» igual con `maintenance-rule-create?item=<id>`.

Sin escrituras. Presupuesto ≤ 45 consultas.

## 9. Revisión de una salida (031d)

Rutas: `rides/<uuid>/review/` (`ride-review`; GET, POST; con `?bike=…&gear=…`
muestra el estado hipotético y su efecto sin JS) y `rides/<uuid>/review/preview/`
(`ride-review-preview`; GET; sólo el fragmento «Al guardar»).

Pantalla: datos de la salida (nombre, fecha local, procedencia, km, tiempo, media),
**¿Con qué bici?** (bicis activas + «Otra o desconocida»), **Material que
llevaste** (interruptores), **Al guardar** (vista previa) y botones «Guardar» y
«Luego». Salida sin inicio: explica y enlaza a la corrección completa.

Candidatos (los recalcula siempre el servidor): objetos propios no retirados al
inicio de la salida (`retired_at` y `RetirementInterval`), sin montaje que cubra
ese instante, y que estén en un perfil vigente en ese instante o tengan ya una
excepción en esta salida. Etiquetas: «Habitual en …», «Añadido sólo en esta
salida», «Quitado sólo en esta salida». Elegir bici pasa los interruptores al
material habitual de esa bici.

Servicio `garage/services/ride_review.py`:

- `review_state(actor, ride_id, *, bike=UNCHANGED, gear=None)`: salida, bicis,
  candidatos con «habitual» por opción de bici, estado actual y, si se pasan
  `bike`/`gear`, la vista previa. Sin escrituras.
- `review_ride(actor, ride_id, *, bike, gear)`: valida `gear ⊆ candidatos`
  (si no, error). Con `R0` = resolución para la bici elegida sin excepciones de
  candidatos (las de no candidatos se conservan): candidato en `gear` y fuera de
  `R0` → `include`; fuera de `gear` y dentro de `R0` → `exclude`; si no, se borra.
  Bici: se escribe corrección manual (misma semántica que `correct_ride`) si la
  clave `bike` falta en `manual_overrides` o su valor difiere.
  Todo con `_lock_owner` en una transacción. Reconstrucción: si el propietario
  no está inicializado, `_rebuild_all_locked`; si no, sólo esa salida. Requiere
  refactorizar `rides._recalculate(..., rebuild=True)` para no reconstruir dos veces.
- Invariante: tras guardar, cada candidato cuenta si y sólo si está en `gear`.
- Equivalencia (prueba): mismas filas de `ItemUsage` que aplicando los servicios
  públicos uno a uno, comparando `ride, item, started_at, bike, métricas,
  ride_count`, sin ids de `resolution` ni marcas de tiempo.
- Vista previa: diferencia entre las filas actuales de esa salida y la
  resolución hipotética (incluye lo montado en un candidato): `+92,4 km` /
  `−92,4 km` y horas por objeto, y bici origen → destino. No calcula
  porcentajes. Avisa si quedan excepciones `include` de componentes de otra bici.
- Tras guardar, la vista compara `maintenance_due` antes y después y muestra las
  reglas que cambian de estado («Cambio de cadena: En curso → Revisar»).

Vista: `login_required`, métodos permitidos, CSRF, 404 para ajenos.

## 10. Uso mensual (031c)

`monthly_usage(actor, *, item=None, bike=None, metric, months=12, tz, at=None)`:
meses naturales locales `[desde, hasta)` en UTC, último en curso, suma de
valores conocidos (`None` si todas faltan; 0 sin filas). Con objeto, si el uso no
está reconstruido devuelve los meses sin valor y la marca `trusted=False`.
Presupuesto ≤ 8 consultas (medido, con savepoints). `charts.line_chart()` puro: ticks 1-2-5, huecos en
meses sin datos, mes en curso discontinuo, etiquetas sólo en máximo y mes en curso,
estado vacío; tooltip y tabla accesible.

## 11. Salidas (031d)

Se conserva la vista; filas estilo B con fecha local, nombre, km, bici o
«Sin bici», enlace a la revisión; enlace a Histórico e importación. Se mantienen
los textos que comprueban las pruebas. `usage-ride-detail` gana «Revisar».

## 12. Privacidad, seguridad y rendimiento

Manifiesto, service worker, iconos y página sin conexión públicos y sin datos.
Vistas con datos: `login_required`, propietario, 404 ajenos, CSRF. Cookie de
zona validada. Sin scripts inline. GET sin escrituras.

## 13. Pruebas

Por subtarea, con PostgreSQL de pruebas y `settings_test`:

- 031a: pestañas y `aria-current`; sin «Strava Tools»; manifiesto; `sw.js`
  (tipo, `no-cache`, versión, sin datos de usuario); offline público sin CSRF;
  Más, Añadir y login; las páginas existentes renderizan con el marco.
- 031b: tabla de §6 (incluido nodata y estimado), Inicio con datos ficticios,
  salidas por revisar, presupuesto, cero escrituras, «90 %».
- 031c: `monthly_usage` (Madrid y Buenos Aires, cambio de hora, mes en curso,
  ausentes, sin reconstruir, propiedad), `line_chart`, ficha, prefijado de
  evento/regla con objeto propio y rechazo de ajeno.
- 031d: candidatos, invariante, equivalencia, reconstrucción única e inicializada,
  «Otra o desconocida» en salida FIT, vista previa sin escrituras, sin JS,
  mensaje de cambio, ajeno 404.
- Pruebas existentes que tocan estas plantillas: `tests_views.py:166,185`,
  `tests_photo_views.py:46`, `tests_usage_views.py:152-154,163-169,177-182`,
  `tests_maintenance_due.py:162-167`, `tests_inventory.py:275-280`.

Además: suite completa, `check`, `makemigrations --check`, `node --check`,
capturas en Chrome sin interfaz y revisión independiente por subtarea.

## 14. Ideas de ProBikeGarage (sin copiar)

Garage ya cubre o supera: material sin bici (perfiles «cualquier bici»),
excepciones por salida en vez de etiquetas globales, componentes anidados, días
de calendario aunque no se use, costes por km por moneda, importación FIT,
exportación completa, honestidad con datos incompletos, gratis para los amigos.
En 031: línea de vida del componente y alta rápida desde «Añadir».
Para después (proponer como tareas): posponer avisos; plantillas de alta con
intervalos sugeridos; comparar la duración de componentes de la misma categoría;
desnivel como métrica.

## 15. Riesgos, límites y revisión

- Teléfono real sólo con HTTPS (tras garage-023).
- `STATICFILES_STORAGE` obsoleto en Django 5.2 (sin hash): mitigado con `?v=`;
  corregir `STORAGES` en garage-023.
- `ride_list` resuelve fila a fila (~180 consultas por página): en 031d se
  comparte un contexto o se omite la resolución en la lista.
- Revisión independiente (16 oct): orden de gravedad con «Sin datos», lecturas
  estimadas, «Sin bici» en salidas FIT, reconstrucción única, candidatos según el
  resolvedor, totales y coste por km, uso no reconstruido, presupuestos con
  savepoints, prefijado de formularios, service worker, pestañas y división en
  subtareas: todo incorporado arriba.
