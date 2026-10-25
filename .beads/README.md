# Seguimiento de Garage con Beads

Este repositorio tiene Beads inicializado con un Dolt local. El seguimiento de tareas es independiente de PostgreSQL/Neon.

El usuario ha autorizado continuar las entregas iniciales de Garage con agentes Sol, pruebas y revisión adversarial. garage-001 está completada con 144 tests pasando sobre PostgreSQL local. Véanse [AGENTS.md](../AGENTS.md), [GARAGE_PLAN.md](../GARAGE_PLAN.md) y [GARAGE_TASKS.md](../GARAGE_TASKS.md).

Desde el repositorio:

```bash
bd list --limit 0
bd ready --exclude-type epic
bd show garage-001
```

Hay 28 tareas y dos epics: fase inicial (`garage-000`) y evolución móvil/comercial (`garage-100`). Los detalles y dependencias están en la base local; `issues.jsonl` contiene una exportación legible y trasladable de las tareas, no un backup completo de Dolt.

Para actualizar las tareas autorizadas, usar `bd --sandbox --dolt-auto-commit off ...`. La configuración desactiva commits de Dolt y staging de la exportación.

No ejecutar `bd init`: ya está inicializado y puede crear un commit Git automáticamente. No hacer commits, staging, sync, pushes, pulls ni despliegues en esta fase.

Si alguna tarea no supera su validación, registrar la limitación sin darla por terminada. Una tarea disponible por dependencias no constituye autorización para implementarla.
