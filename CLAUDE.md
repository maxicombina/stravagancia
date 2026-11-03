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
- Rama obligatoria: `garage` (antes `codex/garage-plan`; renombrada el 25 oct
  2026 a petición del usuario). **Sin despliegue.** Commits y push sólo cuando
  el usuario los pida: el 25 oct 2026 pidió «commit de todo» (`5e422c8`, todo
  el trabajo de Garage; quedaron fuera la base binaria de Metabase modificada y
  `.serena/`) y autorizó un push de `garage` a `origin` (repo público; sin PR;
  `main` intacto). El 3 nov pidió otro commit del trabajo pendiente (sin push).
  Ningún push ni commit posterior sin que lo pida.
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
  **Única excepción (1 nov 2026, el usuario: «usa .env, sin miedo»):** el helper
  `tools/handoff/garage_local_strava.py` lee de `.env` sólo `STRAVA_CLIENT_ID`,
  `STRAVA_CLIENT_SECRET` y `STRAVA_REFRESH_TOKEN` para el servidor local de
  Strava (garage-048, spec garage-044 §7). El servidor hijo sigue sin abrir
  `.env`; nada más del archivo (las `DB_*` y `NEON_PASSWORD` son de Neon) sale de
  ahí; la IA nunca muestra sus valores y ninguna prueba lee el `.env` real.
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
- Strava como fuente de Garage: decidida (garage-029, 12 oct 2026) y **activada
  por el usuario el 18 oct en «modo token»** (garage-030, fases 1–4 hechas; 0010
  y 0012 sólo locales). Nadie la ha probado contra Strava real: la sincronización
  real la ejecuta el usuario con sus credenciales, exportadas en su shell o,
  desde garage-048, leídas de `.env` por el helper (receta de garage-044 en
  TESTING.md), nunca la IA. OAuth por usuario (garage-040) sin
  empezar. Nunca reutilizar las tablas Activity del legado como histórico propio
  (opción descartada).
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
(id 2), sin salidas aún; entra con `maxi` (contraseña en
`~/.cache/stravagancia/garage-demo-users.json`, fuera del repo). Falta el
histórico de Strava, **bloqueado por garage-044** (26 oct: `settings_test`
elimina las variables `STRAVA_*` y prohíbe el HTTP real, y `strava_app.settings`
apunta a Neon; hace falta un módulo de ajustes local con PostgreSQL 55433 y las
variables Strava del usuario), y `garage_probikegarage_verify` (detalle en
docs/garage-handoff.md).

**29 oct 2026 (Fable + agentes Opus, sesión sin el usuario, 20:30–23:00 CET).**
Los clústeres de `/private/tmp` habían desaparecido con un reinicio: recreados
55434 (pruebas) y 55433 (demo con seed), demo 8766 y tablero 8765 relanzados,
`maxi` (id 2, contraseña «maxi») recreado y **la importación de ProBikeGarage
repetida** (0 errores, 6 avisos; mapa nuevo
`~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-29.json`).
**garage-044**: spec `.claude/specs/2026-10-29-garage-ajustes-locales-strava-spec.md`
(D1–D11, **pendiente de que el usuario la confirme**; D5/D6/D8/D9 cambiaron en
§6), implementación por Opus, revisión adversarial (§5, 11 hallazgos) y
correcciones re-verificadas (§6): `strava_app/settings_local.py`,
`test_support/local_strava.py`, `tools/handoff/garage_local_strava.py`
(`check` / `serve [8767]` / `run`), `tests_local_strava.py` y
`tests_local_strava_review.py`. Suite **2752 + 45**
(docs/validation/garage-044.json). Receta en TESTING.md («garage-044»): la
ejecuta el usuario en su Terminal con sus credenciales, nunca la IA.
**garage-045** (nuevo): fusión de `main` (`dd607f6`, `45a7cf6`) preparada por
Opus en la rama `garage-integrate-main` (worktree aparte; `garage` intacta;
sin push): el usuario la adopta con `git merge --ff-only garage-integrate-main`
desde `garage` o la borra. Al cerrar quedaron **en marcha** la demo 8766, el
tablero 8765 y los PostgreSQL 55433/55434 (un reinicio los borra; receta en el
handoff). Detalle y resultados en docs/garage-handoff.md («Sesión del 29 oct»
y «Al cerrar la sesión del 29 oct»).

**31 oct – 1 nov 2026 (Opus 5.5 como sesión principal tras /model; agentes
Opus): garage-046, réplica a mano de ProBikeGarage.** El usuario pidió «nada de
importación»: pasar sus datos a mano por la interfaz desde su Chrome, «todo», con
los km sacados de Strava tras sincronizar, y «hacé todo lo que puedas, no me
preguntes; dejá anotado». Hecho y verificado: usuario de la demo **`maxi-manual`
(id 3, contraseña igual al nombre)** con todo dado de alta por los formularios de
8766 (419 envíos, 0 errores) e **idéntico campo a campo a `maxi`** (id 2, que
queda como referencia del importador); `garage_probikegarage_verify --owner 3`
con `mapping-demo-maxi-manual-2026-11-01.json` empareja todo (sólo faltan los
usos, sin salidas). Copias de la base en `~/.cache/stravagancia/demo-backups/`
(restauración ensayada). Decisiones tomadas sin consultar y lo que queda: `bd
show garage-046`; fricciones de UI vistas al cargar: **garage-047** (sin
priorizar). **Garage y Stravagancia son apps distintas** (confirmado por el
usuario). Sólo un usuario puede tener el atleta de Strava
(`StravaAccount.athlete_id` único). **1 nov, el usuario eligió `maxi` (id 2)
para Strava**, no `maxi-manual` (que propuso la IA): mismos datos (comparación
tabla por tabla: 0 diferencias) y `maxi` ya trae vinculadas sus 2 bicis de
Strava. `maxi-manual` queda sin Strava, como referencia. La receta de TESTING.md
«garage-044» usa `GARAGE_STRAVA_USER=maxi`. Detalle en docs/garage-handoff.md
(«Sesión del 31 oct – 1 nov»).

**1 nov 2026, con el usuario paso a paso: garage-048.** «Usa .env, sin miedo»:
el helper `garage_local_strava.py` lee de `.env` sólo las 3 claves de Strava
(spec garage-044 §7–§8; el hijo sigue sin abrir `.env`). Implementado por Opus
con TDD, revisión adversarial y correcciones; re-verificado: suite **2801 + 45**
(docs/validation/garage-048.json). Falta que el usuario corra `check` (debe
decir «definida (de .env)») y la sincronización; el histórico se baja con el
botón «Importar histórico» (sin comando nuevo; no reutilizar
`load_missing_activities` del legado, notas de garage-044). Pendiente de
decisión: el gancho de `.env` distingue mayúsculas y APFS no (§8).
**Por la tarde:** el usuario bajó el histórico (350 salidas; verify `--owner 2`
350/350, sólo las 3 diferencias esperadas) y un workflow confirmó campo a campo
que Garage tiene lo mismo que ProBikeGarage (spec 043 §13). **garage-049**:
tres direcciones visuales en `design/` (maquetas; la app no cambia),
recomendada la 3 «Telemetría»; **el usuario eligió la 1 «Anillos»** (049
cerrada). **garage-050**: llevarla a la app; spec
`.claude/specs/2026-11-01-garage-estilo-anillos-spec.md` en **borrador** (falta
la crítica adversarial); fuentes ya descargadas en
`~/.cache/stravagancia/fonts-anillos/`. **El equipo se reinició tras el 1 nov
~19:50 UTC**: recrear 55433/55434, restaurar
`demo-backups/garage-demo-2026-11-01-pre-reboot.dump`, relanzar 8766/8765.
Detalle en el handoff («1 nov ~19:50 UTC» y «1 nov, tarde»).

**3 nov 2026 (Opus 5.5 con el usuario): garage-050 a medias.** La crítica de la
spec «Anillos» terminó (R1–R29), pero su aplicación se cortó tras F1a por un error
de la API: faltan F1b–F4, §7 y §8, incluido R1 (cabecera y §9 de la spec). **No
preguntar §8.1 al usuario hasta terminarla.** El usuario pidió commit del trabajo
pendiente, sin push; quedan fuera la base de Metabase y `.serena/`. Suite 2801 + 45
re-ejecutada ese día. Valores reales de bicis retirados de docs y Beads a
`~/.cache/stravagancia/session-2026-11-03/referencias-reales.md`: nunca al repo.
Detalle en docs/garage-handoff.md («3 nov»).

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
   **garage-043** (25 oct, hecha y verificada; volcado real importado como
   `maxi` en la demo 55433, **el usuario destino de Strava**, elegido por el
   usuario el 1 nov) y **garage-046** (1 nov, réplica a mano idéntica como
   `maxi-manual`, id 3, queda como referencia sin Strava): falta que el
   usuario revise garage-047, confirme la spec de **garage-044**
   (implementada y revisada el 29 oct; D1–D11, sobre todo D4 y D5, y los
   rechazos del helper §4.1.4) y descargue el histórico con su receta
   (TESTING.md «garage-044», con `GARAGE_STRAVA_USER=maxi`); después la IA
   pasa `garage_probikegarage_verify --owner 2` con
   `mapping-demo-maxi-2026-10-29.json`.
   Después, la sincronización real desde Strava en local
   (su usuario de Garage para `GARAGE_STRAVA_USER`; el servidor lo arranca él
   con las claves de `.env` que lee el helper desde garage-048, o exportadas;
   la IA no muestra sus valores; la muestra FIT, spec maestra
   §7.3). Sin probar por nadie: Strava y Cloudflare reales. El despliegue
   (garage-023) es lo último.
2. Pendiente del usuario: confirmar el cambio visible de la deducción de
   iconos (spec 041 §7.7–§8);
   garage-040 (OAuth por usuario) anotado, no empezado.
3. 031: falta sólo instalarla en un teléfono real tras desplegar (023).
4. 010 espera a que el usuario cree bucket/credencial (propuesta y script listos).
5. 022 depende de 010. 023: logger `garage`, `STORAGES`, docker-compose sin migrate.
6. Antes de cualquier tarea: comprobar rama, cambios locales, procesos y entorno.
   **garage-045 (29 oct)**: la fusión de `main` (`dd607f6`, `45a7cf6`, legado
   ya en Render) está preparada en la rama `garage-integrate-main` (merge
   `c3eb532`, worktree aparte; 2733 + 45 en verde allí; revisión por workflow:
   0 defectos de la fusión). Único conflicto real: `strava_integration/tests.py`
   (`views.py`, `settings.py` y `conftest.py` se fusionaron solos). `garage`
   sigue en `576ec9c`, sin push. El usuario la adopta (`git merge --ff-only
   garage-integrate-main` desde `garage`) o la borra. Detalle en
   docs/garage-handoff.md («Sesión del 29 oct»).
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

