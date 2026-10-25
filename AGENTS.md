# Trabajo en Stravagancia

## Alcance vigente

El 10 de octubre el usuario pidió el relevo a **Claude u otra IA**. Leer primero
[CLAUDE.md](CLAUDE.md), [contexto y decisiones](docs/garage-context.md) y
[estado exacto](docs/garage-handoff.md). Los agentes Sol anteriores no siguen
activos. Claude cerró garage-020 el 11 de octubre con revisión independiente y suite conjunta.
Las referencias a esos modelos describen la delegación histórica; no impiden
continuar con Claude. Se mantienen pruebas, revisión independiente y límites.

El usuario ha autorizado **continuar la implementación de Garage y lanzar subagentes Sol cuando sea necesario**. Pide pruebas de todo lo implementado y revisión adversarial. Seguir las dependencias y criterios de las tareas; `bd ready` indica qué trabajo puede comenzar.

El entorno de pruebas, contrato de dominio, fuentes, inventario, permisos, montajes, lecturas previas, páginas privadas, salidas propias, importación FIT reanudable, perfiles, materialización de uso e intervenciones, reglas, avisos de mantenimiento y estadísticas están completados y revisados. Las fotos están integradas localmente; falta su comprobación en un bucket privado real. La exportación personal JSON/CSV (garage-020) está completada. La última suite conjunta registrada consta de 1730 pruebas y 12 subcasos que pasan. Consultar [el estado guardado](docs/garage-handoff.md), [TESTING.md](TESTING.md), Beads y el tablero para continuar según dependencias. Las apps móviles, monetización y despliegue siguen siendo fases posteriores.

Trabajar en `garage`. No hacer commits, staging, pushes ni despliegues. No ejecutar `bd init`: el repositorio ya está inicializado y ese comando puede crear un commit automáticamente.

## Contexto y tareas

- Leer [GARAGE_PLAN.md](GARAGE_PLAN.md) para requisitos y decisiones.
- Leer [GARAGE_TASKS.md](GARAGE_TASKS.md) para el orden y las reglas de ejecución.
- Las tareas y criterios detallados están en Beads. Desde este repositorio: `bd list`, `bd ready --exclude-type epic` y `bd show <id>`.
- Beads usa un Dolt local, distinto de PostgreSQL en Neon. Su exportación está en `.beads/issues.jsonl`. No ejecutar `bd sync`, `bd dolt push` ni `bd dolt pull` en esta fase.
- La configuración mantiene los commits de Dolt desactivados y la exportación sin staging. Para escrituras usar `bd --sandbox --dolt-auto-commit off ...`.
- Tras actualizar tareas, refrescar su exportación con `bd --sandbox --dolt-auto-commit off export --output .beads/issues.jsonl` y verificar el estado exportado.

## Ejecución autorizada

- Usar GPT-6 Luna para tareas acotadas si el usuario pide ese modelo. Revisar esquema, migraciones y contadores antes de avanzar a sus dependientes.
- Usar Sol según la instrucción actual. Cubrir todos los comportamientos nuevos con pruebas significativas, ejecutar la suite completa y registrar sus límites de cobertura; los revisores adversariales no editan archivos compartidos.
- Tomar una sola tarea disponible, leer sus criterios y declarar los archivos que se van a editar. No editar simultáneamente modelos o migraciones desde varios agentes.
- Mantener lógica de dominio separada de las vistas, propiedad por usuario, montajes repetibles y lecturas de uso con instante de corte.
- No interpretar las menciones a API o importaciones como permiso para conservar indefinidamente datos de terceros: aplicar la decisión de fuentes de `garage-003`, revisada en `garage-029`. El usuario decidió sincronizar desde Strava para uso personal (`garage-030`), pero está **aplazado**: no implementarlo hasta que lo active, y no reutilizar las tablas Activity del legado.
- Usar datos sintéticos y HTTP simulado en pruebas. No leer ni modificar `.env` para preparar fixtures.
- No ejecutar pytest con la configuración de producción. La ejecución de pruebas forma parte de garage-001 una vez preparada y revisada la configuración aislada.
- La base de Neon puede consultarse en lectura si hace falta contexto. No ejecutar migraciones, pruebas ni cargas sobre ella durante esta fase. No imprimir credenciales ni descargar registros personales a documentos o fixtures.
- No ejecutar `docker compose up` sin seleccionar servicios: el servicio Django apunta a Neon de producción. El PostgreSQL local se arranca de forma independiente.
- Al terminar, informar archivos modificados, comprobaciones y limitaciones. Actualizar la tarea únicamente según lo comprobado; no marcar entregas completas por tener código sin validar.

## Herramientas del proyecto

Python, Django, PostgreSQL, uv y pytest. Reutilizar las plantillas y convenciones existentes. No introducir servicios de pago, una SPA o infraestructura adicional como parte de una tarea rutinaria.
