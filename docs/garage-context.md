# Contexto completo para continuar Garage

Documento de relevo solicitado por Maxi el 10 de octubre de 2026. Resume los
requisitos, las alternativas discutidas y las decisiones efectivas; no pretende
ser una transcripción literal del chat. El estado operativo cambia y se consulta
en [garage-handoff.md](garage-handoff.md) y Beads. Las especificaciones detalladas
están en GARAGE_PLAN.md y garage-domain.md.

## Qué quiere el usuario

Maxi usa ProBikeGarage (https://www.probikegarage.com/), tiene comprada la app,
pero no quiere pagar la suscripción premium. Quiere implementar las funciones
que necesita en su propio proyecto, sin servicios de pago. No se ha obtenido ni
copiado código de ProBikeGarage: Garage es implementación propia.

Requisitos que expresó:

- Varias bicis y componentes físicos individuales, con historial, revisiones,
  avisos e intervenciones.
- Fotos, más estadísticas que las básicas y categorías editables.
- Equipamiento independiente de una bici: casco, zapatillas, calas y similares
  pueden usarse en varias bicis manteniendo un único historial.
- Un objeto se monta/desmonta muchas veces, en la misma bici o en otras.
  Ejemplo obligatorio: dos sillines alternados A→B→A.
- Al dar de alta material usado: uso previo conocido o estimado, instante al que
  corresponde, fecha de compra, coste/moneda y notas. Puede introducir a mano el
  contador que tiene en Garmin.
- Completar retroactivamente salidas y asociaciones de bici que faltan. La fuente
  no se da por resuelta por disponer de una cuenta Strava.
- A medio plazo, apps iOS y Android. A medio/largo plazo, monetizar y ofrecerlo a
  más usuarios: los modelos ya deben tener propiedad por usuario.
- Trabajar en el repositorio local, con rama y **sin commits por ahora**.
- Tareas concretas en Beads para modelos económicos, pruebas de todos los
  comportamientos nuevos y revisión adversarial independiente.
- Progreso visible en HTML: actualización, detalles de tarea como bd show y DAG
  de dependencias/estados, con nodos y enlaces clicables.

17 oct 2026, tras analizar ProBikeGarage con REA
(`docs/research/2026-10-17-probikegarage-rea.md`): incorporar lo que falta
(«posponer un vencimiento … por días, km, etc.», «componentes anidados»); el
desnivel y la sincronización con Strava «luego»; «ante la duda, documenta las
opciones y elige una»; y al final una comparación con ProBikeGarage que recuerde
lo que Garage hace mejor («como lo de material que está asociado a una bici
(casco, zapatillas…)»). Hecho en garage-034 a 039 (`docs/garage-vs-probikegarage.md`).

El usuario pidió varias pausas y reanudaciones. Esas pausas históricas no cancelan
el proyecto. Su petición vigente es dejar el relevo a Claude/otra IA; no afirmar
que hay agentes trabajando después de terminar este turno.

## Alternativas discutidas y decisiones

### Reutilizar Django o empezar de cero

Se decidió mantener Stravagancia y añadir **garage como nueva app Django**.
Ya hay autenticación, PostgreSQL, plantillas y despliegue del proyecto existente.
No crear una SPA ni otro backend. La lógica de dominio se separa de las vistas
para reutilizarla en una futura API móvil.

El usuario preguntó por Rust o Go para ganar velocidad. Se mantuvo Python/Django:
el trabajo inicial es de datos, coherencia, consultas e importación, sin una
necesidad demostrada de reescribir el servidor. Optimizar con evidencia si aparece
un cuello de botella. No hay una migración a otro lenguaje pendiente.

### Fotos: comprimir, recortar o reescalar

Se decidió comprimir y **reescalar sólo si el lado mayor supera 2000 píxeles**,
conservando proporción, sin recortar ni ampliar imágenes pequeñas. Ejemplos:
4000×3000 → 2000×1500; 1200×800 se conserva. Orientación EXIF antes de reescalar;
eliminar metadatos, guardar WebP (calidad 85 como punto inicial).

Se soportan JPEG, PNG y WebP estáticos. HEIC no se prometió. Hay límites de 15 MiB
de entrada, 25 megapíxeles decodificados y protección de memoria/formatos.
La transformación está completa; las fotos privadas están integradas localmente,
pero su persistencia en un bucket real todavía no se ha comprobado.

### Datos de actividades y fuente histórica

Las salidas se capturan con Garmin Edge 840 y se sincronizan a Strava. Maxi paga
Strava y Stravagancia ya baja y muestra datos de esa API. Esto dio lugar a evaluar
reutilizar el histórico existente o volver a descargar actividades/bicis.

Tras revisar las fuentes oficiales se decidió **Garage usa FIT originales propios
aportados por el usuario y entradas manuales**. La política API revisada el 4 de octubre
impide asumir que el histórico permanente y sus derivados son admisibles para
Garage; pagar Strava no elimina sus restricciones. Las tareas013 y021 están
cerradas por no aplicabilidad, sin adaptador ni cola Strava implementados.

**Revisión del 12 de octubre (garage-029):** con Garage para uso personal, el
usuario eligió sincronizar desde Strava como ProBikeGarage (adaptador propio,
`gear_id` para la bici, retirable). Queda **aplazado** en garage-030; hasta
activarlo rige la decisión anterior. Ver garage-data-sources.md.

No vaciar, migrar, reetiquetar ni modificar las tablas del legado Stravagancia
como parte de esta decisión. Separar modelos no demuestra una excepción
contractual. Antes del despliegue sigue pendiente revisar el ámbito de la
Developer Application, su legado y la titularidad explícita de datos existentes.
Para detalles y fuentes fechadas, ver garage-data-sources.md. No convertir este
resumen en una afirmación jurídica o en una verificación actual de términos.

El usuario aportó ~/Downloads/24583055262_ACTIVITY.fit. Se validó localmente en
memoria: una sesión de ciclismo, UTC, distancia, temporizador y tiempo transcurrido;
no había movimiento explícito ni identificación suficiente de la bici.
No copiarlo a fixtures, documentos, repo o demo ni subirlo a terceros.
Los tests usan FIT sintéticos. La bici se asigna manualmente o por lotes; el Edge,
sensores o marchas no identifican automáticamente la bici física.

Se usa fitdecode 0.11.0 (MIT, avisos conservados), con validación estricta CRC,
encuadre/tamaño, límites y campos nativos enteros. El SDK oficial se evaluó como
contraste, no se incorporó al runtime. TCX/GPX y API Garmin no están implementados
ni se da por garantizado acceso personal gratuito a esta última.

### Infraestructura y coste

Mantener Neon y alojamiento existentes en plan gratuito. El aumento de cuota
consultado del 2 de octubre correspondía a PostgreSQL. La documentación/consola
revisadas el 4 de octubre indicaban Free con 1 GB de PostgreSQL y 5 GB de Object Storage
por proyecto, región Frankfurt; no había bucket. **Es evidencia fechada, no
garantía actual ni autorización para crear infraestructura.**

Diseño: PostgreSQL guarda referencias; fotos en bucket privado compatible con S3,
secretos sólo en servidor y acceso autorizado antes de enlaces temporales.
El disco de RenderFree es efímero; no usarlo como archivo persistente.
garage-storage.md detalla compatibilidad, quotas y comprobación externa pendiente.
No introducir gasto, planes pagos ni cuentas nuevas como parte de la implementación.

### Móvil, multiusuario y monetización

Preparar hoy UUID estables, propiedad por settings.AUTH_USER_MODEL, servicios
reutilizables, UTC y errores consistentes. No cambiar el modelo de usuario sin
necesidad ni crear organizaciones/equipos ahora. API versionada, sincronización,
clientes móviles, registro comercial, planes/cobros y notificaciones externas
son fases futuras024–027. Los avisos actuales son internos a la app.

### Agentes y revisión

El usuario inicialmente preguntó por Luna para trabajo acotado; después autorizó
Sol y pidió lanzar implementadores más revisores adversariales. Se utilizaron
GPT-6.1 Sol. No hay obligación técnica de continuar con ese proveedor: ahora pidió
Claude. Mantener tareas acotadas, coste prudente y revisión independiente.

Un escritor por modelos/migraciones, archivos declarados antes de editar,
revisores sin escrituras compartidas. Datos sintéticos y HTTP/storage simulados;
para concurrencia, conexiones PostgreSQL reales y bloqueo demostrado, no sólo
esperas o eventos de que un hilo comenzó. No cerrar código por haberlo escrito.

## Reglas de dominio que no se deben perder

El contrato detallado y sus matices están en garage-domain.md.

### Propiedad, identidad y relaciones

Bicis, categorías, items, montajes, perfiles, salidas, lecturas, intervenciones,
fotos y trabajos tienen propietario. Relaciones deben pertenecer al mismo usuario;
también en servicios, formularios y admin, incluso para superusuarios.
UUID ajenos/malformados no dan información de otros usuarios. Propietario inmutable.

Las escrituras autorizadas se serializan por bloqueo del propietario dentro de
transacción. Snapshots de avisos/estadísticas/exportación usan el mismo protocolo.
No hay RLS ni triggers que sustituyan las validaciones entre filas/usuarios.
SQL directo que ignore el protocolo no tiene las mismas garantías.

### Objetos, montajes y material compartido

Un item es un objeto físico, no una categoría. Sustituir una cadena crea otro
objeto. Transferir o remontar conserva UUID, lecturas e historial.

Montajes son intervalos [inicio,fin), con destino XOR bici/objeto padre, posición
exclusiva opcional, sin solapamientos para un objeto ni ciclos temporales.
No imponer unicidad item+bici: A→B→A necesita intervalos repetidos.
Calas pueden montarse en zapatillas; componentes heredan uso de su conjunto una
sola vez. Casco y zapatillas se asignan mediante perfiles, sin montaje obligatorio.

Perfiles general/bici/deporte se combinan; versiones tienen vigencia. Excepciones
de una salida prevalecen y los cambios históricos de perfil requieren corrección
explícita. Retiro/reactivación conserva intervalos de indisponibilidad y no reabre
montajes antiguos. No prorratear un cambio a mitad de salida automáticamente.

### Métricas, instantes y lecturas previas

Metros y segundos exactos; redondear al mostrar. Distancia, movimiento,
temporizador y tiempo transcurrido son distintos. NULL es desconocido, nunca0.
Formularios con zona IANA explícita conservan microsegundos y rechazan horas
ambiguas o inexistentes por DST. Intervalos basados en inicio UTC de cada salida.

UsageBaseline tiene métrica y ámbito lifetime/acquisition/service. Por métrica y
ámbito/evento, escoger última lectura con corte C<=T y sumar sólo contribuciones
[C,T). No sumar todas las lecturas ni volver a contar salidas anteriores al corte.
La fecha civil de compra no sustituye al instante acquisition_anchor_at.

Lectura service pertenece a un evento concreto del mismo item/usuario, no antes
del evento. Lubricar, revisar y sustituir tienen referencias independientes.
Compra, desmontaje o remontaje no reinician mantenimiento. Una lectura estimada
debe permanecer señalada. Un uso observado parcial no prueba histórico completo.

### Salidas, importación y uso materializado

Garage.Ride tiene identidad propia y procedencia por campo; no necesita ID de Strava.
FIT hash+índice de sesión por usuario da idempotencia. Correcciones manuales,
incluidas correccionesNULL, prevalecen; fuentes retiradas no se reactivan por
reimportación automáticamente. No fusionar posibles duplicados por aproximación.

Preview no escribe; ejecución usa manifest inmutable y checkpoint por sesión,
reanudable incluso sin token de preview. No conservar FIT bruto, GPS, salud ni
seriales de sensores. Parser: 15 MiB, 500 000 frames, 100 sesiones; sólo ciclismo propio.
HTTP ejecuta lotes acotados (20 sesiones) para no exigir worker pagado.

ItemUsage es único ride+item, snapshot de inicio/bici/métricas y razones.
Correcciones/borrados y cambios de asignación se materializan atómicamente.
Rebuild idempotente, dry-run sin escrituras, rangos consideran inicio actual
y previo del snapshot. Inicializado significa hechos calculados, no cobertura
del mundo real. No reutilizar hechos obsoletos para afirmar uso o vencimiento.

### Intervenciones, avisos y estadísticas

Tipos privados, eventos XOR item/bici, importes opcionales exactos con moneda ISO,
reglas independientes por tipo/destino y umbrales positivos configurables.
Importe/moneda desconocidos no son coste0 ni permiten sumar monedas.

Avisos: cualquier umbral conocido alcanzado vence; si ninguno vence y falta
cobertura requerida, desconocido. Próximo es >=90%, convención visible.
Calendario son díasUTC de 24 h y continúa desmontado/retirado. Exactcut o intervalo
vacío puede ser completo; parcial observado fiable que supera umbral puede vencer.

Estadísticas separan observado del período [from,to) y totales al corte T.
Filtro de bici/período no reparte baselines. Bicis usan Ride directamente, nunca
suma de componentes. Distribución usa bici histórica y monta A→B→A correctamente.
Períodos de intervenciones se agrupan por mismo destino+tipo, no cualquier evento.
Coste/km requiere distancia completa, positiva, no estimada y costes declarados
conocidos. El subtotal parcial no genera un cociente tranquilizador.
No se calcula ruta completa de ancestros en estadísticas de montajes anidados.

### Fotos privadas y limpieza

WebP hasta 2000 px, sin metadatos. Photo apunta XOR bici/item/evento a un objeto
privado reservado durablemente ANTES del PUT. Quotas de aplicación:250 MiB/usuario
y 4 GiB/proyecto, con bloqueo serializado; no equivalen al consumo real del proveedor.

Sustitución preserva foto vieja si falla nueva. PUT ambiguo/crash requiere limpieza
recuperable con dos DELETE espaciados; no borrar objetos aún referenciados.
S3 recibe configuración explícita, HTTPS/TLS, SigV4 path-style; sin fallback
AWS local, proxies heredados o credenciales predeterminadas. Errores sanitizados.
GET firmado 60 s por defecto, máximo 300; nunca guardarlo en exportaciones/logs.

## Estado y mapa de tareas

Beads contiene28 tareas + 2 epics. Detalles completos y criterios: bd show y
.beads/issues.jsonl. El tablero proyecta esos datos, no otra lista de trabajo.

| Tarea | Estado al relevo | Resultado / pendiente |
|---|---|---|
| garage-000 | En curso | Epic fase inicial |
| garage-001 | Cerrada | Entorno y tests aislados PostgreSQL/HTTP/.env |
| garage-002 | Cerrada | Contrato temporal y dominio revisado |
| garage-003 | Cerrada | Fuentes FIT/manual; límites y legado definidos |
| garage-004 | Cerrada | App y modelos inventario |
| garage-005 | Cerrada | Propiedad, servicios, formularios y permisos |
| garage-006 | Cerrada | Montajes repetibles, posiciones, ciclos/solapamientos |
| garage-007 | Cerrada | Lecturas previas por corte y ámbito |
| garage-008 | Cerrada | Páginas privadas, operaciones y navegador/móvil |
| garage-009 | Cerrada | Procesar fotos y límite2000px |
| garage-010 | En curso | Integración local completa; bucket real pendiente |
| garage-011 | Cerrada | Salidas propias, fuentes, importaciones |
| garage-012 | Cerrada | FIT estricto, muestra original compatible |
| garage-013 | Cerrada N/A | No adaptador Strava para Garage |
| garage-014 | Cerrada | Importación histórica reanudable y asignación por lotes |
| garage-015 | Cerrada | Perfiles, excepciones y retiro histórico |
| garage-016 | Cerrada | Materialización/rebuild sin duplicados |
| garage-017 | Cerrada | Intervenciones, reglas, baselines service y fotos |
| garage-018 | Cerrada | Vencimientos y avisos internos |
| garage-019 | Cerrada | Estadísticas/costes por bici/material/período |
| garage-020 | Cerrada | Exportación JSON/CSV; cerrada por Claude el 11 oct con revisión y suite |
| garage-021 | Cerrada N/A | No cola/reconciliación Strava para Garage |
| garage-022 | Abierta, bloqueada | Integración/acceso; depende de 010 (020 ya cerrada) |
| garage-023 | Abierta, bloqueada | Preparar despliegue/cuotas/reversión; no desplegar |
| garage-024 | Futura | API móvil versionada y sync |
| garage-025 | Futura | Clientes iOS/Android |
| garage-026 | Futura | Servicio comercial, cuentas y planes |
| garage-027 | Futura | Notificaciones fuera de la app |
| garage-028 | Cerrada | Tablero con detalle, DAG, estados y refresco |
| garage-029 | Cerrada | Decisión: Strava como fuente para uso personal (opción B) |
| garage-030 | Aplazada | Sincronizar salidas y bicis desde Strava; empezar sólo cuando el usuario la active |
| garage-031 | En curso | Web instalable para iPhone y Android: implementada y revisada; falta probarla en un teléfono real (HTTPS, garage-023) |
| garage-032 | En curso | 17 oct: el usuario pidió seguir («sigue sigue q es sabado»). Resto de pantallas al estilo B: Taller, formularios en hora local y km/h, ficha de bici, Estadísticas, listas y fechas locales. Sin modelos ni migraciones |
| garage-033 | En curso | 17 oct: «cada componente ha de tener vida útil por tiempo o por km. o el primero de ambos. mejor que probikegarage». Vida útil = regla del tipo «Sustitución» mostrada como «Vida útil»; formulario propio con sugerencias, inicio por defecto y herencia al reemplazar. Sin migraciones |
| garage-100 | Abierta/futura | Epic móvil/comercial |

El cierre de 013/021 NO representa implementación. No reabrirlas sólo porque
falten funciones al explorar el código: es una decisión consciente de fuentes.

## Exportación 020 (cerrada el 11 de octubre de 2026)

JSON garage-export versión1 es autoridad exacta; CSV se distribuye en ZIP por
tablas con manifest. Sin tokens, authUser, legado API, FIT bruto, binarios de fotos,
claves de almacenamiento/jobs o enlaces firmados. FechasUTC con microsegundos, decimales como cadenas,
relaciones con UUID, unidades y presencia NULL de correcciones. Snapshot bloqueo del propietario,
allowlists explícitas, referencias sólo propias. Corrupción rechaza409 genérico.

CSV protege fórmulas (=,+,-,@ tras whitespace y tab/CR inicial), entrecomilla y
conserva saltos de línea; sentinel NULL y apóstrofos impiden restauración exacta.
JSON es referencia para conservar datos. Tablas vacías llevan cabeceras fijas.
Límite100000filas mientras se cargan; no hay límite de bytes para notas grandes (límite
de memoria declarado, no una garantía de rendimiento ilimitado).

Decisión del usuario (11 de octubre de 2026, con Claude): baseline.source es texto
libre del dominio 007 y la exportación v1 incluye **siempre** value, con source
tal cual se escribió. Se descartó la lista anterior de fuentes admitidas
(manual/manual_garmin_reading/garmin/garmin_manual), que omitía el valor de otras
etiquetas: era preventiva y la propuso la IA, no el usuario. Ningún camino de Garage
escribe lecturas desde Strava; sólo el servicio de baselines vía formularios.
Con la lista, una lectura propia etiquetada p. ej. "probikegarage" se exportaba sin
número. La etiqueta no certifica procedencia ni derechos en ningún caso.

Se omiten ItemUsage/initmarker e ImportRun. Rebuild usa asignaciones actuales;
no promete reproducir facts congelados tras correcciones de perfil sin rebuild.
Fuentes FIT retiradas: identidad/metadatos, sin observaciones ni reactivación.
Photo conserva metadatos y ruta relativa autorizado de aplicación, sin binario.
No hay restaurador automático. Revisar detalles en garage-export.md.

## Mapa rápido de código

- garage/models.py y migrations/0001–0008: esquema; no se añadieron migraciones019/020.
- garage/services/ownership.py: propietario, inventario, validación y bloqueo del propietario.
- installations.py, baselines.py, rides.py, usage_profiles.py, usage.py: dominio temporal.
- importers/fit.py y services/import_history.py: archivos propios e importación reanudable.
- services/maintenance.py y maintenance_due.py: intervenciones/reglas/vencimientos.
- services/statistics.py: estadísticas read-only.
- services/export.py: exportación personal versionada (020 cerrada).
- photos.py, storage.py y services/photos.py: transformación, transporte y consistencia.
- views/forms/templates, módulos history/usage/maintenance/statistics/export:
  interfazDjango reutilizando plantillas/autenticación.
- strava_app/settings_test.py, test_support/, conftest.py, manage.py: aislamiento tests.
- tools/garage_progress.py, tests_progress.py: tablero local.
- tools/handoff/: helpers de PostgreSQL preservados para retomar sin /tmp.

Las modificaciones y archivos sin seguimiento son el trabajo entregado. No hay
commits sobre main en esta rama. Conservar todo y verificar antes de editar.
