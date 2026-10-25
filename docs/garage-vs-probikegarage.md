# Garage frente a ProBikeGarage

Fecha: 18 de octubre de 2026. Autor: Claude (garage-039). Base: el análisis REA
de ProBikeGarage del 17 oct (`docs/research/2026-10-17-probikegarage-rea.md`,
sólo comportamiento observado y nombres de la API, sin código de terceros) y el
estado de Garage tras garage-034 a garage-038. Garage está pensado para uso
personal y de algunos amigos (iPhone y Android, como web instalable), sin
suscripción, y **todavía no está desplegado**: hoy funciona en local.

## En una frase

Garage ya iguala o supera a ProBikeGarage en el taller (reglas, vida útil,
posponer, piezas anidadas, historial y costes) y en honestidad con los datos.
Le falta desplegarse y probarse en un teléfono real, la sincronización
automática con Strava (decidida y aplazada, garage-030), el desnivel (diseñado,
garage-037) y los avisos fuera de la app (garage-027, por definir).

## Comparación por área

| Área | ProBikeGarage | Garage | Quién va delante |
|---|---|---|---|
| **Material de la persona por bici o deporte** (casco, zapatillas, calas) | No se observó un concepto propio: el material va montado en una bici o en un componente, con etiquetas por tipo de actividad en el montaje | **Perfiles de uso versionados** por bici o deporte («Carretera habitual»: zapatillas y casco), con excepciones por salida y revisión de cada salida; el casco cuenta en todas las bicis sin estar montado en ninguna | **Garage** |
| Bicis y componentes | Catálogo fijo de tipos, marca/modelo de catálogo, alta guiada de una bici completa | Categorías libres, marca, modelo, nº de serie, precio y moneda; sin catálogo ni alta guiada | ProBikeGarage en alta rápida; Garage en libertad y costes |
| Piezas anidadas (casete y disco en la rueda) | Sí; registrar un servicio en el padre repara todas sus piezas | Sí (garage-035): sección «Piezas», «Añadir pieza», entradilla «En Rueda · Gravel»; al registrar se marcan explícitamente las reglas del destino y de sus piezas; ciclos y solapes validados en el tiempo | Empate: Garage más fiel (regla a regla, nunca reinicia en silencio); ProBikeGarage más rápido (repara todas las piezas a la vez) |
| Historial de montajes | Intercambios con fechas; impide solapes en el mismo destino y montar en retirados | Períodos sin solapes garantizados por PostgreSQL, posiciones exclusivas (rueda delantera/trasera, disco), traspasos, reemplazo atómico, períodos inactivos al reactivar | **Garage** |
| **Intervalos de servicio** | Un tipo por intervalo (km, tiempo en movimiento, tiempo transcurrido, actividades, desnivel con Premium); repetir o no | Una regla con km, horas, salidas y días **a la vez, vence con lo primero que llegue**; aviso al 90 %; siempre se repite | **Garage** (salvo desnivel e intervalos de una sola vez) |
| **Vida útil** | Intervalo de servicio genérico | De primera clase (garage-033): km, horas y tiempo en días/meses/años, sugerencias por pieza, inicio por defecto; **la pieza nueva la hereda al reemplazar** (casilla marcada por defecto) | **Garage** |
| Posponer | Por tipo y cantidad, en bici, componente o intervalo | Por regla (garage-034), km/horas/salidas/días **lo primero que llegue**, siempre con máximo de días, atajos de un toque; termina sola con una intervención (también con fecha anterior) y nunca oculta un aviso con uso desconocido | Garage por regla y honestidad; ProBikeGarage permite posponer una bici entera de una vez |
| Registrar un servicio | Varios componentes e intervalos en un registro, adjuntos | Intervención principal + «También en esta visita» (una por regla marcada, misma fecha y nota); fecha y hora local, coma decimal, **importe y moneda**, fotos, lecturas | Empate; Garage guarda el coste |
| Uso en cada servicio | Uso acumulado y diferencia con el anterior | «Desde la anterior» y «hasta la siguiente / desde entonces» en cada intervención (garage-036), con mínimo «≥» o lectura | Empate (Garage no guarda el acumulado de toda la vida en cada una; lo muestra aparte) |
| **Comparar piezas** | No se observó | «Cuánto dura cada uno» por categoría (garage-036): km de toda su vida (con lecturas) o lo registrado, días montado (el material que no se monta, desde el inicio de uso o la compra), retirados incluidos | **Garage** |
| Retirar | Retirar con o sin lo montado; retirar al reemplazar | Igual desde garage-038, todo o nada; reactivar conserva el historial | Empate |
| **Honestidad con los datos** | Sólo «configuración pendiente» (`setup_pending`); no se observaron marcas de dato parcial ni estimado | Uso desconocido, mínimo observado «≥», lecturas manuales con ámbito y marca de estimada «≈»; los avisos nunca se apoyan en datos desconocidos | **Garage** |
| Material usado | Uso inicial manual | «Material ya usado» con lecturas previas de km, horas y salidas | Empate |
| **Salidas** | Sincronización con Strava (manual y automática al menos una vez al día) y etiquetas | Importación de FIT de Garmin con vista previa, deduplicación, ejecuciones reanudables y correcciones manuales que sobreviven a la reimportación; salidas manuales; **sin Strava** (030 aplazada) | **ProBikeGarage** en comodidad; Garage en control del dato |
| Desnivel, potencia, cadencia | Sí (desnivel en intervalos y estadísticas con Premium) | No (desnivel diseñado en garage-037, pendiente de activar) | **ProBikeGarage** |
| Estadísticas | Totales, medias y máximos; casi todo con Premium | Período (12 meses, año, año pasado, todo, personalizado), gráfico mensual, reparto por bici, material más usado, **gasto y coste por km** (con distancia completa) | Garage en coste y sin pago; ProBikeGarage en métricas de rendimiento |
| Avisos | En la app y notificaciones push (deducidas de Firebase Cloud Messaging y sus canales) | En la app (Inicio, Taller, fichas); canal fuera de la app por definir (garage-027, abierta; depende de garage-024) | **ProBikeGarage** |
| Fotos y adjuntos | Adjuntos y foto de portada | Fotos privadas WebP (2000 px) con cuota en bici, material e intervención; bucket real pendiente (garage-010) | ProBikeGarage (más tipos) |
| Exportación | Informe (Premium) | JSON y CSV (ZIP) de todos los registros; fotos sólo como referencia, sin el archivo ni el FIT original | **Garage** |
| Plataforma | App Flutter en tiendas y web; ~10 idiomas | Web instalable (PWA) iPhone/Android, estilo nativo por sistema, modo oscuro; sólo español; **pendiente de desplegar** | ProBikeGarage en alcance; Garage sin tiendas ni cuentas de terceros |
| Precio | Suscripción Premium (Paddle, App Store, Google Play), afiliados | Propio, sin suscripción ni publicidad | **Garage** para uso personal |

## Lo que Garage hace y no se observó en ProBikeGarage

1. **Material por bici o deporte sin montarlo**: zapatillas y casco cuentan sus
   km en las salidas de la bici o el deporte del perfil, con historial de
   perfiles y excepciones por salida.
2. **Reglas con varios umbrales a la vez** (km, horas, salidas, días; lo primero
   que llegue), también en la vida útil y al posponer.
3. **Vida útil heredada** por la pieza de repuesto, en la misma operación que el
   reemplazo.
4. **Honestidad**: desconocido, mínimo «≥», estimado «≈»; un aviso nunca se oculta
   ni se da por bueno con datos desconocidos.
5. **Costes**: precio de compra, importe por intervención con moneda, gasto del
   período y coste por km.
6. **Importación FIT robusta** con correcciones manuales que sobreviven.
7. **Comparar cuánto dura cada pieza** de una categoría.
8. **Exportación de todos los registros propios**.

## Lo que aún falta, de más a menos impacto

1. Desplegarlo (garage-023, tras 010 y 022) e instalar la PWA en un teléfono
   real (garage-031): hoy sólo funciona en local.
2. Sincronización con Strava (garage-030, aplazada por decisión del usuario).
3. Desnivel en salidas, reglas y estadísticas (garage-037, diseñado).
4. Avisos fuera de la app (garage-027, por definir; depende de garage-024).
5. Fotos en un bucket real (garage-010, espera la credencial), otros adjuntos y
   foto de portada.
6. Catálogo de componentes y alta guiada de una bici.
7. Posponer una bici o un componente entero de una vez.
8. Potencia, cadencia, temperatura, velocidad, energía, mapa, y medias y máximos
   por salida.
9. Detalles: intervalos de una sola vez, bici por defecto, cantidad de piezas,
   etiquetas por tipo de actividad (Garage usa perfiles por deporte).

Fuera de alcance por las reglas del proyecto: cobros y suscripciones, apps de
tienda, servicios de pago y nueva infraestructura (afecta también a los avisos
push). Afiliados e idiomas no se plantean para el uso personal, salvo que el
usuario los pida.
