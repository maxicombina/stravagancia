# Dominio Garage: esquema y reglas temporales

Diseño de `garage-002`, 4 de octubre de 2026. **Contrato de implementación revisado adversarialmente y aprobado para las tareas dependientes**, sin modelos ni migraciones generados. Las decisiones siguientes concretan el [plan](../GARAGE_PLAN.md); han sido revisadas como contrato de las tareas dependientes. La decisión de fuentes de `garage-003` se documenta independientemente en [garage-data-sources.md](garage-data-sources.md): archivos propios/manual para Garage duradero; adaptador Strava descartado para ese fin, legado intacto.

## 1. Base real y límites

`strava_integration.models.Activity` tiene PK entera, `strava_id` obligatorio y globalmente único, FK a `Athlete`, distancia `float`, fechas y duración. No contiene bici ni propietario Django. `Athlete` tampoco tiene propietario. `store_activity_from_strava_data` hace `update_or_create(strava_id=...)` y puede elegir `Athlete.objects.first()`: **no reutilizar ese fallback en Garage**. No deducir propietarios de los registros existentes ni migrarlos automáticamente.

El proyecto declara Django >=5.2.7, usa `USE_TZ=True`, `TIME_ZONE='UTC'` y `BigAutoField` por defecto. Garage conserva autenticación existente y usa `settings.AUTH_USER_MODEL`; no crea otro usuario. La referencia de pruebas es PostgreSQL 18.6 aislado, 144 tests existentes aprobados en `garage-001`. Esta tarea revisa documentos y código, sin ejecutar BD, pytest ni acceder a producción o `.env`.

## 2. Convenciones y propiedad

Todos los recursos nuevos persistentes tienen `id UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`, `owner FK(settings.AUTH_USER_MODEL, CASCADE)`, `created_at` y `updated_at`. UUID estable, nunca derivado del proveedor externo. El cliente móvil futuro podrá enviar UUID para crear con idempotencia; hoy los genera el servidor. UUID no concede autorización.

Cada servicio recibe usuario y resuelve primero por `(owner, id)`, incluso en administración, jobs, formularios y fotos. `owner` es inmutable; no existe transferencia entre usuarios. Las relaciones deben tener el mismo propietario. Un FK ordinario no garantiza esa igualdad: validación explícita en servicios y `clean()`; no confiar en que `save()` llame a `full_clean()`. Admin usa los mismos servicios y acota queryset, campos relacionados y acciones al usuario autenticado, también si es superuser; owner se asigna del actor, no es un selector editable. Una herramienta futura de soporte sobre inventario ajeno requerirá alcance explícito, fuera de esta entrega. No ofrecer escritura directa de estas tablas mediante `bulk_create`, `QuerySet.update` o SQL ad hoc. La materialización interna de ItemUsage puede agrupar escrituras dentro del servicio autorizado, con propietario bloqueado, salidas canónicas y referencias obtenidas del resolver; no expone un método de inserción masiva al cliente. Los constraints de una fila y exclusiones descritos abajo sí protegen SQL directo; propiedad cruzada y ciclos requieren la ruta de servicios autorizada en esta entrega. Cubrir esa frontera con pruebas. No introducir ahora RLS, triggers o un framework de repositorios.

Eliminar físicamente usuario se hará mediante un servicio futuro de borrado que ordene dependencias y archivos; `CASCADE` en owner no sustituye ese trabajo. Archivar material es la operación ordinaria. FKs de historial a inventario usan `PROTECT` para impedir borrado accidental. No borrar montajes al retirar un objeto.

Instantes en UTC con zona horaria. La interfaz interpreta fecha/hora en la zona IANA elegida por el usuario; una fecha sin hora significa medianoche local. Hasta tener preferencias persistentes, el formulario pide zona con valor inicial UTC explícito, nunca deduce Madrid del servidor. Horas locales inexistentes o ambiguas por DST requieren corrección/desambiguación, sin conversión silenciosa. El inicio de la salida determina todo su material; no hay prorrateo a mitad de salida.

## 3. Inventario concreto (garage-004/005)

Campos comunes anteriores omitidos en la tabla. `blank` para texto vacío, `NULL` para ausencia de fecha, número o relación. Longitudes indicadas son límites iniciales; no interpretar nombre como identidad única.

| Modelo | Campos propios | Invariantes |
| --- | --- | --- |
| `Category` | `name varchar(100)`, `notes text=''`, `is_archived bool=False`, `icon varchar(32)=''` (garage-041, migración 0011) | Nombre recortado no vacío; único por propietario sin distinguir mayúsculas (`owner, Lower(name)`). Renombrar no cambia montajes. Categorías propias, sin fila global compartida. `icon`: CHECK `icon = '' OR icon ~ '^[a-z_]+$'` (sólo la forma, la lista puede crecer sin migración); `Category.clean()` exige una clave de `garage/icons.py` (`ICON_CHOICES`). `''` significa «según el nombre»: no se guarda ninguna sugerencia, se deduce cada vez. Precedencia del icono de un objeto (`item_icon_key`): icono de su categoría si es una clave vigente; si no, el que sugiere el nombre del objeto, después el de la categoría y, por último, «pieza». Deducción: sin acentos ni mayúsculas, palabras clave completas (con plural: «Cadenas», «Pedales»; nunca «cambio» dentro de «Recambios»); gana la escrita antes (el núcleo: «Llave de cadena» es herramienta) y, a igual posición, la más larga («Horquilla de suspensión»). Una clave que ya no esté en la lista se trata como `''`. |
| `Bike` | `name varchar(150)`, `brand/model varchar(150)=''`, `serial_number varchar(150)=''`, `acquired_on date NULL`, `acquisition_anchor_at timestamptz NULL`, `retired_at timestamptz NULL`, `notes text=''`, `purchase_amount decimal(12,2) NULL`, `purchase_currency char(3) NULL` | Nombre no vacío; precio >=0; precio y moneda ambos presentes o ausentes. No imponer unicidad de nombre o número de serie. |
| `Item` | Igual que Bike, más `category FK Category PROTECT` | Un registro es una unidad física, incluido un conjunto (rueda, zapatilla). Sustitución física crea otro UUID. Categoría del mismo owner. |

Estado activo/retirado se deriva de `retired_at`, sin segundo booleano contradictorio. Retirar un item o bici cierra sus montajes abiertos en el mismo instante y transacción; retirar un destino item cierra además sus hijos directos, que quedan desmontados. Rechazar retiros que dejen montajes posteriores a `retired_at`; una corrección retroactiva debe corregirlos en la misma operación. También al crear/editar Installation, exigir `started_at < retired_at` y `ended_at <= retired_at` para item y destino si están retirados; no admitir período abierto sobre un retiro conocido. Retiro exactamente en el inicio generaría intervalo vacío y se rechaza: corregir/eliminar explícitamente el registro erróneo antes, sin truncar silenciosamente historia. No bloquear consultas o uso histórico anterior al retiro. Reactivar cierra el retiro guardando su intervalo de inactividad y limpia el retiro actual, sin reabrir montajes; el período inactivo sigue excluido al consultar el pasado (detalle en sección 11). La fecha de adquisición no restringe el historial: se puede documentar uso anterior y corregir compra después.

Dinero: decimal, moneda ISO 4217 validada en formulario/servicio, sin conversión automática ni suma de distintas monedas. No guardar `money` de PostgreSQL ni floats. Fecha de compra es dato civil, no instante de reinicio. La adquisición de usado **no reinicia** vida ni intervenciones.

No añadir `strava_gear_id` suelto a Bike. El vínculo externo se bosqueja en sección 7 y pertenece a una conexión de un usuario; no participa en identidad del inventario. No usar FK a `Activity` para contadores.

## 4. Installation: historial, posición y concurrencia (garage-006)

Campos: `item FK Item PROTECT`, `bike FK Bike PROTECT NULL`, `parent_item FK Item PROTECT NULL`, `slot varchar(80) NULL`, `started_at timestamptz`, `ended_at timestamptz NULL`, `notes text=''`, más campos comunes. `NULL` final significa intervalo abierto hasta infinito. El destino es **exactamente uno** de bike/parent_item. `slot=NULL` significa colocación sin exclusividad; cadena vacía se normaliza a NULL. Un valor de slot significa posición exclusiva en ese destino, nunca exclusividad de categoría.

No hace falta entidad Slot en esta entrega. Validar claves canónicas en minúsculas ASCII (`[a-z0-9_]+`, longitud <=80) y ofrecer presets, por ejemplo `front_wheel`, `rear_wheel`, `main_saddle`. Los nombres visibles pueden traducirse. No crear variantes de una misma posición por mayúsculas o espacios. La identidad exclusiva es `(tipo de destino, UUID destino, slot)`. Dos posiciones distintas de la categoría ruedas son válidas. Un conjunto puede tener, por ejemplo, un neumático en `tyre` y un disco en `brake_disc`.

Invariantes SQL:

- CHECK XOR de destinos; `parent_item_id != item_id` si presente.
- CHECK `ended_at IS NULL OR ended_at > started_at`: sin períodos vacíos ni negativos.
- CHECK slot NULL o clave canónica no vacía.
- Tres exclusiones GiST inmediatas, usando `tstzrange(started_at, ended_at, '[)')`: `(item_id WITH =, rango WITH &&)` para cualquier montaje; `(bike_id WITH =, slot WITH =, rango WITH &&) WHERE bike_id IS NOT NULL AND slot IS NOT NULL`; equivalente para `parent_item_id`.

No agregar UNIQUE `(item,destino)` ni UNIQUE `slot` global. UUIDs globalmente únicos permiten omitir owner de las exclusiones. Intervalos adyacentes no se solapan: a las 10:00 el período que termina deja de estar vigente y el que empieza ya lo está. Las exclusiones cubren pasado, futuro y períodos abiertos, también frente a dos transacciones simultáneas. Son implementables con `ExclusionConstraint`, `TsTzRange(Func)` y `RangeBoundary(inclusive_lower=True, inclusive_upper=False)` (también su valor por defecto); no duplicar un rango almacenado y dos fechas. [Django 5.2, constraints PostgreSQL](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/constraints/).

`btree_gist` aporta igualdad GiST para UUID/texto y es extensión trusted instalable por un rol con CREATE sobre la BD. Una migración `BtreeGistExtension` debe preceder las exclusiones. Antes de implementar, comprobar en **BD aislada** disponibilidad en `pg_available_extensions`, instalación en `pg_extension` y privilegio CREATE del rol migrador. No inferirlo por ser PostgreSQL 18.6 ni exigir superusuario al rol de runtime. Si no está instalada y el migrador carece del permiso, bloquear esa migración y preparar instalación por el administrador en la futura fase de despliegue; **no degradar a clean() sin constraint**. No instalar nada en Neon en esta tarea. [PostgreSQL 18, btree_gist](https://www.postgresql.org/docs/18/btree-gist.html), [CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html).

### Transacciones y grafo temporal

Todas las escrituras de montajes (crear, editar, cerrar, sustituir, transferir, retirar) se hacen en `transaction.atomic()`. Adquirir primero `select_for_update()` sobre la fila del **propietario**; después leer/validar/escribir. Este bloqueo grueso serializa cambios de inventario temporal de un mismo usuario y evita carreras de ciclos incluso cuando no existía ninguna instalación que bloquear. Es suficiente para la fase personal y dos usuarios siguen siendo independientes. No bloquear solamente los montajes existentes. Operaciones de varias personas no existen; orden del bloqueo siempre owner primero.

Sustituir cierra el período saliente en T y luego inserta el entrante en T. Transferir cierra el del mismo item y abre otro destino. Si hay historial posterior, validar todos los intervalos, sin alargar hasta infinito por defecto. Un error revierte toda la operación, incluida retirada. Atrapar `IntegrityError` fuera del bloque atomic y traducir constraint por nombre a errores consistentes (`installation_overlap`, `slot_occupied`, etc.); no continuar dentro de una transacción rota. Exclusiones inmediatas evitan tener que diferir constraints parciales.

Para proponer una arista hijo X → padre Y vigente en I, recorrer desde Y los vínculos `item → parent_item`. En cada paso intersectar el intervalo acumulado con el de esa arista y descartar si queda vacío. Si se alcanza X con intersección no vacía, rechazar ciclo. En una edición, excluir la versión antigua antes de evaluar la candidata; cambios por lote se validan contra el grafo final del lote bajo el bloqueo. No basta comprobar ancestros actuales, ni cada arista por separado solapada con I: debe existir **un instante común a todo el camino**. Un ciclo histórico sin coincidencia temporal es válido. Ejemplo: X→Y en [1 ene, 2 ene) y Y→X en [2 ene, 3 ene) no forman ciclo; si Y→X empieza el 1 ene a las 12:00, sí. Dos escrituras concurrentes X→Y/Y→X son serializadas por owner y la segunda rechazada.

Los hijos permanecen físicamente montados en un conjunto mientras éste está desmontado de bici; conservan Installation pero no acumulan uso por bici. En una salida se resuelven raíces montadas en Bike y objetos de perfil, se recorren hijos vigentes en el inicio y se forma un **set de UUID**. Cada objeto aparece una vez aunque se alcance por varios caminos.

## 5. UsageBaseline: lecturas, cortes y desconocidos (garage-007)

Un baseline es una lectura acumulada **inmediatamente antes** de un corte C, independiente del inventario de salidas. Campos: `item FK Item PROTECT`, `metric varchar` (`distance_m`, `moving_time_s`, `ride_count`), `scope varchar` (`lifetime`, `acquisition`, `service`), `cut_at timestamptz`, `value decimal(20,3)`, `source varchar(80)` (p. ej. `manual`, `manual_garmin_reading`), `is_estimated bool=False`, `notes text=''`, `service_event FK ServiceEvent PROTECT NULL` cuando exista mantenimiento, más campos comunes.

garage-007 implementó scopes lifetime/acquisition; garage-017 añade service con su FK y CHECK (service exige evento del mismo item/owner; otros scopes exigen FK NULL). Una lectura acquisition requiere `Item.acquisition_anchor_at` y un corte no anterior a esa ancla; un corte service no puede anteceder `performed_at`. Las lecturas siguen perteneciendo a items; las intervenciones sobre una bici no admiten lecturas de un item distinto como sustituto.

CHECK valor >=0 y finito; solo el número de salidas exige valor entero, mientras distancia y segundos conservan hasta tres decimales; corte obligatorio. Una fila por `(item, metric, scope, cut_at)` en scopes lifetime/acquisition; para service la unicidad incluye `service_event`. Correcciones de la misma lectura actualizan esa fila, no se añaden. El servicio permite corregir por la misma clave conservando UUID; el formulario de alta rechaza una clave existente y exige abrir su edición explícita para corregirla. No exigir monotonía entre lecturas: una corrección/estimación puede bajar; mostrar procedencia y estimación. No sumar lecturas entre sí. La ausencia de una métrica significa **desconocida**, nunca 0. Un 0 explícito es conocimiento de cero. Un baseline de kilómetros no habilita inferir horas o número de salidas.

Cada scope significa algo distinto: lifetime cuenta desde primera utilización del objeto; acquisition desde la adquisición de este usuario; service desde una intervención específica. La pantalla pregunta qué expresa el número. No guardar el mismo número automáticamente en lifetime y acquisition. Para material nuevo con uso cero confirmado se pueden crear ambas lecturas 0 en su fecha; para usado con 1.000 km anteriores a compra, lifetime=1.000 y acquisition=0 únicamente si esos datos están confirmados. Fecha de compra por sí sola no prueba uso cero.

En una consulta con instante T se suman salidas con inicio `< T`. Elegir por métrica y scope **la lectura de mayor corte C <= T**. Total = `baseline.value + sum(ItemUsage.metric para C <= Ride.started_at < T)`. El baseline cubre todo el uso anterior a C en ese scope; las salidas importadas antes de C se conservan pero no se vuelven a sumar. Si T=C el total es exactamente la lectura. Si hay varios baselines solo usar uno, nunca adicionarlos ni suponer que el segundo es un incremento.

Sin baseline elegible mostrar suma observada y cobertura parcial/desconocida, no presentarla como total de vida. Antes de un corte futuro, tampoco restar salidas de esa lectura para inventar total anterior. Una importación incompleta después de C sigue produciendo un total con cobertura parcial; el baseline no acredita completitud de las salidas posteriores. Métrica ausente en una salida o en un item usage mantiene el resultado observado y su indicador de desconocidos, sin convertir NULL en cero.

Acquisition usa `Item.acquisition_anchor_at` como límite de observación, independiente de `acquired_on` (compra civil) y de `UsageBaseline.cut_at` (lectura). Se guarda una vez el instante UTC explícito; el formulario puede proponer medianoche de compra en una zona elegida y confirmada. Cambiar zona de visualización o fecha civil no modifica el ancla. Una corrección de ancla es operación explícita que valida lecturas existentes y recalcula el tramo observado; no reinicia vida ni convierte un baseline de vida en adquisición. Si no se conoce el instante, dejar ancla NULL y mostrar adquisición desconocida, incluso con fecha de compra; no fabricar exactitud desde esa fecha. No derivar adquisición restando un total de vida desconocido en la compra.

Un período [P,T) dentro de un tramo observado suma salidas de ese período. Un baseline no permite distribuir el uso anterior al corte entre meses. Si un período atraviesa C y falta esa distribución, devolver observado y cobertura; no contar toda la lectura como si hubiera ocurrido dentro del período.

## 6. Ejemplos numéricos de aceptación

Todos los horarios siguientes son UTC y datos sintéticos.

| Caso | Historial y resultado esperado |
| --- | --- |
| Dos ruedas | Delantera F y trasera R, misma categoría, en `front_wheel` y `rear_wheel` de Bike1 desde 1 ene. Salida de 40 km/7.200 s: F=40 km, R=40 km. No sumar ambas como 80 km de bici. |
| Posición ocupada | Sillín A en `main_saddle` [1 ene, 10 ene). B en la misma posición [9 ene, ∞) se rechaza. B desde 10 ene se admite. En posiciones distintas la categoría no impone conflicto. |
| A→B→A | A [1 ene,10 ene), B [10 ene,20 ene), A [20 ene,∞). Salidas 5 ene=30 km, 10 ene=40 km, 20 ene=50 km. A tiene un UUID y dos instalaciones: 80 km; B=40 km. Una salida durante un hueco desmontado no suma a A. |
| Remontaje y servicio | Vida A=1.000 km antes de 1 ene; lubricación A el 6 ene. Al 21 ene: vida A=1.080 km; desde lubricación=50 km observados (si cobertura completa, 50 exactos). Remontar no reinicia ninguno. Calendario desde 6 ene transcurre aunque A esté desmontado. |
| Casco en dos bicis | H en perfiles de Bike1 y Bike2. Salidas de 20 y 35 km: H=55 km, 2 salidas. Si H además se incluye manualmente en la primera, sigue en 55 km/2, por set y UNIQUE item/ride. |
| Conjunto | Zapatilla Z incluida por perfil; cala C montada sobre Z. Una salida 25 km: Z=25 y C=25. Si C además figura en perfil, C sigue en 25; no hay segundo ItemUsage. |
| Corte sin dobleconteo | H lifetime distancia=1.000 km, C=1 ene 00:00. Importar 31 dic=70 km, 1 ene 00:00=20 km y 2 ene=30 km. Al 3 ene total vida=1.050 km, no 1.120. Antes de C solo 70 km observados, vida desconocida. |
| Cortes por métrica | Distancia como arriba; tiempo baseline=3.600 s en 2 ene 00:00. Salida 1 ene=1.800 s y 2 ene=900 s: tiempo al 3 ene=4.500 s, distancia=1.050 km. No reutilizar corte de distancia para tiempo. Sin baseline de tiempo: 2.700 s observados, vida en horas desconocida. |
| Compra posterior | Compra H=1 dic, lectura vida 1.000 km a 1 ene. No sabemos qué parte ocurrió antes del 1 dic: vida al 3 ene=1.050, adquisición=50 km observados más diciembre conocido; total adquisición desconocido salvo lectura acquisition independiente. |
| Dos lecturas | Vida distancia 1.000 km en 1 ene y 1.030 km en 2 ene. Salida 2 ene=30 km. Al 3 ene usar segunda: 1.060 km; no 2.060 ni 1.080. La lectura más reciente puede corregir la estimación previa. |

## 7. Bosquejo de siguientes modelos (no crear en garage-004)

`Ride`: UUID y owner propios; `started_at` UTC nullable solo para conservar una salida incompleta tras retirar su única fuente de inicio (crear manual/FIT exige inicio explícito), `name`, `sport_type`, `bike FK Bike NULL PROTECT`, `distance_m decimal(20,3) NULL`, `moving_time_s decimal(20,3) NULL`, `timer_time_s decimal(20,3) NULL`, `elapsed_time_s decimal(20,3) NULL`, `notes`, `updated_at`. Métricas >=0 y finitas. Los segundos conservan milisegundos como Decimal, sin truncamiento a entero. Bici desconocida permanece NULL, sin asignación por defecto. Guardar temporizador y movimiento por separado: `total_timer_time` de FIT no rellena automáticamente moving_time. Horas de mantenimiento usan moving_time; si falta, indicar desconocido o registrar una estimación manual explícita. Registro propio/manual no requiere cuenta externa. No convertir el FloatField de Activity en autoridad de totales; normalizar con decimal desde representación de origen y documentar precisión.

Conexiones y mappings externos siguientes son evolución condicional, no modelos requeridos para archivos/manual ni permiso para usar Strava. `ExternalConnection`: UUID/owner, proveedor, identidad externa de cuenta, estado de autorización/revocación. Unicidad por `(owner, provider, external_account_id)`; vínculo explícito y autorizado a Athlete cuando aplique, sin `.first()`. Tokens protegidos por tarea de conexión, no notas/JSON público. `BikeSourceLink`: bike, conexión, external_gear_id, único por `(connection, external_gear_id)` y misma propiedad.

`ActivitySource`: Ride, owner, tipo de fuente y ámbito de identidad (conexión para API; propietario + hash de archivo + índice de sesión para archivos), external_id/hash e import_run opcional. Unicidad por ámbito+identidad. Una salida puede tener varias fuentes; dos fuentes no crean dos usos. Coincidencia por hora/distancia es candidata, no unión automática en casos ambiguos. Procedencia **por campo** (bici, inicio, distancia, tiempos) incluye fuente, manual override, momento de actualización y restricciones/caducidad aplicables. Puede implementarse inicialmente con JSON estructurado validado, sin tablas EAV. Fuente de archivo propio no convierte campos rellenados por API en propios. Precedencias, retención y retirada siguen garage-data-sources.md y se concretan en garage-011; preservar correcciones manuales y recalcular si se pierde un campo. No respaldar totales permanentes en API no autorizada.

`ImportRun`: owner, intervalo solicitado, fuente, estado, progreso, cursor y errores sintéticos en tests. Jobs acotados al usuario y reanudables. Ningún import crea inventario/montajes históricos supuestos.

`UsageProfile`: owner, bici opcional (NULL=habitual general), modalidad concreta o general, período [inicio,fin), conjunto de items. Perfil general y específico se combinan mediante set; no crear precedencias implícitas que omitan casco general. Cambios ordinarios cierran/abren vigencia hacia futuro. Aplicar a salidas anteriores exige acción explícita. `UsageOverride` único `(ride,item)`, include/exclude; exclusión manual prevalece y se aplica después de expandir hijos; excluir un conjunto excluye su subárbol salvo inclusión explícita del hijo. Incluir un item expande sus hijos vigentes. Validar que el resultado no duplique items. Semántica concreta de perfiles y expansión se prueba en garage-015.

`ItemUsage`: único `(ride,item)`, owner, métricas normalizadas y datos mínimos de resolución/revisión. Representa material efectivo, no un contador incremental. Al corregir fecha/bici/distancia/modalidad, recalcular conjunto y métricas, retirar usos obsoletos y actualizar los existentes en una transacción; borrar Ride borra sus usos. Bloquear Ride para evitar dos reconstrucciones concurrentes; operaciones de montajes toman antes owner y luego rides en orden UUID cuando recalculen histórico. Un cambio histórico de montaje marca/recalcula intervalo afectado explícitamente, sin sumar diferencias a un contador irreversible. Baselines se aplican al consultar, no eliminan ItemUsage anterior al corte.

`ServiceType`: catálogo del owner (lubricar, sustituir, revisar). `ServiceEvent`: owner, destino XOR item/bike, tipo, `performed_at`, notas, importe+moneda opcionales. `MaintenanceRule`: owner, destino, tipo, umbrales independientes distancia/segundos/salidas/días >0, criterio de vencimiento cualquiera de los umbrales configurados. Solo el último ServiceEvent **del mismo tipo** anterior o igual al corte reinicia esa regla; no reinicia vida o adquisición ni otro tipo. Uso desde evento S es suma en [S,T), con cobertura; si baseline vida corta después de S, no permite inventar uso S→C. Una lectura scope=service vinculada a ese evento puede cubrir ese hueco. Sin evento, pedir ancla inicial explícita o mostrar sin fecha de referencia; no asumir compra o baseline vida como intervención. Si alguna métrica requerida es desconocida, mostrar el estado correspondiente; un umbral conocido ya excedido sí permite avisar de vencimiento.

`Photo`: owner, referencia privada de almacenamiento, destino XOR Bike/Item/ServiceEvent, dimensiones y metadatos del procesado; UUID no sustituye comprobar permisos. Procesado/almacenamiento se especifican en garage-009/010.

## 8. Resoluciones propuestas y pendientes reales

**Resueltas por este diseño y revisión:** PK UUID; propietario AUTH_USER_MODEL; categorías privadas; montajes por posición y destino XOR; [inicio,fin); exclusiones PostgreSQL inmediatas; bloqueo por owner para ciclos temporales; sin duplicación por propagación; baselines por scope/métrica con cortes independientes; desconocido distinto de cero; dinero decimal+moneda; salidas propias sin FK obligatorio a Activity. No hace falta escoger tecnología móvil, API pública ni organizaciones para implementarlo.

**Pendientes reales:** comprobación externa de fotos en bucket privado (garage-010), avisos y estadísticas (garage-018/019), exportación e integración final. Muestra FIT, procedencia/retirada, perfiles e interfaz de zona IANA ya están implementados; la preferencia persistente de zona horaria queda como mejora posterior. No se ha migrado el histórico legado de Strava: asociar o migrar registros existentes requiere titular explícito y la decisión sobre legado de garage-data-sources.md, sin propietario supuesto.

**Verificaciones que sí condicionan la implementación:** revisión adversarial de este contrato completada antes de garage-004; prueba de disponibilidad/instalación btree_gist con rol no superusuario en BD aislada antes de constraints de garage-006. En tests posteriores cubrir dos usuarios, cada CHECK/exclusión, dos conexiones simultáneas reales, ciclos con intersección común y sin ella, retiros retroactivos, todos los ejemplos y cortes DST. Esta entrega documental no afirma que esas pruebas ya existan.

## 9. Precisión de duración revisada con la muestra FIT

La validación autorizada del FIT original el 4 de octubre de 2026 confirmó
segundos fraccionarios en los tiempos de la sesión. Se ajusta el contrato antes
de implementar garage-007/011: distancia y duraciones usan `Decimal(20,3)`.
Solo `ride_count` exige un entero. La misma precisión se aplica a baselines,
Ride, ItemUsage y umbrales de tiempo de mantenimiento; la UI puede redondear
al mostrar, pero no modifica el valor guardado. Revisado por el coordinador
y un Sol adversarial; no afecta intervalos de montaje ni modelos legacy.

El importador parte del entero bruto FIT y su escala/offset usando Decimal,
no de un float intermedio. Valores que no se puedan representar exactamente
con tres decimales se rechazan con un error explícito de precisión en esta
primera versión; nunca se truncan o redondean silenciosamente. `NULL` en
movimiento permanece desconocido aunque exista tiempo de temporizador.


## 10. Procedencia de salidas concretada para garage-011

La primera implementación solo admite archivos FIT propios y correcciones
manuales. La muestra no identifica la bici de Garage; por ello la observación
FIT inicial no incluye referencias de bici. Esa asignación es manual y usa
la FK tipada de Ride, protegida y validada por propietario.

La identidad de una fuente FIT es propietario + hash SHA-256 del archivo +
índice de sesión. Su vínculo con Ride no cambia al reimportar. Las observaciones
se reemplazan como conjunto completo, para que un campo retirado del payload
no sobreviva accidentalmente. No se fusionan salidas por coincidencia de hora
o distancia.

Por campo prevalece una corrección manual explícita, incluso NULL; en su ausencia,
la fuente activa con valor conocido y cambio semántico más reciente, con un
desempate determinista. Reimportar el mismo payload o actualizar solo metadatos
del parser/importación no cambia esa precedencia. Una fuente retirada solo se
reactiva con una acción explícita, no por un reintento automático.

Retirar una fuente conserva Ride y sus correcciones manuales y recalcula cada
campo desde las fuentes restantes. Si desaparece la única fecha de inicio,
started_at pasa a NULL y la salida queda pendiente de completar; no se fabrica
una fecha. Los cálculos por intervalo y el motor de uso deben excluir ese registro
y declarar la incertidumbre. Tener un inicio conocido no acredita que todas
las métricas estén completas. Al borrar el registro de un trabajo de importación,
sus fuentes y salidas permanecen y la referencia import_run pasa a NULL.

Estas decisiones fueron revisadas por el coordinador y un Sol adversarial antes
de implementar; no declaran todavía pruebas ni cierre de garage-011.

**Enmienda garage-030 (18 oct 2026).** «No se fusionan salidas por coincidencia»
sigue valiendo dentro de una misma clase (nunca FIT↔FIT ni Strava↔Strava), con
una excepción **entre clases**: una actividad de Strava se une a la única salida
cuyo FIT activo (o, sin FIT activo, su inicio y distancia efectivos) empieza a
±90 s y mide ±2 %, y un FIT nuevo sólo se une a la única salida que hoy viene
sólo de Strava. Un FIT nuevo que coincide con una salida que ya tiene otro FIT
activo (de otro archivo) no se une: va a una salida nueva marcada «posible
duplicado» para no contarse dos veces en silencio. La precedencia pasa a ser por clase (`manual` > `fit` >
`strava` > `unknown`, la más reciente dentro de cada clase) y la bici puede
venir de un vínculo de bici de Strava. El vínculo `source.ride` sigue siendo
inmutable salvo en «Separar fuente» y «Unir con…» (§16).

## 11. Perfiles, excepciones y reactivación (garage-015)

Los perfiles se versionan por serie con intervalos [inicio, fin) sin solapamientos.
Una edición ordinaria conserva la versión anterior y abre la siguiente desde
ahora o una fecha futura. Crear o corregir efectos en el pasado exige una
operación histórica explícita; la interfaz pide fecha y confirmación. Se combinan
perfiles generales y específicos de bici/modalidad, montajes vigentes y
excepciones por salida. Se deduplican UUID tras expandir los conjuntos. Una
exclusión alcanza su subárbol, salvo inclusiones explícitas más profundas; otra
exclusión aún más profunda vuelve a aplicarse. Sin bici no se inventan raíces
de montaje; sin inicio conocido se declara la resolución pendiente.

Una reactivación real no debe borrar la inactividad pasada: un casco incluido
en el perfil general sumaría incorrectamente durante su retiro al reconstruir
el uso. `RetirementInterval` conserva esos períodos cerrados por bici u objeto,
con propietario, destino exclusivo, duración positiva y exclusión GiST de
solapamientos. `retired_at` representa únicamente el retiro actual o previsto.

`reactivate_inventory` cierra el retiro vigente en el instante indicado (por
defecto ahora), guarda [retired_at, reactivación) y limpia `retired_at`. Rechaza
reactivaciones futuras o anteriores al retiro. Si ambos instantes coinciden no
crea un intervalo vacío. Cancelar un retiro todavía futuro no inventa inactividad;
reactivar un objeto activo no añade historial. No se reabren montajes. La
corrección explícita de `retired_at` modifica el dato actual erróneo y conserva
los períodos ya cerrados.

Montajes y retiros actuales no pueden solapar esos períodos cerrados. El
resolver comprueba la inactividad en el inicio de cada salida, también para
material habitual, hijos, inclusiones manuales y bicis. Todas las mutaciones
se serializan bajo el bloqueo del propietario. La UI captura errores de
reactivación sin dejar operaciones parciales.

## 12. Contrato de importación y materialización (garage-014/016, completadas)

La previsualización FIT no escribe registros ni conserva el archivo. Un token
firmado de corta duración vincula propietario, hash, rango y selección de
sesiones; ejecutar exige reenviar el mismo archivo y volver a validarlo. El
trabajo guarda solamente un manifiesto mínimo (hash SHA-256 e índices elegidos),
además de su progreso. Ese manifiesto es inmutable y permite reanudar aunque
se cierre la pestaña o caduque la previsualización. No depende de rutas locales,
contenido FIT guardado ni heurísticas por fecha. Cada sesión confirmada y su
checkpoint se guardan juntos. Procesar todos los archivos enviados acredita
ese lote, no la completitud del histórico del usuario.

El uso por objeto y salida se materializa como filas únicas, nunca como sumas
incrementales irreversibles. Cambiar una salida recalcula su conjunto completo;
los cambios temporales de montajes, perfiles o retiro reconstruyen de forma
conservadora las salidas del propietario en la misma transacción. El bloqueo
se toma primero sobre propietario y después sobre salidas en orden UUID. Es
una elección inicial de sencillez: el coste crece con el histórico y habrá que
medirlo antes de ampliar la escala.

Cada fila conserva inicio y bici de la resolución. Una reconstrucción por
rango selecciona tanto el inicio actual como el inicio anterior materializado:
si una corrección mueve una salida fuera del rango, sus filas antiguas no quedan
abandonadas. Una salida que pierde su único inicio conocido elimina sus usos
resueltos y permanece como pendiente. Un dry-run calcula cambios sin escribir,
ni siquiera timestamps. Repetir una reconstrucción idéntica conserva UUID y
fecha de modificación de las filas.

Las consultas aplican las lecturas previas por métrica y ámbito después de
seleccionar las observaciones. Ausencia de métricas, inicio o bici se expone
como incertidumbre; haber importado un lote no equivale a tener cobertura
completa. Distancia, tiempo en movimiento, temporizador y tiempo transcurrido
permanecen separados. No se suman usos de componentes para obtener uso de bici.

La reconstrucción prepara una sola vista del inventario, montajes, perfiles y
excepciones del propietario. Agrupa las escrituras de hechos calculados para
evitar consultas repetidas por objeto y salida; conserva las restricciones SQL,
la validación de valores y el bloqueo transaccional. La prueba de coste usa un
histórico sintético representativo, además de las pruebas de corrección.

`UsageMaterializationState` guarda por propietario si se completó la
inicialización. La migración no copia el histórico legado ni ejecuta servicios
actuales en un RunPython. Las salidas Garage anteriores requieren reconstrucción
completa explícita; una consulta pendiente de inicialización no presenta cero
como uso conocido. El comando limitado a un rango no acredita todo el histórico.
Las escrituras ordinarias mantienen la materialización en su misma transacción;
un propietario con una sola salida queda inicializado al reconstruir esa salida
completa mediante el servicio ordinario. La marca no acredita que el usuario haya
registrado todas sus salidas reales y no sustituye el indicador de cobertura.

## 13. Intervenciones y reglas (garage-017)

Migración 0008: catálogo privado `ServiceType`, `ServiceEvent` y `MaintenanceRule`.
Evento y regla tienen exactamente un destino, item o bici, del mismo propietario
que su tipo. Existe como máximo una regla por destino y tipo; sus umbrales se
configuran de manera independiente, estrictamente positivos. Distancia y tiempo
usan Decimal con tres decimales; salidas y días son enteros. La interfaz actual
expresa las unidades explícitamente en metros y segundos en movimiento.

La referencia de una regla es el último evento de ese mismo destino y tipo con
`performed_at <= T`. Si no existe, usa únicamente `anchor_at` explícito no futuro;
compra, adquisición, retiro y montajes no proporcionan referencias implícitas.
Un empate de fecha se resuelve por creación más reciente y UUID estable. El
cálculo de vencimientos y avisos corresponde a garage-018.

Las lecturas service se distinguen además por `service_event`: dos eventos del
mismo objeto pueden tener cortes coincidentes sin sobrescribirse. El evento se
resuelve por propietario y debe afectar a ese item; corte anterior al evento,
evento ajeno o intervención sobre bici son inválidos. El alta de material usado
solo admite lifetime/acquisition; una lectura service se registra después desde
un objeto existente, seleccionando una intervención concreta.

Un evento con lecturas impide cambiar destino, tipo o fecha hasta corregir o
retirar esas lecturas. Un evento con fotos impide cambiar destino. Las operaciones
se serializan con el bloqueo del propietario y protegen referencias dependientes.
El importe opcional conserva dos decimales y exige moneda ISO 4217; se muestra
por intervención, sin conversión ni suma entre monedas. Las fechas de formularios
conservan microsegundos e interpretan una zona IANA explícita, rechazando horas
ambiguas o inexistentes.

Una misma visita puede registrar varias intervenciones (garage-035): al crear una
desde la pantalla de un objeto o bici, se ofrecen las reglas de ese destino y de
lo montado en él (a cualquier profundidad) en la fecha de la intervención. Cada
regla marcada crea otra intervención ordinaria con su destino y tipo, la misma
fecha y nota y sin importe, en la misma transacción que la principal. No hay
propagación implícita: registrar en el padre no reinicia reglas de las piezas
que no se marcaron. Las extra no quedan enlazadas a la principal (editarla o
borrarla no las cambia). El material que sólo cuenta por perfiles de uso no es
una pieza montada y no se ofrece. Si lo montado en esa fecha difiere de la lista
mostrada, no se guarda nada y se vuelve a mostrar.

Photo admite ahora destino XOR bici/item/evento y conserva los mismos permisos,
reservas de cuota y limpieza de garage-010. La extensión de destino no acredita
la conexión externa a un bucket, que sigue pendiente de su prueba real.

**Enmienda garage-030 fase 3 (desnivel).** Una regla admite además el umbral
`elevation_gain_m`, independiente de los demás, estrictamente positivo y con la
misma exactitud que la distancia (Decimal, tres decimales). El formulario del
teléfono pide **metros enteros** («Desnivel (m)», teclado numérico); un valor con
decimales guardado desde el admin conserva su campo exacto y no se trunca. El
formulario de vida útil tiene el mismo campo (si el valor guardado no es entero,
se edita en la regla del Taller). Los textos de umbrales lo muestran exacto como
«20.000 m de desnivel». Revisión de código: el `IntegerField` de Django quitaba
un «.000» final y guardaba «20.000» como 20 m. Los enteros del teléfono (desnivel
de regla, vida útil y aplazamiento; salidas y días de regla y aplazamiento;
tiempo de la vida útil) usan ahora `WholeNumberInput`: texto con teclado
numérico donde «20.000», «20 000» (también con espacio duro o fino) son veinte
mil, y cualquier otro punto o coma («1.5», «2,5», «1.000,0», «0.500») se rechaza
sin truncar. El formulario del admin conserva sus campos.

**Enmienda garage-043 (importación de ProBikeGarage, 25 oct 2026).** El
importador (`garage_import_probikegarage`, sólo sobre un Garage sin bicis ni
material) crea los **tipos de intervención por nombre**, reutilizando los del
propietario sin distinguir mayúsculas ni espacios en los extremos: el título de
cada intervalo repetible es el tipo de su regla; los intervalos no repetibles son
la vida útil («Sustitución», garage-033; varios se combinan en una regla, lo
primero que llegue). Una intervención crea un evento por cada intervalo listado
de cada componente, con el tipo de ese intervalo, y, si a un componente no le
corresponde ninguno, un evento con el título de la intervención como tipo. Ese
evento sigue la regla general de esta sección: si el componente tiene una regla
de ese mismo tipo, la reinicia (es su referencia) y el informe lo avisa. Lo que
hacía ProBikeGarage no está demostrado: en el único caso observable del volcado
real (una pieza retirada) reinició tras una intervención así un intervalo
repetible de **otro** título, que Garage no reinicia; ahí Garage reinicia menos
y la verificación lo muestra como una diferencia. Varios intervalos
no repetibles de una pieza marcados en la misma intervención dan una sola
«Sustitución». Si el título difiere del tipo, se antepone a las notas
(«Título. notas»); sin importe ni moneda. Las reglas se anclan en el primer
montaje del componente; sin montaje no tienen ancla ni referencia hasta su
primera intervención. El uso inicial se guarda como lecturas `lifetime`
estimadas (fuente «ProBikeGarage (uso inicial)») con corte en el primer montaje
(§5); su desnivel no se guarda (no hay lecturas de desnivel, §17). Detalle en
`docs/garage-data-sources.md` («ProBikeGarage como origen de inventario»).

## 14. Vencimientos y avisos internos (garage-018)

`maintenance_due(actor, at=...)` calcula un snapshot de todas las reglas propias
bajo la misma transacción y bloqueo del propietario usados por las escrituras.
Carga referencias y hechos en un lote de consultas; consultar el panel no
materializa usos ni modifica marcas o registros. La prueba concurrente acredita
el bloqueo real del lector con `pg_blocking_pids` antes de liberar al escritor.

Orden de estado: vencido, desconocido, próximo, vigente. Cualquier umbral
alcanzado determina vencido. Si ninguno vence y alguna métrica configurada tiene
cobertura incompleta o es desconocida, el estado es desconocido. Próximo requiere
alcanzar el 90 % de un umbral y cobertura suficiente de todas las métricas
configuradas; es una convención visible de la interfaz. La comparación usa
Decimal exacto, aunque la presentación en kilómetros/horas redondee.

Para items, la lectura service elegida pertenece al evento de referencia y a la
métrica concreta, con el mayor corte C <= T. Suma únicamente [C,T); sin esa
lectura, observa [S,T). Nunca reutiliza lifetime/acquisition. Los hechos de uso
no inicializados no acreditan un vencimiento: podrían estar obsoletos. Una
lectura exactamente en T conserva su valor explícito aun en ese caso. El
intervalo vacío [S,S) permite cero lógico. La inicialización no demuestra que
estén registradas todas las salidas reales: un intervalo no vacío sigue parcial.

Para bicis, usa directamente salidas propias asignadas a esa bici y período,
sin sumar componentes. Inicio o bici desconocidos aparecen como contexto del
propietario y no se atribuyen a un destino. Un mínimo observado fiable puede
acreditar vencimiento con histórico parcial; por debajo del umbral no demuestra
que esté al día. Las lecturas estimadas conservan una indicación visible tanto
en el valor como en el estado, sin prometer exactitud ni un mínimo garantizado.

Calendario significa días de 24 horas transcurridos desde la referencia UTC;
no se detiene al desmontar o retirar. Se calcula duración, sin construir una
fecha futura que pueda desbordarse con un umbral de días grande. Lubricar,
sustituir y revisar seleccionan sus propias referencias y no reinician otras
reglas. El panel inicial y la página de mantenimiento muestran estado, métricas,
cobertura y restante; no envían notificaciones fuera de la app.

**Enmienda garage-030 fase 3 (desnivel).** `maintenance_due.METRICS` termina en
`elevation_gain_m`; el orden no decide nada (gana lo primero alcanzado). Mismas
reglas que la distancia: referencia, intervalo [R,T), hechos de la bici o
`ItemUsage` del objeto (el desnivel de cada salida pasa íntegro a lo resuelto),
vencido si el mínimo observado alcanza el umbral, «próximo» al 90 % sólo con
cobertura completa y, si no, «Revisar» en pantalla. No hay lecturas de desnivel
(`UsageBaseline` no lo admite): siempre cuenta lo observado desde la referencia.
Una salida sin desnivel es una contribución desconocida (`missing_values`) y el
valor queda como mínimo. Revisión de código: si **ninguna** salida del intervalo
lo trae (lo normal en fuentes anteriores a la 0012), el desnivel es desconocido
(`unrecorded`, estado «Sin datos»), igual que en estadísticas: un 0 observado
nunca avisaría. Un intervalo sin salidas sigue siendo 0 observado; distancia y
tiempo no cambian. Las pantallas lo dicen: «N sin desnivel» en la fila del aviso
y en la ficha del objeto, una nota con el recuento y cómo completarlo («volver a
importar los FIT o el histórico de Strava») en el objeto y en Posponer, y un
motivo propio en «Sin datos» del Taller. Presentación: unidad «m», nombre «Desnivel» y la marca
«↑» delante de las cifras sueltas («↑ m quedan», «↑ m de 3.000») para que nunca
se lean como distancia.

## 14 bis. Aplazamientos de avisos (garage-034)

Migración 0009 (aditiva, sólo local): `MaintenanceSnooze` pospone el aviso de una
regla desde `started_at` por km, horas, salidas y días (al menos una cantidad;
la interfaz exige siempre días como máximo). Termina con lo primero que se
alcance. Guarda la referencia de la regla al posponer (`reference_at` y la
intervención, si existe) y sólo vale mientras la referencia actual sea esa:
cualquier intervención que pase a ser la referencia, también con fecha
anterior, o otro ancla reinicia la cuenta; borrarla lo recupera. Mover la regla
a otro destino o tipo cierra el aplazamiento abierto. Como mucho uno abierto por
regla; uno nuevo cierra el anterior en su inicio y nunca empieza antes del
último inicio o fin (sin solapes) ni en el futuro.

`maintenance_due` añade `snooze` a cada vencimiento: uso observado en
[inicio, T) con los mismos hechos que la regla (sin lecturas service) y días de
24 h. Estado `reached` si alguna cantidad se alcanzó, `unknown` si alguna no
tiene valor (uso por objeto sin materializar) y `active` si no. Un aplazamiento
activo oculta el aviso sólo si el estado real requiere atención; se muestra
«Pospuesto» con el estado real visible. Uso desconocido nunca oculta un aviso.
Los km, horas y salidas observados son un mínimo: mantener el aviso pospuesto
con ese mínimo es una excepción que la persona acepta al posponer, acotada por
el máximo de días; lo que queda se presenta «como máx.». Agotarse o dejar de
valer se calcula y no escribe nada: `ended_at` nulo no significa activo, y
cambiar salidas o el uso puede volver a activar uno agotado.

**Enmienda garage-030 fase 3 (desnivel).** Cantidad `elevation_gain_m` en metros
enteros (formulario y atajo «10 % de la regla», redondeado hacia arriba y como
mínimo 1 m). Es más estricta que km, horas y salidas: **una sola salida del
intervalo sin desnivel deja esa cantidad desconocida**, así que el aplazamiento
pasa a `unknown` y el aviso se muestra; la página lo explica («Aplazamiento por
revisar: alguna salida desde entonces no registra desnivel»), distinto del uso
pendiente de calcular. Motivo: las fuentes antiguas (FIT anterior a
`fitdecode-0.11.0-m2`, salidas manuales) no traen desnivel y un mínimo ocultaría
el aviso demasiado tiempo. Alcanzada, se nombra exacta («500 m de desnivel»); lo
que queda se presenta «como máx. ↑ 200 m».

## 15. Estadísticas privadas (garage-019)

`statistics(actor, started_from=..., started_to=..., bike=..., category=..., item=...)`
calcula un snapshot bajo transacción y bloqueo del propietario, con consultas por
lotes y Decimal de precisión local. No reconstruye hechos ni escribe registros.
Los filtros sólo aceptan recursos propios. La página es privada, GET y sin caché;
sus fechas conservan microsegundos, usan una zona IANA explícita y rechazan horas
ambiguas o inexistentes.

El período observado es [inicio,fin), seleccionado por inicio UTC de la salida.
Las bicis suman sus salidas directas; los objetos usan ItemUsage vigente. No sumar
componentes como si fueran distancia de bici. NULL sigue desconocido y el tiempo
de temporizador no sustituye al movimiento. El uso no inicializado no permite
mostrar atribuciones posiblemente obsoletas entre bicis.

Los totales de vida, adquisición y última intervención se calculan al corte final
con la última lectura admisible por métrica/ámbito/evento y contribuciones desde
su corte. No dependen del inicio o bici elegidos para observar un período. Las
lecturas previas nunca se reparten entre bicis, montajes o meses. Un subtotal
conocido conserva su valor y señala contribuciones desconocidas. Sin lectura,
el total de vida/adquisición es desconocido; el observado se muestra separado.
Servicio sin lectura ofrece uso observado desde el evento. Una lectura en el
corte o un intervalo de servicio vacío permite cobertura completa en ese corte;
el resto es conservadoramente parcial, incluso después de reconstruir.

La distribución usa la bici histórica de cada hecho. Los remontajes A→B→A
conservan sus intervalos; un montaje directo en A no recibe hechos de B por
perfiles o excepciones. Los montajes anidados identifican el padre y presentan
uso durante ese intervalo, sin afirmar una ruta completa de ancestros. Los
períodos entre intervenciones agrupan destino y tipo, independientemente de
otros tipos; conservan las lecturas vinculadas a cada evento concreto.

Los costes registrados se agrupan por moneda, sin conversión. Se distinguen
intervenciones del período y compra más intervenciones desde una adquisición
con instante explícito. Los importes desconocidos no son cero y las entradas
sin coste se cuentan una sola vez entre ámbitos solapados. El coste/km exige
un denominador de distancia positivo, completo, sin estimación y costes
declarados conocidos en ese ámbito. Una lectura exacta de adquisición en el
corte puede habilitarlo; un subtotal observado parcial de bici/período no lo
habilita. El resultado representa costes declarados, no una contabilidad total.

**Enmienda garage-030 fase 3 (desnivel y potencia).** `statistics.METRICS` y
`monthly.METRICS` añaden `elevation_gain_m` al final (las pantallas y el coste/km
siguen usando las posiciones 0–2). Por bici, objeto, montaje, intervención y
mes se suma el desnivel conocido; todas las salidas sin él ⇒ desconocido (no
cero), algunas ⇒ mínimo con su recuento. Sin lecturas de desnivel, los totales
de vida y adquisición de un objeto son desconocidos; desde una intervención es
lo observado. La página muestra el desnivel del período («↑ 2.000 · m de
desnivel», sólo si se conoce), por bici y material, y el gráfico mensual cambia
entre km y desnivel con `?chart=elevation` (mismas consultas, sin JavaScript).
Revisión de código: las filas por bici y por material de Estadísticas y la bici
en Inicio marcan el mínimo («↑ ≥ 2.000 m») cuando alguna salida no lo trae, y el
gráfico mensual de desnivel dice cuántas salidas de esos meses no lo registran,
con la misma indicación para completarlo. La potencia media de un período no es aditiva: no se suma ni se muestra aquí
(queda para más adelante, p. ej. media ponderada por tiempo con cobertura).

## 16. Strava como fuente (garage-030, fases 1–2, modo token)

Migración 0010 (local; en Neon sólo con el despliegue de garage-023). Aditiva
salvo dos CHECK ampliados (`garage_activitysource_kind_valid` y
`garage_importrun_source_valid` sustituyen a los de «sólo fit»), que las filas
existentes cumplen; prueba de migración sobre filas FIT.

**Cuenta (modo token).** `GARAGE_STRAVA_USER` nombra al usuario de Garage dueño
del atleta de Stravagancia. `StravaAccount` (`mode='env'`, propietario y atleta
únicos) se crea en la primera sincronización o importación manual con
`GET /athlete` y no guarda tokens (CHECK): el token sale sólo de
`strava_integration.utils.refresh_access_token()`. Se supone el permiso
`activity:read_all` del token del legado. `mode='oauth'` queda para garage-040.
«Quitar lo sincronizado desde Strava» borra la fila; la siguiente sincronización
o importación manual la vuelve a crear (la sincronización diaria de la fase 4
nunca la crea).

**Fuente e identidad.** `ActivitySource(source_kind='strava')` con
`external_id` (id de actividad, único por propietario, inmutable), `gear_id`
observado, `file_hash = sha256("strava:{atleta}:{actividad}")`,
`session_index = 0` y `parser_version = 'strava-api-v3'`: las restricciones de
hash e identidad existentes no cambian. CHECK: strava ⇒ `external_id` no nulo
y > 0 e índice 0; fit ⇒ `external_id` nulo y `gear_id` vacío. Observaciones:
inicio UTC, nombre, deporte canonizado, distancia, tiempo en movimiento y
transcurrido; temporizador desconocido (Strava no lo da). Números con
`parse_float=Decimal`; un valor no exacto a tres decimales, negativo o float es
desconocido, nunca redondeado. Sólo ciclismo (`Ride`, `GravelRide`,
`MountainBikeRide`, `EBikeRide`, `EMountainBikeRide`, `VirtualRide`,
`Velomobile`, `Handcycle` → claves de `garage/sports.py`); el resto se omite y se
cuenta.

**Precedencia.** Campo a campo: corrección manual; fuente FIT activa más
reciente; fuente Strava activa más reciente; desconocido. Única excepción: un
`sport_type` específico de Strava sustituye al `cycling` genérico del FIT. La
bici, sin corrección manual, sale del `gear_id` de la fuente Strava activa a
través de `StravaGear.bike` (procedencia `strava` con esa fuente). Vincular,
desvincular o cambiar el «retirada» de una bici de Strava recalcula sus salidas
y reconstruye su uso; retirada en Strava no desvincula.

**Perfiles por familia.** Un perfil con `cycling` cubre todas las claves de
ciclismo; uno con clave específica, sólo esa; vacío, todas. Se aplica al
resolver de uso y a la revisión de una salida.

**Vinculación.** Ver la enmienda de §10. Cero candidatas ⇒ salida nueva; dos o
más, o una que ya tiene fuente Strava activa ⇒ salida nueva con la fuente
marcada `possible_duplicate`. Como mucho una fuente Strava activa por salida
(regla de servicio). «Separar fuente» mueve una fuente activa (de una salida con
otra activa) a una salida nueva; «Unir con…» la mueve a una salida propia sin
fuente activa de su clase; ambas recalculan las dos salidas y reconstruyen el
uso. Tras «Unir con…», la salida que se queda sin filas de fuente se borra sólo
si no tiene ninguna corrección manual (nombre, bici y notas incluidos) ni
excepciones de material; si las tiene, se conserva (pendiente si pierde el
inicio), y la página de confirmación lo explica antes de unir. «No es un
duplicado» sólo quita la marca.

**Borrado.** Un `delete` del webhook confirmado con 404, una actividad que deja
de ser ciclismo y «Quitar lo sincronizado» **borran** la fila Strava (política
§6.3/§7.4: no quedan observaciones). La salida se borra con su uso si no le
queda ninguna fila de fuente ni corrección de medida (inicio, deporte,
distancia, tiempos; nombre, bici y notas no cuentan); si no, queda (pendiente si
pierde el inicio). «Retirar» desde la ficha marca `withdrawn_at` y la
sincronización no la reactiva.

**Histórico y sincronización.** `ImportRun(source_kind='strava')` sin
manifiesto: `requested_from` = fecha elegida, páginas de 50 en orden
ascendente (hasta 4 por pulsación), `processed = cursor =` páginas confirmadas, `total` nulo (CHECK),
`items_imported` (ciclismo guardado o ya conocido) e `items_skipped` (otros
deportes, retiradas a mano, datos no válidos). Una página y su punto de control
van en una transacción con el bloqueo del propietario y una reconstrucción. 429
o 401 ⇒ `failed` con `rate_limited`/`unauthorized`, sin bucles; se continúa.
Los resúmenes de error se acumulan entre páginas (sin repetir, ≤ 20); una página
confirmada quita los transitorios (429, 401, red). «Sincronizar ahora» lee
`GET /athlete`, los últimos 7 días (≤ 2 páginas) y hasta 10 avisos pendientes:
como mucho 14 peticiones a Strava, ninguna empezada tras 25 s; un 429 o 401 de
los avisos marca la sincronización como fallida. La red (también la renovación
del token) nunca se usa dentro de una transacción ni con el bloqueo del
propietario tomado. Una actividad nueva cuesta un número acotado de consultas
(probado: ≤ 15 en una página de 20).

**Webhook.** Compartido con el legado y despachado por atleta: si
`STRAVA_WEBHOOK_SUBSCRIPTION_ID` existe, otro id se descarta; Garage guarda
`StravaEvent` (sin propietario, deduplicado, sin títulos, tope de 500 pendientes
por atleta) antes del 200 sólo si el atleta tiene `StravaAccount`. Tras el
commit arranca como mucho un hilo por atleta y proceso (si ya hay uno, hace
otra ronda), que cierra su conexión; el legado sólo procesa su propio
`Athlete.strava_id`. Cada aviso se reclama (intento contado y confirmado) antes
de llamar a Strava, la llamada va sin transacción abierta y la escritura toma
primero el bloqueo del propietario y después la fila del evento (el mismo orden
que «Quitar lo sincronizado»). Los avisos son pistas: crear o actualizar ⇒ se
pide la actividad, que debe ser de este atleta; borrar ⇒ sólo con 404 y
`activity:read_all` (fase 4: si la actividad sigue en Strava, se guarda lo que
devuelve como en una actualización, y si ya no es ciclismo se borra; un borrado
nunca crea una fuente). Un aviso con respuesta inservible se da por cerrado al
quinto intento. Los eventos `athlete` se ignoran en modo token. Purga a los 30
días al sincronizar.

**Enmienda fase 3 (menores de la re-verificación de fases 1–2).**
- Un aviso que llega durante la última ronda de un worker ya no se queda
  esperando: la última ronda no consume la petición de «otra ronda» y, al
  liberar al atleta, arranca un worker nuevo.
- Un lote lleno (`EVENT_BATCH`, 50) que confirmó alguno va seguido de otra
  ronda; si era la última, un worker de fondo cede el resto a uno nuevo. Un lote
  lleno que no confirmó ninguno (todos fallan por ahora) no se repite en el acto,
  para no insistir a Strava. «Sincronizar ahora» (10 avisos) no arranca hilos
  por el resto: lo informa como pendiente.
- Tiempo máximo: ninguna llamada empieza tras `REQUEST_SECONDS` (25 s) y el
  cliente recorta sus timeouts de conexión y lectura para que **juntos** no pasen
  de lo que queda hasta `RESPONSE_SECONDS` (30 s; mitad y mitad si queda poco).
  requests no tiene timeout total: la resolución DNS, un cuerpo que llega a
  goteo (cada trozo reinicia la lectura) o la renovación del token pueden añadir
  algunos segundos, así que la respuesta tarda «unos 30 s», no es un límite
  estricto; el techo duro es el timeout de gunicorn (60 s). Revisión de código:
  antes cada timeout se recortaba por separado y una llamada empezada a los 25 s
  podía llegar a ~35 s. Una página o un aviso cortados así no son un error (código interno
  `deadline`, nunca guardado): la semana queda incompleta, el aviso pendiente sin
  nota y un paso de importación en pausa («Continuar» repite esa página). Sólo
  si se cortan las primeras llamadas (renovación lenta del token) se informa
  `network`. Límite conocido: `refresh_access_token()` del legado no tiene timeout.
- Perfiles de uso: la modalidad se muestra con `sport_label` («gravel», no
  `gravel_ride`).

**Operación diaria (fase 4, 18 oct 2026; spec
`.claude/specs/2026-10-18-garage-strava-fase4-spec.md`).** Sin migración nueva.
- **Un solo trabajo.** `sync_now(actor)` («Sincronizar ahora») y `sync_all()`
  usan el mismo `_sync_owner(owner)`: `GET /athlete`, la semana (≤ 2 páginas),
  la ausencia y hasta 10 avisos, con los mismos topes (14 peticiones, unos
  30 s). `sync_all(now=None)` purga los avisos de más de 30 días y recorre las
  cuentas existentes (en modo token, como mucho la del propietario de
  `GARAGE_STRAVA_USER`; un bucle pensado para garage-040). Nunca crea la cuenta
  (`_sync_owner(owner, create=False)`): tras «Quitar lo sincronizado» sólo la
  vuelve a crear una acción de la persona, y si se quita mientras la ejecución
  diaria espera a Strava, no se escribe nada más para ella (se comprueba con el
  bloqueo del propietario antes de cada escritura) y termina como `idle`.
  Resultado `{pending, status, error, accounts, purged, absences}`: `pending` =
  avisos sin confirmar tras la ejecución (las pistas de ausencia incluidas) + 1
  por cuenta cuya semana quedó incompleta; `status` es `idle` (sin propietario
  configurado o sin cuenta), `ok`, `partial` (actividades inservibles) o
  `failed`. Un código de parada (`rate_limited`, `unauthorized`, `network`…)
  termina la ejecución con `status='failed'` y `error`, sin otra llamada ni
  reintento, y deja los pendientes como estén. Una línea `INFO` del logger
  `garage` (`garage.services.strava_sync`) con contadores y códigos, nunca el
  token ni nombres.
- **Ausencia como pista.** Sólo si la semana se leyó completa, sin código de
  parada y sin actividades inservibles, y sólo con `activity:read_all` (supuesto
  en modo token; se comprueba a mano antes de desplegar, docs/garage-handoff.md
  «Despliegue»: sin él, una salida hecha privada parecería borrada). Cada fuente Strava activa (no retirada a mano) cuyo inicio
  observado es posterior al `after` que se pidió a Strava y que la lista no
  nombró recibe un `StravaEvent` sintético (`delete`, `subscription_id=0`,
  `event_time` = ese `after`, `updates={"origin": "absence"}`), con el bloqueo
  del propietario y deduplicado: la clave única de siempre y ninguna segunda
  pista mientras haya un borrado pendiente de esa actividad. Como mucho
  `ABSENCE_HINTS` (20) por ejecución y el tope de 500 pendientes. Lo confirma el
  camino de un `delete` del webhook en la misma ejecución (o en la siguiente):
  404 ⇒ fuente borrada (y la salida, si se queda sin fuentes ni correcciones de
  medida); deporte no ciclista ⇒ borrada; sigue ⇒ se conserva y se actualiza;
  un error deja la pista pendiente. Fuentes anteriores a la ventana: sólo por
  webhook (límite documentado).
- **Revocación externa.** Sólo marca la cuenta que Strava rechace el token
  mismo: la renovación rechazada o un 401 tras una renovación antes de que
  `GET /athlete` responda (`SyncResult.rejected`). Pone `revoked_at` una sola
  vez: su fecha no se mueve mientras dure. En cuanto Strava responde a
  `GET /athlete` se anula (bajo el bloqueo del propietario), para que los
  avisos de esa misma ejecución se confirmen, y un final correcto (`ok` o
  `partial`) también lo anula. Un final por `network` (también un 5xx, un 429
  del endpoint del token o una renovación lenta), `rate_limited` o
  `invalid_response` no lo toca: no prueba nada sobre el token y no reinicia el
  plazo. Un 401/403 posterior a la aceptación (un aviso, un permiso que falta)
  hace fallar la ejecución sin marcar la cuenta. Mientras no sea nulo, el
  webhook y los workers ignoran al atleta (filtros de las fases 1–2).
- **Purga a 30 días** (API Policy §7.4). Sólo `sync_all`, y sólo si en esa
  misma ejecución Strava sigue rechazando el token (`rejected`): un token que
  vuelve a valer, un fallo de red o un 429 nunca purgan (la purga espera al día
  siguiente). El día de la purga es una fecha local de Madrid, la zona de la
  ejecución diaria (`DAILY_SYNC_ZONE`): `purge_date(revoked_at)` = día local de
  `revoked_at` + 30, y `purge_due` se cumple desde ese día (la ejecución de las
  09:05 de esa fecha purga, nunca un día después de la fecha que muestra Más →
  Strava, sea cual sea la hora de la revocación o un cambio de hora). Hace
  exactamente «Quitar lo sincronizado» (`remove_strava_data`, comprobado otra
  vez con el bloqueo del propietario): fuentes Strava, salidas sólo-Strava sin
  correcciones de medida, `StravaGear`, la fila y sus eventos; `purged += 1`.
  El botón nunca purga: sólo lo intenta otra vez.
- **Disparo.** `POST /garage/strava/sync-all/` (`garage:strava-sync-all`): sin
  sesión ni CSRF; con `GARAGE_SYNC_TOKEN` vacío o de menos de 32 caracteres
  responde 404 a cualquier método, como una URL inexistente; si no, sólo POST
  (405), y una cabecera `X-Sync-Token` ausente o distinta (comparada con
  `hmac.compare_digest`) es un 403 sin cuerpo que no escribe nada ni llama a
  Strava. El cuerpo se ignora; la respuesta es 200 JSON también cuando
  `status='failed'`. Lo llama una vez al día el Worker de Cloudflare
  (`keepalive/`), que repite mientras `pending > 0` y sin `error`, como mucho
  K veces, y nunca sigue una redirección (un 3xx para ese día). La comparación
  del token se hace en una función aparte: el valor nunca es una variable local
  de la vista (una página 500 con DEBUG imprime las de cada marco). `manage.py garage_strava_sync` ejecuta lo mismo y escribe el JSON;
  `manage.py garage_sync_token` imprime un token nuevo
  (`secrets.token_urlsafe(48)`) sin escribir ningún archivo.
- Sigue pendiente: OAuth por usuario y «Desconectar» con revocación (garage-040).

## 17. Desnivel y potencia (garage-030 fase 3, garage-037)

Migración 0012 (local; en Neon sólo con el despliegue de garage-023). Aditiva
salvo que sustituye `garage_maintenancerule_has_threshold` y
`garage_snooze_has_amount` por versiones que también aceptan el desnivel (las
filas existentes ya cumplen las nuevas); reversible mientras ninguna regla o
aplazamiento dependa sólo del desnivel.

**Campos.** Ride y ActivitySource: `elevation_gain_m`, `average_power_w`,
`max_power_w`, `weighted_power_w`, `energy_kj`, `Decimal(20,3)` nulos con
`exact_usage_value` y CHECK de rango [0, `MAX_USAGE_VALUE`] (el desnivel puede
ser 0). ItemUsage: sólo `elevation_gain_m`. MaintenanceRule y
MaintenanceSnooze: `elevation_gain_m` (> 0, ≤ `MAX_USAGE_VALUE`; Decimal como
la distancia: los metros enteros los exige el formulario).

**Tuplas** (`garage/ride_values.py`). `CORE_METRICS` = distancia y los tres
tiempos (criterio de «pendiente» y cobertura, sin cambios); `USAGE_METRICS` =
`CORE_METRICS` + desnivel (lo que fluye a ItemUsage; `METRIC_FIELDS` es su
alias); `POWER_METRICS` = potencia media, máxima, ponderada y kJ;
`RIDE_METRICS` = `USAGE_METRICS` + `POWER_METRICS` (observaciones de fuente,
precedencia, correcciones manuales, procedencia por campo y exportación).
`SOURCE_FIELDS` y `RIDE_FIELDS` incluyen las nueve. Una corrección manual de
desnivel o potencia es una corrección de **medida** (§16, «Borrado»).

**Observación.** FIT y Strava como en `docs/garage-data-sources.md` (fase 3):
potencia de Strava sólo con `device_watts`; plausibilidad (≤ 2.500 W media y
ponderada, ≤ 5.000 W máxima, ≤ 20.000 m, ≤ 50.000 kJ) ⇒ desconocido, nunca un
error, sólo en el parser y el adaptador. En el FIT, un campo opcional repetido o
mal formado también es desconocido (revisión de código). Reimportar el FIT o volver a observar
la actividad en Strava rellena las fuentes antiguas.

**Motor.** El desnivel de la salida (el de la fuente que prevalece; nunca se
suman fuentes) pasa íntegro a cada objeto resuelto, como la distancia, y se
reconstruye igual. La potencia no se materializa. No hay lectura previa de
desnivel (`UsageBaseline` no lo admite): el desnivel de toda la vida de una
pieza es sólo lo observado. Reglas y aplazamientos: §13, §14 y §14 bis
(enmiendas); estadísticas: §15.

**Pantallas.** El desnivel aparece como «↑ 1.234 m» (filtro `metric_m`: metros
enteros con separador de miles) donde se ven distancia y tiempo y sólo si se
conoce: listas de salidas e histórico, previsualización FIT, revisión y su
efecto, ficha de la bici (cuarta cifra y últimas salidas), objeto (cuarta cifra),
uso entre intervenciones (`span_text`, «↑ ≥ 2.000 m») e Inicio. La potencia
(«Ø» media, «máx», «NP» normalizada y kJ, enteros) sólo en la revisión y el
detalle de la propia salida (`_ride_measures.html`, filtro `power_figures`).
Nulo ⇒ no se pinta nada. Sin JavaScript nuevo; `.stats.four` es la única regla
CSS nueva. Los formularios de corrección y de salida manual admiten los cinco
campos (vacío = desconocido explícito, como los demás).

