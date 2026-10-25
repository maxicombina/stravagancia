# Plan de Garage para Stravagancia

Preparar una nueva app Django `garage` para gestionar bicis, componentes y equipamiento personal, con fotos, mantenimiento y estadísticas. Reutilizar Stravagancia y sus servicios actuales, con un objetivo de **0 € adicionales de infraestructura al mes**.

Este documento es el plan de implementación. El trabajo se hace en la rama `garage`, sin commits ni despliegues por ahora. Tras completar garage-001, el usuario ha autorizado continuar con las entregas iniciales usando agentes Sol, pruebas completas y revisión adversarial. Las decisiones propuestas se distinguen de los requisitos ya acordados. Las tareas ejecutables y sus dependencias se mantienen en Beads; véase [GARAGE_TASKS.md](GARAGE_TASKS.md).

## 1 Requisitos acordados

- Varias bicis, componentes, historial de montajes y cambios entre bicis. Un mismo objeto puede montarse y desmontarse repetidamente, también en la misma bici; por ejemplo, alternar dos sillines.
- Categorías editables para poder añadir cualquier clase de material.
- Equipamiento independiente de una bici: casco, zapatillas y calas, entre otros. Un objeto conserva su historial aunque se use en varias bicis.
- Revisiones, intervenciones, intervalos de mantenimiento y avisos.
- Estadísticas de uso por objeto, bici y período, y desde cada intervención.
- Fotos. Reducir el lado mayor a 2000 píxeles cuando lo supere, manteniendo proporciones y sin recortar. Conservar el tamaño de las imágenes pequeñas y guardar el resultado comprimido.
- A corto plazo, completar retroactivamente los datos que faltan, especialmente la bici de cada salida, mediante la fuente de importación que se valide.
- Al dar de alta material usado, introducir fecha de compra, notas y uso previo, por ejemplo el que ya está registrado en Garmin.
- Mantener Python y Django. Añadir una app interna, con las plantillas y la autenticación del proyecto.
- Mantener Neon y el alojamiento actual en sus planes gratuitos.
- Preparar los modelos para varios usuarios desde la primera entrega. A medio plazo, ofrecer apps iOS y Android; a medio o largo plazo, vender el servicio a otros usuarios.

## 2 Base existente y decisiones previas

El proyecto ya tiene actividades, sincronización, webhooks, autenticación, administración y páginas Django. Los puntos que afectan a Garage son:

| Código existente | Consecuencia para el trabajo |
| --- | --- |
| [Activity](strava_integration/models.py) conserva distancia y duración, pero no la bici ni `gear_id` | Hace falta asociar cada salida a una bici y distinguir la asociación importada de una corrección manual |
| [store_activity_from_strava_data](strava_integration/services.py) crea o actualiza por identificador | Conservar la idempotencia y recalcular el uso cuando cambien los datos |
| [Webhooks](strava_integration/views.py) descargan la actividad antes de responder y capturan errores devolviendo OK | Registrar trabajo pendiente y errores para poder recuperarlos |
| La detección de actividades pendientes usa una fecha de corte | No sirve por sí sola para corregir cambios o huecos anteriores |
| [Configuración](strava_app/settings.py) usa Neon y WhiteNoise | Los archivos subidos necesitan almacenamiento persistente separado de los estáticos |

### Contexto confirmado en la base de datos

Consulta de solo lectura en la consola de Neon el 4 de octubre de 2026, sobre la rama `production` y la base `neondb`. No se modificaron registros ni se descargaron actividades o datos personales.

| Comprobación | Resultado |
| --- | --- |
| Actividades almacenadas | 346 |
| Atletas | 1 |
| Usuarios Django | 2 |
| Registros de `MissingActivity` | 304, todos marcados como cargados; ninguno pendiente |
| Migraciones de `strava_integration` aplicadas | 7 |
| PostgreSQL | 18.6 |
| `Activity.strava_id` | Obligatorio |
| Tablas de integración | `activity`, `athlete`, `missingactivity` |

El modelo actual no vincula `Athlete` con un usuario Django. No asumir que el primer atleta o el primer usuario es el propietario correcto. El contador de pendientes a cero tampoco demuestra que el histórico esté completo ni que sus datos estén actualizados.

Esto confirma dos necesidades: un vínculo explícito entre usuario y cuenta externa, y una identidad de salida que permita importar datos propios sin exigir un identificador de Strava. La inspección inicial desde el terminal no pudo conectar; la consola sí permitió estas consultas. Los futuros agentes tienen autorización para inspeccionar la base si hace falta, mediante consultas de lectura; las pruebas y migraciones se ejecutarán en entornos aislados.

### Fuente del histórico de salidas

Hay una dependencia que resolver antes de ampliar el histórico importado. La política de Strava vigente desde junio de 2026 limita la caché a siete días y restringe almacenamiento persistente, análisis y datos derivados. No asumir que conservar únicamente totales resuelve esas restricciones. Revisar su aplicación concreta al uso personal previsto y documentar la fuente admitida antes de conectar contadores permanentes a la API. [Política de Strava, apartados 5 y 6](https://www.strava.com/legal/api_policy).

Propuesta técnica: hacer que el cálculo de uso acepte una salida normalizada con procedencia identificada. Si la API no permite el histórico necesario, usar archivos propios del Garmin, importados por el usuario, para ese histórico. Validar primero la importación de un archivo de ejemplo. No dar por disponible una API gratuita de Garmin ni asumir que sus archivos contienen la bici o el historial de equipamiento. Las lecturas de uso previo de Garmin se pueden introducir manualmente.

El inventario, las fotos, los montajes y las intervenciones manuales son independientes de esta decisión. El motor de uso también puede desarrollarse con datos sintéticos. La decisión bloquea las importaciones reales y las funciones que dependan de ellas, no todo Garage. No modificar ni eliminar los datos existentes como parte de este plan.

La monetización obliga además a validar el uso comercial y las restricciones sobre servicios cobrados vinculados a la API. La excepción para funcionalidad propia no equivale a permiso general para vender análisis basados en esos datos. No prometer esa integración como base comercial antes de cerrar esta cuestión. [Política de Strava, apartado 5.8](https://www.strava.com/legal/api_policy).

### Almacenamiento y coste

Neon Free ofrece actualmente **1 GB de PostgreSQL y 5 GB de Object Storage por proyecto**. El aumento del 2 de octubre corresponde a PostgreSQL. [Anuncio de Neon](https://neon.com/blog/neon-free-plan-1-gb-per-project).

La revisión de la consola del proyecto `stravagancia` confirmó el plan Free, región Frankfurt y acceso a Object Storage; todavía no hay un bucket. Propuesta: bucket privado compatible con S3, claves en variables de entorno del servidor y únicamente referencias a los objetos en PostgreSQL.

Render Free tiene disco efímero y puede suspenderse por inactividad. Los archivos persistentes irán a Neon; los avisos iniciales aparecerán dentro de la app. Comprobar límites de transferencia y configuración de gasto antes del despliegue para mantener el objetivo de coste. [Render Free](https://render.com/docs/free).

## 3 Modelo y reglas de uso

Los nombres siguientes son propuestas para cerrar antes de generar migraciones.

| Entidad | Responsabilidad |
| --- | --- |
| `Bike` | Bici física, estado y vínculo opcional con una bici de Strava |
| `Category` | Categoría editable de material |
| `Item` | Objeto físico individual, categoría, fecha de compra, uso inicial conocido y estado activo o retirado |
| `UsageBaseline` | Lectura de uso previo con fecha de referencia, unidades, procedencia y notas |
| `Installation` | Un período de montaje de un objeto en una bici o en otro objeto, con posición opcional; admite tantos períodos separados como sean necesarios, incluso con el mismo destino |
| `UsageProfile` | Material habitual por bici y modalidad, con fechas de vigencia |
| `Ride` | Salida normalizada de Garage, con propietario, identidad propia, fecha, bici, distancia y tiempo; independiente de tener identificador de Strava |
| `ExternalConnection`, `ActivitySource` | Cuenta externa de un usuario, vínculo de una salida con sus fuentes y procedencia de los campos completados desde ellas |
| `ImportRun` | Período solicitado, progreso, incidencias y resultado de una importación o reconciliación |
| `UsageOverride` | Inclusión o exclusión manual de material en una salida |
| `ItemUsage` | Uso efectivo de un objeto en una salida, recalculable y único para ese par |
| `ServiceType`, `MaintenanceRule`, `ServiceEvent` | Tipo de intervención, intervalos y operaciones realizadas |
| `Photo` | Referencia al archivo, dimensiones y vínculo con bici, objeto o intervención |

Reglas esenciales:

1. Un objeto es una unidad física. Sustituir una cadena crea otro objeto; moverla de bici conserva su historial.
2. Un montaje tiene un único destino y no se solapa con otro montaje del mismo objeto. Los intervalos incluyen el inicio y excluyen el final. Impedir ciclos entre objetos.
   Un objeto puede tener muchos períodos de montaje en la misma bici: no imponer unicidad al par objeto y destino. Desmontarlo cierra el período vigente; volver a montarlo abre otro, conservando los anteriores. Durante el tiempo desmontado no acumula uso por salidas de esa bici, aunque sus intervalos de mantenimiento por calendario siguen transcurriendo.
   Cuando haya una posición exclusiva, como sillín principal o rueda delantera, tampoco se pueden solapar dos objetos en esa posición. No imponer exclusividad por categoría: una bici puede tener rueda delantera y trasera. Sustituir el objeto de una posición cierra un período y abre otro en una misma transacción.
3. Permitir calas montadas en zapatillas y componentes montados en conjuntos, como ruedas. El uso de un conjunto se propaga a sus componentes vigentes una sola vez.
4. El casco o las zapatillas se asignan mediante perfiles habituales, aunque no estén montados en ninguna bici. La excepción manual de una salida prevalece sobre esos perfiles.
5. Cambiar un perfil habitual afecta a salidas futuras; recalcular un período histórico requiere una acción explícita y conserva las excepciones manuales.
6. Contar distancia en metros y tiempo en segundos; redondear al mostrar. Utilizar tiempo en movimiento para los intervalos por horas.
7. Repetir una importación no suma uso de nuevo. Editar distancia, fecha o bici, o borrar una salida, recalcula los objetos afectados de forma transaccional.
8. Separar uso de toda la vida, uso desde la adquisición y uso desde cada tipo de intervención. Lubricar no reinicia el intervalo de sustitución.
9. No inventar montajes históricos ni asignar una bici por defecto cuando se desconozca. Mostrar la cobertura del histórico y permitir introducir valores iniciales estimados.
10. El uso previo tiene un instante de corte: si unas zapatillas llevaban 1000 km al comenzar el 1 de enero, la lectura cubre las salidas anteriores a ese instante y se suma únicamente el uso de salidas que empiecen a partir de él. Importar salidas anteriores no añade esos kilómetros otra vez. La fecha de compra y la fecha de esa lectura pueden ser distintas. Cada métrica tiene su propia lectura; desconocer las horas no equivale a cero horas. Para fechas anteriores al corte, mostrar solo el uso histórico observado y su cobertura, sin inventar totales anteriores ni reinicios de mantenimiento.
11. Vincular bicis, material, categorías propias, salidas, intervenciones, fotos e importaciones al usuario. Validar también que los objetos relacionados pertenecen al mismo usuario.
12. Los vínculos e identificadores externos se resuelven dentro de la cuenta conectada y su propietario. Conservar procedencia por fuente y campo para reconciliar sin duplicados: una salida de un archivo propio no convierte automáticamente en datos propios los campos rellenados desde una API. Documentar qué fuente prevalece y cómo se trata su retirada; conservar las correcciones manuales.

Para los montajes y lecturas de uso, tomar como referencia el inicio de la salida, almacenado en UTC. El formulario interpreta las fechas en la zona horaria del usuario. La inferencia inicial supone cambios de material entre salidas; no prorratea automáticamente una sustitución a mitad de una salida.

Ejemplo obligatorio: montar el sillín A, sustituirlo por B y después volver a montar A. A conserva un único registro de objeto con dos períodos de montaje y suma el uso de ambos. B acumula únicamente el uso de su período. Cada salida se asigna según el montaje vigente en su fecha; los cambios no reinician el uso de toda la vida ni los contadores desde una intervención.

### Preparación para varios usuarios y aplicaciones móviles

Usar `settings.AUTH_USER_MODEL` como propietario desde las primeras migraciones. Aprovechar la autenticación existente y añadir el vínculo con las cuentas externas. No migrar a un modelo de usuario personalizado salvo necesidad concreta.

Separar importación, cálculo de uso y mantenimiento de las vistas HTML. La web llama a esos servicios; una futura API hará lo mismo. Usar identificadores UUID estables para los nuevos recursos que se expondrán a clientes móviles, fechas con zona horaria y errores de validación consistentes.

Las consultas, archivos, trabajos pendientes y cachés deben quedar acotados por usuario. Añadir pruebas con dos usuarios desde el principio. Las credenciales personales actuales en variables globales no sirven para conectar cuentas de futuros clientes: el paso a conexiones por usuario tendrá almacenamiento protegido de tokens y una gestión de autorización y revocación propia.

La API pública, el registro abierto, la aplicación móvil y los cobros se implementarán después. El esquema y la lógica de dominio deben permitirlos sin convertir ahora el proyecto en una plataforma con organizaciones o equipos.

## 4 Entregas de implementación

### Entrega 0 Preparación y decisiones independientes

- Preparar configuración de pruebas con PostgreSQL local y llamadas externas simuladas.
- Comprobar que las pruebas nunca toman `DATABASE_URL` de producción. El README indica que el servicio Django de Docker puede conectar a Neon; arrancar únicamente PostgreSQL para las pruebas locales.
- Ejecutar la batería existente como referencia.
- Cerrar la decisión sobre procedencia y conservación de las salidas; validar un archivo Garmin si esa es la fuente elegida. Mantener `Ride` independiente de la API.
- Documentar la representación de fechas y resolver explícitamente la asociación de los datos existentes con su usuario, sin elegir el primer registro automáticamente.
- Diseñar importaciones por período con previsualización, progreso, reanudación e incidencias. Diferenciar salidas ausentes de campos ausentes en salidas ya cargadas.

**Criterios separados:** el inventario puede empezar cuando el entorno de pruebas esté aislado y el esquema esté revisado. Las importaciones reales pueden empezar cuando se valide la fuente y su conservación. La definición de la fuente no bloquea la primera condición.

### Entrega 1 Inventario y montajes

- Crear `garage`, sus URLs bajo `/garage/`, modelos iniciales y administración.
- Añadir páginas privadas para listar, crear y editar bicis, categorías y material.
- Registrar montajes, retiradas, transferencias y relaciones como calas sobre zapatillas. Permitir volver a montar un objeto previamente desmontado, en la misma bici o en otra, consultando todos sus períodos anteriores.
- Permitir material sin bici y archivo de objetos retirados.
- Formulario de alta de material usado: fecha de compra, notas, kilómetros, horas o salidas previas conocidas y fecha de referencia. Permitir indicar Garmin como procedencia de una lectura introducida manualmente.
- Establecer propietario y restricciones entre usuarios desde estas migraciones.

**Terminada cuando:** se pueden gestionar dos bicis, mover un componente, alternar dos sillines con la secuencia A → B → A y registrar casco, zapatillas y calas conservando el historial de cada objeto.

### Entrega 2 Fotos

- Añadir Pillow y un cliente S3 compatible, tras comprobar versiones y soporte en la imagen Docker.
- Procesar orientación antes del reescalado. Guardar WebP con calidad 85 como punto de partida, ajustándola con ejemplos reales.
- Ejemplo obligatorio: 4000 × 3000 pasa a 2000 × 1500; una foto de 1200 × 800 mantiene sus dimensiones.
- Limitar tamaño de entrada y memoria de decodificación; comprobar el contenido del archivo. Empezar con JPEG, PNG y WebP estáticos y mostrar errores claros para otros formatos; HEIC queda pendiente de evaluar. Aplicar orientación antes de eliminar metadatos EXIF innecesarios.
- Guardar en bucket privado y autorizar el acceso antes de emitir enlaces temporales. Limpiar archivos huérfanos si falla el guardado o se elimina una foto.
- En desarrollo y pruebas usar almacenamiento local aislado o simulado. Configurar Neon al validar la integración externa.

**Criterios separados:** el procesamiento y acceso se verifican con almacenamiento local o simulado; la conexión externa se verifica después con un bucket privado autorizado y archivos de prueba. Para dar por completa la entrega, comprobar persistencia externa y manejo de fallos, sin confiar solo en un backend simulado.

### Entrega 3 Salidas y contadores

- Implementar el adaptador de la fuente acordada y el vínculo de cada salida con su bici.
- Si se utiliza la API, conservar `gear_id` según la política definida y permitir una corrección manual que la sincronización no sobrescriba.
- Completar retroactivamente los campos del histórico mediante importación o reconciliación por períodos. Las 346 actividades son una referencia del volumen observado, no una obligación de copiar datos de la API sin haber validado ese uso.
- Buscar también salidas que falten antes de la fecha de corte actual. Mostrar qué se añadirá o corregirá antes de aplicar cambios.
- Reimportar de Strava únicamente si se valida ese uso. Para archivos propios del Garmin, usar información de bici cuando exista y permitir asignarla por lotes cuando el archivo no la incluya.
- Conservar excepciones manuales, detectar posibles duplicados entre fuentes y pedir revisión cuando la coincidencia sea ambigua; no fusionar solo por proximidad de fecha.
- Añadir perfiles habituales por bici y modalidad, y correcciones de material por salida.
- Implementar el cálculo de uso y un comando de reconstrucción por período, con previsualización y ejecución reanudable.
- Ofrecer una lista de salidas pendientes de asignación y mostrar desde qué fecha el uso es fiable.

La documentación de webhooks solo enumera actualizaciones de título, tipo y privacidad; no promete un evento al cambiar la bici. Si se mantiene esa integración, incluir reconciliación acotada y actualización manual. Registrar eventos antes de responder y procesarlos fuera de la petición, con reintentos persistentes. [Webhooks de Strava](https://developers.strava.com/docs/webhooks/).

Propuesta sin un worker de pago: cola en PostgreSQL, comando de procesamiento y ejecución de lotes mediante el mecanismo gratuito de cron ya utilizado, verificando sus límites. Los arranques en frío de Render hacen necesaria la reconciliación aunque exista esa cola.

**Terminada cuando:** el histórico se puede completar por lotes reanudables; una salida cuenta una sola vez para cada objeto; las correcciones y los borrados producen los totales esperados; una bici desconocida queda pendiente y las lecturas de uso previo no duplican kilómetros.

### Entrega 4 Mantenimiento y avisos

- Registrar intervenciones con fecha, notas, objetos afectados, fotos y coste opcional.
- Una intervención afecta a objetos concretos; conservar su lectura de uso cuando se conoce. Si falta el histórico necesario para calcular un intervalo por uso, mostrarlo como desconocido. Registrar costes con importe decimal y moneda; no sumar monedas distintas sin conversión definida.
- Configurar intervalos por kilómetros, horas, número de salidas o tiempo transcurrido.
- Para reglas combinadas, avisar cuando se alcance cualquiera de sus umbrales.
- Mostrar estado vigente, próximo o vencido y lo que falta para cada intervención.
- Avisos iniciales en el panel al abrir la app. Notificaciones fuera de la app quedan como una entrega posterior con canal y ejecución definidos.

**Terminada cuando:** registrar una lubricación actualiza su próximo aviso y conserva tanto la vida total de la cadena como la regla independiente de sustitución.

### Entrega 5 Estadísticas y uso diario

- Panel de bicis y material con kilómetros, horas y salidas por período.
- Historial de un objeto entre distintas bicis y distribución de su uso.
- Comparación de períodos entre intervenciones y costes por kilómetro cuando haya datos suficientes.
- Filtros por bici, categoría, objeto y fechas; indicar valores estimados e histórico incompleto.
- Páginas adaptadas al móvil, usando plantillas Django y las convenciones visuales existentes.
- Exportación del inventario y del historial propio para conservar una copia independiente.

**Terminada cuando:** se puede revisar una salida, corregir su material, registrar una intervención y consultar su efecto en contadores y estadísticas desde el móvil.

### Entrega 6 Validación y preparación del despliegue

- Ejecutar pruebas relevantes, revisión de migraciones y comprobaciones de Django en un entorno aislado.
- Comprobar regresiones en sincronización, páginas y administración existentes.
- Probar almacenamiento externo con archivos de prueba, revisar cuotas y documentar variables de entorno sin valores secretos.
- Preparar la migración y reversión del despliegue. El repositorio despliega al actualizar `main`: no hacer push ni desplegar durante esta preparación.

## 5 Pruebas que deben proteger el comportamiento

- Casco utilizado en dos bicis: acumula ambas salidas sin duplicarlas.
- Componente transferido y montaje exactamente en el límite de un intervalo.
- Dos ruedas en posiciones distintas, y sustitución en una posición exclusiva sin solapamientos.
- Sillines A → B → A en la misma bici: dos períodos para A, uno para B, sin duplicar objetos ni sumar uso cuando están desmontados. Recalcular el histórico conserva esos resultados y los contadores de mantenimiento.
- Calas y zapatillas: propagación de uso sin ciclos ni doble contabilización.
- Importación repetida, distancia corregida, bici corregida y salida eliminada.
- Corrección manual que sobrevive a una sincronización y a cambios en perfiles habituales.
- Bici desconocida, actividad que cambia a un tipo excluido y recuperación tras un fallo de importación.
- Dos reglas de mantenimiento sobre el mismo objeto con reinicios independientes.
- Material con uso previo: importar antes y después de su fecha de referencia conserva el total correcto.
- Una salida exactamente en el instante de corte, fecha local convertida a UTC y métrica previa desconocida; no convertir desconocido en cero.
- Importación histórica interrumpida y reanudada; dos fuentes para una salida y coincidencias ambiguas.
- Fotos horizontales, verticales, pequeñas y con orientación EXIF; fallo de almacenamiento sin referencia rota ni archivo huérfano.
- Dos usuarios sin acceso cruzado a inventario, salidas, fotos, trabajos de importación o cachés; rechazar relaciones entre objetos de propietarios distintos.

## 6 Trabajo con un agente más ligero

Modelo autorizado actualmente por el usuario: **GPT-6.1 Sol** para implementación y revisión adversarial. Dividir el trabajo por tareas de Beads y revisar modelos, migraciones y cálculos antes de avanzar.

El ahorro depende del trabajo y de las repeticiones necesarias. Separar entregas facilita dar instrucciones precisas y revisar resultados antes de continuar.

Cada encargo al implementador debe incluir:

- Una entrega o parte pequeña de ella, con archivos afectados y resultado observable.
- Las reglas de dominio aplicables y casos de prueba que debe satisfacer.
- Revisión previa del código que toca y respeto por cambios locales de otros autores.
- Puede consultar el esquema y recuentos de Neon en lectura si necesita contexto. Ejecutar pruebas, migraciones y modificaciones en entornos aislados; simular llamadas a Strava y utilizar datos sintéticos.
- Prohibición de commits, pushes, despliegues y cambios de infraestructura durante esta etapa.
- Al terminar, archivos modificados, comprobaciones realizadas y cuestiones pendientes.

Trabajar con un implementador por entrega, evitando ediciones simultáneas de modelos y migraciones. Revisar el resultado antes de encargar la siguiente. El coordinador asigna las tareas autorizadas a subagentes Sol y mantiene actualizado Beads.

**Estado de ejecución:** entorno de pruebas, contrato de dominio, decisión de fuentes, inventario, permisos, montajes, lecturas previas y procesamiento de fotos completados. También están completadas las páginas privadas de inventario y los modelos de salidas propias. El importador FIT y los perfiles y excepciones por salida también están completados, con 1158 pruebas y 12 subcasos pasando. Continúan la interfaz de importación del histórico y el motor de contadores. El motor de contadores se prueba con datos sintéticos; la muestra FIT real se usa únicamente para validar compatibilidad local.

## 7 Evolución a medio y largo plazo

**Apps iOS y Android:** ofrecer una API versionada para el mismo dominio y elegir después la tecnología móvil. Definir autenticación para móviles, sincronización reanudable, resolución de cambios concurrentes y subida de fotos. Valorar notificaciones push en esa entrega. La separación de servicios y los identificadores estables se preparan ahora; la API y las apps completas quedan fuera de las entregas iniciales.

**Venta a otros usuarios:** añadir registro y conexión de cuentas individuales, recuperación de acceso, exportación y borrado por usuario, planes, límites de uso y facturación mediante un proveedor. Mantener los derechos de cada plan separados de los objetos del inventario; no añadir ahora reglas de pago a cada modelo.

Antes de abrir el servicio comercial, validar condiciones de las fuentes externas, costes por usuario y capacidad del alojamiento. El objetivo de 0 € adicionales corresponde a la fase personal inicial dentro de las cuotas gratuitas; el plan no presupone que un servicio comercial creciente pueda operar gratis indefinidamente.

## Precisión de tiempos comprobada durante la implementación

La muestra FIT autorizada contiene milisegundos. El contrato de dominio conserva
duración en segundos con tres decimales y aritmética Decimal en salidas, lecturas
previas y mantenimiento. El número de salidas sigue siendo entero. Los cambios
son para Garage y no alteran las tablas de Stravagancia existentes.
