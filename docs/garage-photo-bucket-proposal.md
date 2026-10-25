# Propuesta: prueba real de fotos privadas (garage-010)

Estado: **propuesta pendiente de autorización del usuario** (11 de octubre de 2026,
Claude). No se ha creado ningún proyecto, bucket ni credencial.

## Qué falta comprobar

El código de fotos está completo y probado con almacenamiento simulado
(docs/garage-storage.md). Falta demostrar contra un proveedor real:

1. Subir una imagen y leerla desde otro cliente (persistencia real).
2. Lectura anónima denegada: el bucket es privado de verdad.
3. Enlace GET firmado válido, y denegado una vez caducado.
4. Sustitución y borrado: los objetos borrados dejan de poder leerse.
5. Errores del proveedor sin secretos ni enlaces en los mensajes.

## Recomendación: Neon Object Storage en un proyecto Neon aparte y desechable

- **Coste cero garantizado:** el plan Free de Neon es permanente, "no credit card
  required", e incluye 5 GB de Object Storage por proyecto. Sin tarjeta no hay
  forma de que aparezca un cargo.
- **El código ya está hecho para Neon:** endpoint de rama, SigV4, direccionamiento
  por ruta y privacidad configurada en la consola (Neon no acepta ACL ni políticas
  por S3, y el adaptador no las envía).
- **Proyecto aparte, no el de producción:** la prueba no toca la base de
  Stravagancia, la credencial sólo alcanza ese proyecto y al final se borra entero.
  Región AWS Europe (Frankfurt), disponible para Object Storage.

Comprobado en la documentación oficial el 11 de octubre de 2026
([overview](https://neon.com/docs/storage/overview),
[compatibilidad S3](https://neon.com/docs/storage/s3-compatibility),
[precios](https://neon.com/pricing)). Matices:

- La documentación no dice si Object Storage está en GA o en preview; indica que
  el soporte "se está extendiendo" a más regiones.
- Lifecycle y versionado se guardan pero no se ejecutan (Garage ya no depende de
  ellos). Puede devolver `503 SlowDown` con carga alta.
- El tráfico de salida de fotos cuenta en los 5 GB de transferencia del proyecto,
  compartidos con PostgreSQL. Irrelevante para esta prueba; a vigilar en producción.

### Alternativa: Cloudflare R2

Ya tienes cuenta de Cloudflare (Worker de keep-alive). La
[página oficial de precios](https://developers.cloudflare.com/r2/pricing/) indica
10 GB-mes gratis, 1 M de operaciones clase A, 10 M clase B y salida gratuita: más
holgado que Neon. Pero no aclara si activar R2 exige registrar un método de pago,
y una guía de terceros dice que lo pide. Con tarjeta registrada, un exceso se
cobraría, y la garantía de coste cero dependería de vigilar el consumo. El adaptador es S3 genérico; habría que
verificar que su validación de configuración acepta la región `auto` de R2.

## Qué harías tú (unos 10 minutos en la consola de Neon)

1. Crear un proyecto nuevo, p. ej. `garage-photos-test`, plan Free, región AWS
   Europe (Frankfurt).
2. En Storage, crear un bucket privado, p. ej. `garage-photos-test`.
3. Crear una credencial de Object Storage para ese proyecto/rama.
4. Guardar los cinco valores en un archivo **fuera del repositorio**, con permisos
   sólo para ti, y **no pegarlos en el chat**:

   ```bash
   mkdir -p ~/.config && touch ~/.config/garage-s3-test.env && chmod 600 ~/.config/garage-s3-test.env
   # Contenido (una variable por línea):
   # GARAGE_S3_ENDPOINT_URL=https://...   (endpoint HTTPS de la rama)
   # GARAGE_S3_REGION=...
   # GARAGE_S3_BUCKET=garage-photos-test
   # GARAGE_S3_ACCESS_KEY_ID=...
   # GARAGE_S3_SECRET_ACCESS_KEY=...
   ```

## Qué haría yo

**Script ya preparado** (12 oct, probado sin red real: archivo ausente, permisos
abiertos y endpoint inexistente fallan limpio, sin secretos en la salida):

```bash
.venv/bin/python -I tools/handoff/garage_bucket_check.py   # o --env-file <ruta>
```

`tools/handoff/garage_bucket_check.py`:

- No carga Django, ni la base de datos, ni `.env`: sólo lee ese archivo y usa el
  adaptador real (`garage.storage`) y el procesado real (`garage.photos`). No
  desactiva las protecciones de los tests (la prueba no corre dentro de pytest).
- Genera una imagen sintética en memoria: ni fotos personales ni FIT.
- Ejecuta las cinco comprobaciones de arriba con dos clientes independientes,
  compara SHA-256 y tamaño, y borra sólo sus propios objetos aunque falle algo.
  Además prueba un enlace con la firma alterada.
- Rechaza el archivo de credenciales si otros usuarios pueden leerlo.
- Imprime únicamente OK/FALLO por paso: nunca claves, enlaces firmados ni secretos.

Puedo ejecutarlo yo sin ver el archivo de credenciales, o puedes lanzarlo tú con
`! python3 tools/handoff/garage_bucket_check.py` para que el secreto no pase por
mí en ningún caso. Después registraría la evidencia en
docs/validation/garage-010.json y cerraría 010 si todo pasa, lo que desbloquea 022.

Recomiendo conservar el proyecto de prueba hasta terminar 022 (revisión de
integración) y luego borrarlo entero desde la consola, con su credencial.

## Fuera de esta propuesta

- El bucket de producción, sus credenciales y las variables en Render son parte
  de garage-023 (despliegue) y requieren otra autorización.
- Nada público, ningún plan de pago, ningún cambio en el proyecto Neon de producción.
