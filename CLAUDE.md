# Continuar Stravagancia / Garage

Estas instrucciones sustituyen la guía antigua de este archivo. El usuario pidió
el 10 de octubre de 2026 que **Claude u otra IA continúe el proyecto**, conservando
las decisiones, las tareas, las pruebas y el trabajo local sin commits.

## Leer antes de actuar

1. [Estado exacto y siguiente paso](docs/garage-handoff.md).
2. [Contexto de la conversación y decisiones](docs/garage-context.md).
3. [AGENTS.md](AGENTS.md), [GARAGE_PLAN.md](GARAGE_PLAN.md) y [GARAGE_TASKS.md](GARAGE_TASKS.md).
4. Últimas entregas: `bd show garage-034`/`035`/`036` y sus especificaciones en
   `.claude/specs/` (17–18 oct); antes `bd show garage-032`, `bd show garage-033`;
   `bd show garage-020`, [formato de exportación](docs/garage-export.md) y [pruebas aisladas](TESTING.md).
5. Para cálculos/modelos: [contrato de dominio](docs/garage-domain.md).
   Para importación o exportación: [fuentes admitidas](docs/garage-data-sources.md).

Los documentos son complementarios. Los recuentos históricos de TESTING.md no
validan código posterior. Los informes actuales están en docs/garage-validation.json.

## Autorización y límites vigentes

- Repositorio: /Users/maxicombina/src/learning/django/stravagancia.
- Rama obligatoria: `codex/garage-plan`. **Sin push ni despliegue.** Commits
  sólo cuando el usuario los pida (el 25 oct 2026 pidió «commit de todo»:
  `5e422c8`, un commit con todo el trabajo de Garage; quedaron fuera la base
  binaria de Metabase modificada y `.serena/`).
- Hay muchísimo código nuevo sin seguimiento Git. No ejecutar git clean/reset,
  checkout de archivos, stash ni borrar cambios para preparar el trabajo.
- Continuar implementación necesaria, pruebas y revisión adversarial, en orden
  de dependencias. No pedir permiso otra vez para acciones locales ya autorizadas.
- Las referencias a Sol/Luna son preferencias históricas de delegación; el relevo
  actual es Claude. No hace falta acceder a los subagentes de la sesión anterior.
- Una tarea de producto y un escritor de modelos/migraciones a la vez.
  Revisores independientes no editan los archivos compartidos.
- Neon/producción: **sólo lectura** si hace falta contexto. Ninguna migración,
  prueba, carga ni corrección allí. No leer/modificar .env para preparar pruebas.
- No iniciar Docker Compose completo: su servicio Django apunta a Neon y ejecuta
  migraciones en producción. **Ya ocurrió el 12 oct 2026**: `garage.0001`–`0008`
  están aplicadas en Neon. No editar ni reordenar esas migraciones; las nuevas,
  sólo aditivas. Usar únicamente PostgreSQL local aislado.
- `.venv` es ahora de Linux (lo reconstruyó el contenedor): no tocarlo. En macOS
  usar `GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python`.
- No añadir servicios de pago, SPA, nueva infraestructura, API comercial,
  aplicaciones móviles ni cobros como ampliación rutinaria.
- Bucket/credenciales de fotos y despliegue siguen pendientes de una propuesta
  y autorización concretas. No crear credenciales ni hacer público un bucket.
- Strava como fuente de Garage: decidido (garage-029, 12 oct 2026) pero **aplazado**
  en garage-030. Hasta que el usuario la active: no implementarla, no crear sus
  migraciones ni ejecutar sincronizaciones Strava para Garage. Nunca reutilizar las
  tablas Activity del legado como histórico propio (opción descartada).
- No copiar la muestra FIT personal al repositorio, fixtures, documentos o demo.

## Retomar ahora

**18 oct 2026 (Claude Fable 5.1 orquestando; agentes sólo Opus 5.5).** Cerradas
las ideas de ProBikeGarage 034–036, 038 y 039 (comparación en
docs/garage-vs-probikegarage.md), **garage-030 fases 1–2** (Strava en «modo
token», spec `.claude/specs/2026-10-18-garage-strava-fase1-2-spec.md`),
**garage-041** (juego inicial de 42 categorías con icono, spec
`.claude/specs/2026-10-18-garage-categorias-iniciales-spec.md`) y **garage-030
fase 3 = garage-037** (desnivel y potencia, spec
`.claude/specs/2026-10-18-garage-strava-fase3-spec.md`; revisión en §5,
re-verificación en §6) y **garage-030 fase 4** (operación diaria: `sync-all`
con `GARAGE_SYNC_TOKEN`, ausencia como pista, revocación y purga a 30 días,
Worker de Cloudflare; **sin migración**; spec
`.claude/specs/2026-10-18-garage-strava-fase4-spec.md`; revisión en §5,
re-verificación en §6) y, el 19 oct, **garage-042** (ciclo de vida del material
visible: Montado · Disponible/Sin estrenar · En uso · Retirado, chips en
Material; spec `.claude/specs/2026-10-18-garage-ciclo-vida-material-spec.md`
§6–§8; **sin migración**; primer feedback de UI del usuario). Detalle en
docs/garage-handoff.md. Suite **2618 + 45 subcasos**
(docs/validation/garage-042.json; 2578 antes de la 042). **Todo lo que sea
implementar lo hace un agente Opus** (regla del usuario, 18 oct); Fable
orquesta, documenta, actualiza Beads/estado y verifica.

**25 oct 2026: garage-043, importar ProBikeGarage.** El usuario quiere migrar
sus datos de ProBikeGarage y replicar el estado. Volcado hecho ese día con su
Chrome (sólo GET) en `~/.cache/stravagancia/probikegarage/` (**fuera del repo;
nunca a fixtures, docs ni demo**). Spec con mapeo y decisiones D1–D12:
`.claude/specs/2026-10-25-garage-probikegarage-import-spec.md`. Importador de
un solo uso sobre un Garage vacío + verificación; las salidas se re-descargan
de Strava (030). Sin migración. **Implementado, revisado y re-verificado el
25 oct** (suite **2690 + 45**, docs/validation/garage-043.json). **Importación
real hecha por el usuario el 25 oct** en el clúster demo 55433, usuario `maxi`
(id 2), sin salidas aún. Falta el histórico de Strava (servidor arrancado por
el usuario con `GARAGE_STRAVA_USER=maxi` y su token) y
`garage_probikegarage_verify` (detalle en docs/garage-handoff.md).

**Migraciones sólo locales, no están en Neon: `0009_maintenancesnooze`,
`0010_strava_source`, `0011_category_icon`, `0012_elevation_power`.** Docker
Compose `web` las aplicaría en producción. La siguiente migración es la
**0013**. Nota sólo para el despliegue (garage-023): la 0012 sustituye los
CHECK `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` por
versiones que admiten el desnivel (las filas actuales los cumplen; en Neon las
tablas de Garage están vacías). No preguntar por ello antes de desplegar.

**Orden fijado por el usuario (18 oct):** primero probar todo en local, después
resolver la sincronización real desde Strava, y el despliegue es lo último.

1. **Pruebas locales con el usuario**: está dando feedback sobre la UI de la
   demo 8766 (demo / garage-demo); recogerlo en Beads y priorizarlo con él
   antes de tocar nada (el primero, garage-042, ya implementado; falta que lo
   pruebe y decida la nota menor de las acciones con retirada programada).
   **garage-043** (25 oct, hecha y verificada; volcado real ya importado como
   `maxi` en la demo 55433): falta el histórico de Strava y
   `garage_probikegarage_verify`. Después, la sincronización real desde Strava en local
   (su usuario de Garage para `GARAGE_STRAVA_USER`; el servidor lo arranca él
   con su token de entorno, nunca leer `.env`; la muestra FIT, spec maestra
   §7.3). Sin probar por nadie: Strava y Cloudflare reales. El despliegue
   (garage-023) es lo último.
2. Pendiente del usuario: su usuario de Garage para `GARAGE_STRAVA_USER`;
   confirmar el cambio visible de la deducción de iconos (spec 041 §7.7–§8);
   garage-040 (OAuth por usuario) anotado, no empezado.
3. 031: falta sólo instalarla en un teléfono real tras desplegar (023).
4. 010 espera a que el usuario cree bucket/credencial (propuesta y script listos).
5. 022 depende de 010. 023: logger `garage`, `STORAGES`, docker-compose sin migrate.
6. Antes de cualquier tarea: comprobar rama, cambios locales, procesos y entorno.
   **25 oct**: `main` tiene dos commits nuevos del legado (`dd607f6`, `45a7cf6`,
   renombrado/webhook; ya en Render) que `codex/garage-plan` debe integrar;
   `strava_integration/views.py` dará conflicto. Detalle en docs/garage-handoff.md §Siguiente paso 7.
7. En macOS, `cp`/`rm` piden confirmación (alias): usar `/bin/cp -f` y `/bin/rm -f`
   en mutaciones y restauraciones, y comprobar el hash al restaurar.

## Beads y tablero

```bash
bd list --all --limit 0
bd ready --exclude-type epic
bd show garage-020
bd --sandbox --dolt-auto-commit off --actor claude update garage-020 --append-notes 'Resultado comprobado'
bd --sandbox --dolt-auto-commit off --actor claude export --output .beads/issues.jsonl
```

Verificar que la exportación refleja el estado escrito. No ejecutar bd init,
bd sync, bd dolt push/pull ni commits de Dolt. Beads usa Dolt local, independiente
de PostgreSQL/Neon. Su JSONL contiene todas las tareas, también las cerradas.

Tablero: http://127.0.0.1:8765/ con detalles equivalentes a bd show y DAG clicable.
Actualizar docs/garage-progress-state.json con hora UTC, agentes reales y última
validación acreditada. No dejar agentes ficticios “en curso” entre sesiones.
Demo ficticia: http://127.0.0.1:8766/garage/, credenciales en el estado guardado.

## Pruebas

Leer TESTING.md. Usar `python -m pytest`, settings_test y PostgreSQL real dedicado;
no SQLite, settings de producción ni HTTP/storage reales. El bootstrap bloquea
.env, conexiones remotas y credenciales heredadas. No desactivar estas protecciones.

Se conservan helpers reproducibles en tools/handoff/ (copias de los que se usaron
en esta sesión); inspeccionarlos antes de reutilizar estado temporal. Comandos
exactos, puertos y alternativas sin helpers están en docs/garage-handoff.md.

Actualizar el estado al cambiar de tarea y antes de agotar contexto, sin esperar
al cierre de una sesión larga. Al finalizar cada sesión, dejar estado suficiente
para otra IA: tarea, archivos,
hallazgos pendientes, pruebas realmente ejecutadas, límites, procesos activos
y siguiente acción concreta. No hace falta volver a diseñar Garage desde cero.

