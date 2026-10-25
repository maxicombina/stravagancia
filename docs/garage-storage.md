# Fotos privadas: integración local de garage-010

Revisión de documentación oficial el 4 de octubre de 2026. La implementación
local de garage-010 está integrada y probada con almacenamiento simulado; este
documento no acredita conexión ni persistencia en un bucket real. El procesamiento
de imágenes de garage-009 ya está validado por separado.

## Capacidad y compatibilidad verificadas

Neon Free incluye 1 GB de PostgreSQL y 5 GB de Object Storage por proyecto.
La documentación incluye Frankfurt entre las regiones compatibles. La revisión
previa de la consola encontró el proyecto en Free y todavía sin bucket.
[Anuncio de cuotas](https://neon.com/blog/neon-free-plan-1-gb-per-project),
[Object Storage](https://neon.com/docs/storage/overview).

El cliente puede usar boto3 con endpoint de rama, región y credenciales S3
explícitos. Debe emplear SigV4 y direccionamiento por ruta. La visibilidad privada
se configura en Neon; las escrituras de ACL o política mediante S3 no están
soportadas. No copiar ejemplos de buckets públicos para las fotos de Garage.
[Compatibilidad S3](https://neon.com/docs/storage/s3-compatibility),
[configuración del cliente](https://neon.com/docs/storage/get-started).

Las credenciales se acotan por rama y pueden alcanzar descendientes. El permiso
de escritura incluye lectura. Los enlaces GET firmados permiten entregar una
foto después de comprobar su propietario, sin exponer la clave secreta. La
caducidad declarada de la credencial no está aplicada actualmente; no confundirla
con la caducidad del enlace firmado. Evitar credenciales generales o heredadas
del perfil AWS local como fallback de configuración.
[Autenticación](https://neon.com/docs/storage/authentication),
[objetos y enlaces firmados](https://neon.com/docs/storage/objects).

Neon documenta que las reglas de lifecycle y la configuración de versionado
se almacenan pero no se ejecutan. La limpieza y recuperación de Garage no pueden
depender de ellas. DeleteObject elimina el objeto en la vista de la rama; no
prometer borrado físico inmediato ni deducir de él liberación instantánea de cuota.
[Limitaciones](https://neon.com/docs/storage/s3-compatibility).

## Diseño implementado

- Procesar en el servidor con garage.photos antes de subir: WebP sin metadatos,
  proporción conservada, lado mayor hasta 2000 píxeles y límites ya probados.
- Autorizar destino y propietario antes de acceder al almacenamiento. Nombres
  internos aleatorios; nunca rutas ni nombres de archivo aportados por el cliente.
- Configuración específica de Garage, sin secretos en vistas, errores, fixtures
  o documentos. Endpoint HTTPS fijo del operador; sin URLs arbitrarias de usuario.
- Separar backend S3 de servicios de dominio para probar subidas, lecturas,
  sustitución, borrado y fallos con almacenamiento simulado.
- Resolver explícitamente consistencia entre PostgreSQL y objetos: no son una
  transacción distribuida. La sustitución debe preservar la foto anterior si
  falla la nueva. Registrar y reintentar limpiezas pendientes, incluso cuando la
  compensación inicial falla, sin borrar archivos aún referenciados.
- Contabilizar bytes procesados y aplicar cuotas antes de reservar una subida,
  bajo bloqueo para evitar carreras. Dejar margen al límite del proveedor; una
  estimación de la aplicación no sustituye su medición de consumo real.

## Evidencia necesaria antes de cerrar la conexión externa

Primero implementar y revisar el adaptador, servicios, interfaz y pruebas
aisladas. Preparar después una comprobación revisable con una imagen sintética
en un bucket privado de prueba y credenciales acotadas: subir, verificar contenido
y persistencia desde otro cliente, comprobar denegación anónima, acceso firmado,
sustituir y limpiar únicamente los objetos de la prueba. Verificar los fallos
sin imprimir enlaces firmados ni credenciales. La creación de infraestructura
y credenciales queda pendiente de esa propuesta concreta; no se ha ejecutado.

## Núcleo aislado implementado — 5 de octubre de 2026

`garage.storage` proporciona el transporte privado con boto3 fijado en las
dependencias existentes. Su importación no carga configuración ni abre conexiones.
No sustituye el almacenamiento predeterminado de Django ni modifica los archivos
estáticos. El constructor recibe `PhotoStorageConfig`; el operador puede obtenerla
con `PhotoStorageConfig.from_environment()` cuando conecte el servicio de fotos.

Variables obligatorias, exclusivamente en el entorno del servidor:

| Variable | Contenido |
| --- | --- |
| `GARAGE_S3_ENDPOINT_URL` | Endpoint HTTPS de la rama, sin usuario, contraseña, ruta, consulta ni fragmento |
| `GARAGE_S3_REGION` | Región explícita del bucket |
| `GARAGE_S3_BUCKET` | Nombre del bucket privado ya autorizado |
| `GARAGE_S3_ACCESS_KEY_ID` | Identificador de la credencial acotada a la rama |
| `GARAGE_S3_SECRET_ACCESS_KEY` | Secreto de esa credencial |

No se han escrito valores ni modificado `.env`. Faltan bucket y credenciales
autorizados. No hay valores por defecto ni fallback a variables, perfiles o
archivos de AWS. El cliente dedicado ignora endpoints heredados, proxies y CA
heredados y modelos locales de `~/.aws/models` o `AWS_DATA_PATH`. Carga solamente
modelos distribuidos con botocore/boto3 y fija el modo de defaults del SDK en
`legacy` para evitar consultas de región a IMDS bajo `AWS_DEFAULTS_MODE=auto`.
Conserva la verificación TLS y usa SigV4 por ruta. Limita conexiones
a 3 segundos, lecturas a 10 segundos y solicitudes a dos intentos. No envía ACL,
políticas, lifecycle, versionado ni checksums opcionales del SDK.

Las operaciones disponibles son subir un `ProcessedPhoto`, leerlo de forma
acotada, consultar sus bytes, borrar una clave y firmar únicamente GET. Las
claves tienen la forma `garage/photos/<uuid aleatorio>.webp`; el nombre del archivo
del cliente se ignora. Los bytes procesados se limitan a 15 MiB por objeto y
las dimensiones a 2000 píxeles por lado. La subida devuelve clave, bytes y SHA-256
calculado en el servidor; no usa ETag como checksum. Leer cierra siempre el cuerpo
HTTP y rechaza longitud inválida, exceso, truncado o MIME inesperado. La lectura
no vuelve a decodificar la imagen ni compara su hash con una referencia de DB;
esa comprobación, si se necesita, corresponde al servicio que conoce la referencia.

Los errores del proveedor se traducen a códigos estables y mensajes sin sus
detalles ni su cadena de excepciones. El adaptador no registra credenciales,
enlaces firmados ni nombres originales. No habilitar logging DEBUG de boto3 o
botocore: sus trazas de solicitudes no forman parte del contrato de sanitización
de este adaptador. Los enlaces firmados son capacidades temporales: caducan en
60 segundos por defecto, con un máximo de 300; no deben guardarse ni registrarse.
Su formato SigV4 contiene el identificador de acceso y la firma, nunca el secreto.

El servicio de dominio debe autorizar propietario y destino antes de cualquiera
de estas llamadas; el transporte no recibe usuarios ni consulta la base. Debe
obtener `new_photo_key()` y reservar durablemente esa clave y sus bytes **antes**
de llamar a `upload(photo, key=clave)`. Así conoce qué limpiar incluso si un timeout
ocurre después de que el proveedor guarde el objeto. Nunca reutilizar una clave
de una foto ya referenciada para sustituirla. El transporte no borra objetos
automáticamente tras errores ni ofrece una sustitución transaccional.

### Validación y trabajo pendiente

Pruebas locales sintéticas: configuración incompleta, endpoints inválidos,
aislamiento de credenciales/perfiles/archivos AWS heredados, exclusión de modelos
locales y ausencia de consultas al proveedor de metadatos bajo defaults `auto`,
peticiones S3 exactas sin ACL, subida, lecturas acotadas, contabilización de bytes,
borrado idempotente,
errores sanitizados y firma GET real calculada localmente. Se usan Stubber y
clientes simulados; no se realizan solicitudes a un bucket ni conexiones de DB.

El flujo local completo ya incluye modelos y referencias, autorización por
propietario, cuotas reservadas bajo bloqueo, sustitución/eliminación, consistencia
entre DB y almacenamiento, reintentos de limpieza e interfaz privada. La cuota
estimada es de 250 MiB por usuario y 4 GiB por proyecto, dejando 1 GiB de margen
frente al límite documentado de 5 GiB del proveedor. Es un límite de aplicación,
no una medición del consumo real del bucket.

La migración `0007_private_photos` añade las referencias y reservas duraderas.
Las pruebas específicas de fotos (adaptador, dominio, vistas y limpieza) pasan:
267 casos; la suite completa pasa 1507 pruebas y 12 subtests. La revisión
adversarial no encontró bloqueos locales. El chequeo de Django y la comprobación
de migraciones también pasan.

La **prueba externa de bucket privado y persistencia está explícitamente
pendiente**: imagen sintética, lectura y verificación desde otro cliente,
denegación anónima, GET firmado, sustitución y limpieza solo de sus objetos.
No se ha creado bucket ni credencial, ni se ha cambiado infraestructura, coste
o configuración de producción. garage-010 permanece en curso hasta documentar
esa comprobación con un bucket privado autorizado.
