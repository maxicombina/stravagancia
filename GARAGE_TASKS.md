# Tareas de Garage

La revisión del plan está preparada como **28 tareas y 2 epics en Beads**. Tras completar garage-001, el usuario ha autorizado continuar la implementación de las entregas iniciales con subagentes Sol y revisión adversarial, con pruebas de los cambios y ejecución de la suite completa.

## Estado de garage-001 — 4 de octubre de 2026

Implementación completada por un Sol y revisada por dos Sol adversariales. Hay settings independientes, aislamiento temprano de PostgreSQL/HTTP/`.env` y 49 casos nuevos. **Los 144 tests pasan con PostgreSQL 18.6 local**, incluidos los 32 que requieren base de datos, con `DATABASE_URL`, `DB_HOST` y `PGHOSTADDR` remotos sintéticos heredados.

El bloqueo del sandbox quedó resuelto al habilitar la ejecución autorizada. La prueba de PostgreSQL normaliza su dirección mediante `host(inet_server_addr())`, manteniendo la validación estricta de loopback. Se verificó la creación y destrucción de la base de pruebas con un rol dedicado sin privilegios de superusuario; el servidor desechable se detuvo y sus datos se eliminaron. `garage-001` está completada. Comandos y límites en [TESTING.md](TESTING.md). Sin commits, staging, despliegues ni conexiones a Neon.

## Consultar las tareas

Ejecutar desde el repositorio:

```bash
cd /Users/maxicombina/src/learning/django/stravagancia
bd list --limit 0
bd ready --exclude-type epic
bd show garage-001
```

Cada tarea contiene contexto, archivos previstos, alcance, criterios de aceptación y dependencias. `garage-000` agrupa la fase personal inicial; `garage-100` agrupa apps móviles y servicio comercial. Las tareas marcadas `condicional-strava` solo se implementan si la decisión de fuentes las habilita. Si no aplican, se documenta el motivo y se cierran sin construir esa integración.

## Primeras tareas

- `garage-001`: completada; pruebas aisladas y suite verificada con PostgreSQL local.
- `garage-002`: completada; [contrato de dominio](docs/garage-domain.md) aprobado tras revisión adversarial.
- `garage-003`: completada; [decisión de fuentes](docs/garage-data-sources.md) con FIT propio/manual y límites de uso real explícitos.
- `garage-004`: completada; inventario, administración y migración inicial, con 305 pruebas pasando en la suite completa y revisión adversarial.
- `garage-005`: completada; servicios, formularios y permisos por usuario, con 478 pruebas de aplicación pasando (tablero en ampliación excluido de esa ejecución).
- `garage-006`: completada; montajes repetidos, posiciones e intervalos temporales, con revisión adversarial y suite conjunta de 700 pruebas pasando.
- `garage-007`: completada; lecturas previas, cortes por métrica y ámbito, formularios IANA/DST y revisión adversarial; suite conjunta de 806 pruebas pasando.
- `garage-008`: completada; interfaz privada, historial y operaciones de montaje, probadas también en navegador y ancho móvil.
- `garage-011`: completada; salidas propias, procedencia y trabajos de importación, con suite conjunta de 1002 pruebas y 12 subcasos pasando.
- `garage-012`: completada; importador FIT con validación estricta y muestra propia comprobada en memoria.
- `garage-015`: completada; perfiles, excepciones y retiros históricos, con suite conjunta de 1158 pruebas y 12 subcasos pasando, y comprobación en navegador.
- `garage-014`: completada; importación histórica reanudable, asignación por lotes y cobertura verificadas; revisión adversarial aprobada.
- `garage-016`: completada; materialización idempotente del uso por objeto y reconstrucción verificadas; revisión adversarial aprobada.
- `garage-017`: completada; intervenciones, reglas independientes, lecturas vinculadas y fotos de intervenciones. Revisión adversarial Sol aprobada y suite conjunta de 1605 pruebas y 12 subcasos pasando, incluidas carreras reales en borrados de administración.
- `garage-018`: completada; vencimientos independientes, cobertura y estimaciones, revisión adversarial Sol; 1640 pruebas y 12 subcasos pasan, con comprobación del panel en Chrome.
- `garage-019`: completada; estadísticas por bici/material/período, montajes e intervenciones, costes por moneda y cobertura explícita. Revisión adversarial Sol; 1672 pruebas y 12 subcasos pasan, incluidos 32 casos focales y comprobación en móvil.
- `garage-020`: completada; exportación personal JSON v1 exacta y ZIP CSV con manifiesto, sólo datos propios, fallo cerrado ante referencias ajenas o corrupción. Revisión independiente Claude aprobada; 58 focales y suite conjunta de 1730 pruebas y 12 subcasos pasan, y comprobación HTTP en la demo. Por decisión del usuario, las lecturas previas exportan siempre su valor con la etiqueta tal cual.
- `garage-010`: integración local implementada y en curso; adaptador S3 privado, flujos de dominio/interfaz, cuotas y limpieza recuperable. Falta probar persistencia real, acceso anónimo denegado y GET firmado en un bucket privado autorizado.
- `garage-028`: completada; detalle, DAG y recarga automática del HTML, 61 pruebas y verificación en la pestaña real del usuario.
- `garage-009`: completada; procesamiento de fotos con límite de 2000 píxeles, con 47 casos de fotos dentro de la suite conjunta.

Inventario, fotos y motor con datos sintéticos avanzan sin esperar a una integración externa. Hay una muestra FIT original autorizada en Descargas; validada con el importador final, sin incorporarla al repositorio. La integración existente permanece separada de los nuevos contadores.

La validación conjunta más reciente ejecutó **1730 pruebas y 12 subtests, todos pasaron**, con PostgreSQL 18.6 desechable y migraciones hasta 0008. También pasaron `manage.py check` y `makemigrations --check --dry-run`. La integración externa de fotos no forma parte de esa evidencia. `garage-020` está completada (ver [validación](docs/validation/garage-020.json)). `garage-022` sigue bloqueada por `garage-010`, que necesita una prueba en un bucket privado real con autorización explícita del usuario. Ver [estado de relevo](docs/garage-handoff.md).

`garage-013` y `garage-021` están cerradas por **no aplicabilidad**, sin implementar adaptador ni cola Strava para Garage, según la decisión de fuentes. Su estado cerrado no representa funcionalidad entregada.

## Índice

| Tarea | Resultado | Depende de |
| --- | --- | --- |
| `garage-001` | Aislar PostgreSQL y las pruebas existentes — completada | Sin dependencias |
| `garage-002` | Cerrar esquema temporal y reglas de dominio — completada | Sin dependencias |
| `garage-003` | Resolver fuentes del histórico y condiciones de Strava — completada | Sin dependencias |
| `garage-004` | Crear app Garage y modelos de inventario | `garage-001`, `garage-002` |
| `garage-005` | Aplicar propiedad y validación entre usuarios | `garage-004` |
| `garage-006` | Implementar montajes repetidos y posiciones | `garage-005` |
| `garage-007` | Registrar uso previo con instante de corte | `garage-005` |
| `garage-008` | Crear páginas privadas de inventario y montajes | `garage-006`, `garage-007` |
| `garage-009` | Procesar fotos con límite de 2000 píxeles | `garage-005` |
| `garage-010` | Conectar fotos privadas a Neon Object Storage | `garage-008`, `garage-009` |
| `garage-011` | Modelar salidas propias, fuentes e importaciones | `garage-001`, `garage-002`, `garage-005` |
| `garage-012` | Importar archivos propios de actividades Garmin | `garage-003`, `garage-011` |
| `garage-013` | Adaptador Strava — no aplicable, cerrado sin implementar | Decisión `garage-003` |
| `garage-014` | Completar histórico y asignación de bicis por lotes | `garage-003`, `garage-011`, `garage-012` |
| `garage-015` | Asignar material habitual y excepciones por salida | `garage-006`, `garage-011` |
| `garage-016` | Calcular y reconstruir uso sin duplicados | `garage-007`, `garage-011`, `garage-015` |
| `garage-017` | Registrar intervenciones y reglas de mantenimiento — completada | `garage-005`, `garage-007` |
| `garage-018` | Mostrar próximos mantenimientos y avisos internos | `garage-016`, `garage-017` |
| `garage-019` | Añadir estadísticas de bicis y material | `garage-016`, `garage-018` |
| `garage-020` | Exportar inventario e historial propio — completada | `garage-003`, `garage-008`, `garage-011`, `garage-017` |
| `garage-021` | Cola Strava — no aplicable, cerrado sin implementar | Decisión `garage-003` |
| `garage-022` | Revisar integración, acceso y casos de dominio | `garage-008`, `garage-010`, `garage-014`, `garage-018`, `garage-019`, `garage-020` |
| `garage-023` | Preparar despliegue, cuotas y reversión | `garage-022` |
| `garage-024` | Diseñar API móvil versionada y sincronización | `garage-023` |
| `garage-025` | Elegir e iniciar clientes iOS y Android | `garage-024` |
| `garage-026` | Preparar servicio comercial, cuentas y planes | `garage-003`, `garage-023` |
| `garage-027` | Definir notificaciones fuera de la app | `garage-018`, `garage-024` |
| `garage-028` | Mostrar progreso local de Garage en un tablero | Sin dependencias |
| `garage-029` | Revisar garage-003: Strava para uso personal — decidido (opción B) | Sin dependencias |
| `garage-030` | Sincronizar salidas y bicis desde Strava — **aplazada** hasta que el usuario la active | Decisión `garage-029` |
| `garage-031` | Experiencia móvil: web instalable (PWA) para iPhone y Android, estilo B | — |
| `garage-031.1` | Marco común, instalación (PWA), login, estilo genérico, Más y Añadir | — |
| `garage-031.2` | Presentación del desgaste e Inicio | `garage-031.1` |
| `garage-031.3` | Uso mensual, gráfico y ficha de componente | `garage-031.2` |
| `garage-031.4` | Revisión de salida y lista de Salidas | `garage-031.2` |
| `garage-032` | Resto de Garage en el móvil: Taller, ficha de bici, Estadísticas, formularios y listas | `garage-031.4` |
| `garage-032.1` | Hora local en formularios, Taller, registrar mantenimiento, reglas en km/h, detalle de intervención | — |
| `garage-032.2` | Ficha de bici y filtro de salidas por bici | `garage-032.1` |
| `garage-032.3` | Estadísticas por período con gráfico y reparto | `garage-032.1` |
| `garage-032.4` | Listas de inventario y fechas locales en plantillas antiguas | `garage-032.1` |
| `garage-033` | Vida útil por componente: km, horas y tiempo, lo primero que llegue; hereda al reemplazar | `garage-032` |
| `garage-034` | Posponer vencimientos: km, horas, salidas o días, lo primero que llegue (migración aditiva 0009, sólo local) | `garage-033` |
| `garage-035` | Piezas anidadas: verlas, montarlas y mantenerlas en grupo | `garage-034` |
| `garage-036` | Uso en cada intervención y comparar cuánto duró cada pieza | `garage-035` |
| `garage-037` | Desnivel positivo en salidas, reglas y estadísticas — **luego**, a pedido del usuario | `garage-036` |
| `garage-038` | Retirar el reemplazado y retirar con lo montado | `garage-036` |
| `garage-039` | Comparación final de Garage con ProBikeGarage | `garage-034`–`038` |

## Encargo a un agente más ligero

Modelo autorizado actualmente: GPT-6.1 Sol. Entregar una tarea concreta y las secciones relevantes del [plan](GARAGE_PLAN.md), evitando copiar todo el historial de conversación. Revisión previa a avanzar cuando se trate de modelos, migraciones o cálculos. No iniciar varios agentes editando los mismos modelos o migraciones.

Plantilla de encargo:

> Trabaja en la tarea <id> de Stravagancia, en la rama garage. Lee AGENTS.md, GARAGE_TASKS.md y bd show <id>, y comprueba sus dependencias. Implementa solo su alcance y valida sus criterios con PostgreSQL aislado y datos sintéticos. No hagas commits, staging, pushes, despliegues ni escrituras en producción. No cambies .env. Antes de editar, identifica los archivos afectados. Al terminar informa cambios, pruebas, limitaciones y estado real de la tarea.

Para una tarea de diseño, sustituir “implementa” por “documenta y propone”; no generar código de aplicación.

## Tablero local

Abrir [el progreso de Garage](http://127.0.0.1:8765/). Para arrancarlo desde el repositorio:

```bash
.venv/bin/python tools/garage_progress.py --port 8765
```

Pulsa un identificador o título para ver su descripción, criterios, notas y resultado del cierre; las dependencias del detalle también son navegables. El enlace superior **Ver DAG** o la pestaña **DAG de dependencias** muestra todas las tareas como nodos clicables con flechas de requisito a dependiente, sin aplicar los filtros de la lista.

El servidor escucha solo en `127.0.0.1`, lee la exportación de Beads y `docs/garage-progress-state.json`, y refresca la página cada cinco segundos. Tras cambiar tareas hay que exportarlas; el coordinador actualiza agentes y validación. La fecha visible permite distinguir la última actualización de una sesión ya detenida. Si cambia el HTML, la página se recarga automáticamente y conserva la vista de lista o DAG. Enlaces directos: [DAG](http://127.0.0.1:8765/#dag) y [garage-006](http://127.0.0.1:8765/#garage-006).

## Datos y seguimiento

El [plan](GARAGE_PLAN.md) recoge la inspección de Neon del 4 de octubre: 346 actividades, un atleta, dos usuarios Django y cero registros de MissingActivity pendientes. Son contexto y cobertura observada, no un conjunto de pruebas ni garantía de histórico completo.

Beads almacena el seguimiento en un Dolt local dentro de `.beads/`; PostgreSQL/Neon almacena los datos de la aplicación. Son bases diferentes. `.beads/issues.jsonl` es una exportación de tareas y dependencias para lectura y traslado, no un backup completo de Dolt ni de Neon.

Los commits de Dolt y el staging automático de exportaciones están desactivados. No ejecutar `bd init`, `bd sync` ni comandos de push/pull en esta fase. Consultar y actualizar tareas no requiere cambios en producción. El estado y la asignación actuales se consultan con `bd list`; el usuario ha autorizado continuar las entregas iniciales en orden de dependencias.

## Correcciones hechas en esta revisión

- Separar la decisión de fuente histórica de los requisitos para empezar inventario.
- Precisar cortes de uso previo, métricas desconocidas y tratamiento del histórico anterior.
- Añadir posiciones de montaje exclusivas, remontajes y protección de sustituciones simultáneas.
- Distinguir propiedad de datos y procedencia por campo al combinar fuentes.
- Separar procesamiento de fotos de la verificación externa real, y dejar formatos no soportados explícitos.
- Preparar varias cuentas desde los modelos, manteniendo API móvil y facturación fuera de las primeras entregas.


## Demo local de inventario

Hay una demo en http://127.0.0.1:8766/garage/ con datos ficticios y PostgreSQL
independiente en el puerto 55433. Sirve para revisar la interfaz; no representa
el inventario real ni escribe en Neon. El tablero de tareas sigue en 8765.
La demo usa una base temporal que puede reiniciarse al renovar el entorno.
