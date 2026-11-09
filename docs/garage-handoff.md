# Estado de Garage para Claude u otra IA

Actualización: 3 de noviembre de 2026 (ver la primera sección). Antes: 1 de noviembre
(sesión 31 oct 22:30 – 1 nov 01:30 UTC aprox.),
Claude Opus 5.5 como sesión principal (el usuario cambió el modelo con /model) con
agentes Opus. Antes: 29 de octubre (19:30–22:00 UTC), Fable 5.1 con agentes Opus. Empezar por CLAUDE.md y
garage-context.md; no rediseñar el proyecto ni ignorar cambios locales. Rama
`garage` (renombrada desde `codex/garage-plan` el 25 oct porque el usuario no
quería «codex» en el nombre). Commits sobre `main`: `5e422c8` (todo el trabajo
de Garage, pedido por el usuario), `24fa1dc` y `e09bfb0` (docs) y el commit de
cierre de esta sesión (estado; ver `git log`). **Push hecho el 25 oct con
autorización expresa del usuario**: `origin/garage` está en `e09bfb0` (repo
público maxicombina/stravagancia; sin PR; `main` intacto). El commit de cierre
queda sin push salvo que el usuario lo pida. Fuera de los commits, a propósito:
`metabase-data/metabase.db/metabase.db.mv.db` (base binaria modificada por
Metabase, ya ignorada pero rastreada) y `.serena/` (caché de herramienta). Los
dos commits del legado en `main` (`dd607f6`, `45a7cf6`) siguen sin integrar
(sección «Siguiente paso», punto 7).

## 8 nov: el trabajo sigue en el VPS; el portátil queda congelado

- Decisión del usuario (8 nov): «congelamos en el portátil, seguimos todo en el VPS».
  **El VPS (`~/src/learning/django/stravagancia`) es la copia
  de trabajo**: ahí otro Claude retoma garage-050 «Anillos» (ver
  `docs/garage-vps-handoff.md`).
- **En el portátil (macOS) no se modifica nada**: ni código, ni docs, ni Beads, ni ramas,
  ni commits ni push, salvo petición expresa del usuario. Una sesión de Claude en el
  portátil sólo responde preguntas. Si se toca algo allí, las dos copias divergen.
- **En el VPS sí se trabaja**, con las reglas de CLAUDE.md y del handoff del VPS (sin push,
  sin commit salvo petición, sin despliegue, sin `.env`).
- Estado en el momento del congelado, idéntico en ambas máquinas: `garage` `28df904`,
  `garage-050-anillos` `66ea10b`, `origin/garage` `e09bfb0`; Beads con 63 tareas (hash del
  export `fa4c8e1d…944c`); mismos cambios sin commitear. El `.env` del VPS quedó en 600.
- Lo que se haga en el VPS no vuelve al portátil solo: traerlo (bundle, o push que pida el
  usuario) es decisión del usuario.

## 9 nov: Anillos terminada y subida a su rama, sin fusionar

- **Hecho.** Workflow `wf_9527df31-077`: 22 agentes Opus en serie, 0 errores, unas 8 h.
  F3 rondas 2 y 3, F4a–c, 3 rondas de F4 y revisión final. 44 hallazgos, 34 corregidos.
  F4d no se ha hecho: es opcional y sólo si el usuario la pide.
- **Estado.** Rama `garage-050-anillos` (`../stravagancia-garage-050`), HEAD `9a2b2a1`.
  `b10c875` es Anillos; `67b8ad6`, la ruta fija del helper de Strava; `9a2b2a1`, el filtro
  de Salidas. Sin migración. Python de producción tocado: `auto_id` en
  `garage/history_views.py` y los enlaces de filtro en `garage/usage_views.py`.
- **Arreglos tras la revisión final.** Workflow `wf_88406334-65d`: 9 agentes Opus en serie,
  0 errores. El helper deduce su repo de la ubicación del archivo; en un worktree usa su
  propio `.venv` y `.env`, y su estado por defecto sigue siendo una ruta de macOS
  (`GARAGE_DEMO_STATE` fuera del Mac). En Salidas, cada enlace cambia un filtro y conserva
  los demás, sin arrastrar la página.
- **Verificado por la sesión principal sobre `9a2b2a1`:** `3556 passed, 464 subtests`,
  0 fallos (482 s). `check` y `makemigrations --check` limpios.
- **Verificado antes de los dos arreglos, sobre `b10c875`:** contraste 44 pares y 88
  comprobaciones sin fallos; capturas 144 de 144 válidas, 0 desbordes, 0 consola, 0 red.
- **Sin verificar:** Safari, iPhone real, PWA instalada, teclado iOS. La demo no tiene
  fotos ni vencidos por encima del 150 %: esos estados se vieron inyectando el marcado.
- **Por decidir con el usuario:** en Salidas, con una bici elegida, «Sólo las que están
  por revisar» da siempre lista vacía (`pending_rides` exige bici nula);
  Material marca Garaje y la maqueta pide Más; claves crudas de posición (`rear_tire`);
  gráfico de 420 px centrado en tarjetas anchas; formatos heredados como «Km: 2795.000»;
  `h1` de Bici en 26 px en móvil (la maqueta pide 30, y 30 incumple F3b); «Guardar foto» y
  «Continuar importación» de FIT en ghost; orden de teclado de la barra lateral (va tras
  el contenido); 60 de 113 pruebas de `tests_ui_guards.py` comparan el texto del CSS o JS
  y no la cascada. Sin medir: «Corregir lectura» en `item_detail.html:101`.
- **Git.** Push de `garage` y `garage-050-anillos` el 9 nov, sin fusionar: el usuario pidió
  «aun NO merge de nada». `garage` no tiene Anillos ni estos arreglos, así que en el VPS
  sigue con los 33 fallos de `tests_local_strava*.py`. No fusionar ni llevar commits de
  una rama a otra hasta que lo pida.
- **Siguiente.** El usuario prueba por el túnel y decide cuándo fusionar en `garage`.
  Después garage-047, garage-053, garage-051 y el repaso garage-052.

## 8 nov: Anillos retomada en el VPS (Linux), sin el Mac

El usuario pidió seguir con garage-050 en el VPS, con agentes Opus en serie, hasta 3
rondas por bloque y **sin commits** de los agentes. Ver también `docs/garage-vps-handoff.md`.

- **Git.** Commit `227a72d` (documentación y estado) y push autorizado por el usuario:
  `origin/garage` en `227a72d` y `origin/garage-050-anillos` en `66ea10b` (`main` intacto;
  fuera, la base de Metabase y `.serena/`). El portátil se puso al día en `227a72d` el
  mismo día (`git merge --ff-only`).
- **Entorno, fuera del repo, en `~/.cache/garage-vps/`:** `venv/` (`uv sync --frozen
  --group dev`), `garage-test` (pruebas, 55434), `garage-demo` (demo ficticia, 55433),
  `demo-restart` (servidor de la copia en 127.0.0.1:8768), `garage-050/snap`
  (instantáneas, porque no hay commits), `garage-050/suite-gate` (suite comparada con la
  referencia). PostgreSQL 17.11 de Debian, sin clúster del sistema. Clúster 55434 en el
  scratchpad de la sesión; demo 55433 en `~/.cache/garage-vps/pg-demo`, con el seed.
  Sin `maxi` ni datos reales, a propósito.
- **Referencia de la suite en `66ea10b`, ejecutada aquí el 8 nov:** 3350 passed y 33
  failed, todos en `tests_local_strava*.py`, porque `garage_local_strava.py:19` fija `REPO`
  a una ruta del Mac y `subprocess.run(cwd=REPO)` da `FileNotFoundError` (comprobado). El
  mensaje «No se pudo ejecutar … GARAGE_TEST_PYTHON» es engañoso. Ajenos a Anillos, sin
  arreglar. El helper no sirve en Linux tal cual. `check`, `makemigrations --check` y
  contraste (88 comprobaciones), limpios.
- **Workflow `wf_9527df31-077`** (Opus, en serie): herramienta de capturas nueva
  (`garage-050/capture.mjs`), F3 rondas 2 y 3, F4a–c, hasta 3 rondas de F4, revisión final;
  se para ante cualquier fallo nuevo. La revisión de código de F3 ronda 2 se rehace porque
  sus hallazgos se quedaron en el workflow del Mac. Sus cambios quedan **sin commit** en
  `../stravagancia-garage-050`. Si esta sesión muere: `snap --list` y el `log` del worktree
  dicen hasta dónde llegó.
- **Probar desde el Mac:** túnel SSH del puerto local 18768 al 8768 de la copia (el 8768 del
  Mac está ocupado) y `http://localhost:18768/garage/`, `demo` / `garage-demo`.
- **Salidas reales nuevas:** las sincroniza el usuario en el Mac (TESTING.md «garage-044»,
  `GARAGE_STRAVA_USER=maxi`, «Sincronizar ahora» pide 7 días). No se hace en el VPS.

## 3 nov (Opus 5.5 con el usuario): estado real de garage-050 y commits

- **Corrección de lo anterior.** Este archivo decía que la crítica de la spec
  «Anillos» seguía en curso, y la cabecera de la spec, que estaba revisada.
  Ninguna de las dos cosas era exacta: la crítica terminó el 1 nov (R1–R29), pero
  el agente que la aplicaba se cortó por un error de la API después de F1a. Falta
  F1b en adelante, §7 y §8, incluido R1, y no existía la §9. La cabecera y la §9
  de la spec ya lo dicen, con los hallazgos literales. Transcripciones: sesión
  `e4119f18`, agentes `a055b8be7be1fde6a` (revisor) y `a14f295409d257c14`
  (aplicador).
- **Procesos.** PostgreSQL 55433 y 55434 siguen de la recreación del 1 nov. Demo
  8766 (`GARAGE_STRAVA_USER=demo`) y tablero 8765 relanzados como tareas de esta
  sesión (mueren con ella). Comprobado en la base: `demo` 79 salidas / 13 objetos,
  `maxi` 350 / 50, `maxi-manual` 0 / 50.
- **Suite re-ejecutada el 3 nov** sobre el árbol completo: 2801 + 45 en 193 s;
  `check` y `makemigrations --check` limpios
  (`/private/tmp/garage-suite-2026-11-03.log`). Sin cambios de código desde el 1 nov.
- **Datos reales retirados.** Nombres de bici, `gear_id` de Strava y km reales
  salieron de `TESTING.md`, este archivo, la spec de la 043 y Beads (044, 047)
  antes del commit. Originales, fuera del repo:
  `~/.cache/stravagancia/session-2026-11-03/referencias-reales.md`. Búsqueda de
  secretos sobre lo pendiente: sólo valores sintéticos.
- **Commits a petición del usuario** («empecemos por 1, luego 2»), locales y **sin
  push** (ver `git log`). Fuera, como el 25 oct: la base de Metabase y `.serena/`.
- **Después:** la aplicación de R1–R29 se terminó ese mismo día (agente Opus; tabla
  en spec §9: 25 corregidos, 4 parciales). Ver la sección siguiente.

## 3 nov: el usuario decide «Anillos» antes de prod

- Literal: «hagamos anillos, dale. no quiero salir a prod con cosas a medio hacer.
  luego habrá mejoras, pero quiero salir lo mejor posible. implementá anillos».
- Worktree `/Users/maxicombina/src/learning/django/stravagancia-garage-050`, rama
  `garage-050-anillos` desde `08eeeae`, sin push (spec §6.0.1). Servidor de la copia
  en 8768. La demo 8766 y el árbol principal no cambian hasta que apruebe.
- Respuesta del usuario: «merge en main: si / foto: lo tengo que pensar. de momento
  haz todo anilos, merges, etc». Se entiende: adoptar en `garage` la fusión de `main`
  (garage-045), **no** fusionar `garage` en `main`, que sería desplegar; §8.1 con las
  opciones recomendadas; sin parar por bloques; sin decidir el bucket (garage-010).

## 3 nov: alcance antes de prod (el usuario lo olvidará y lo preguntará)

- **Antes de prod, decidido:** garage-050 completa, con D21 (burdeos desde 150 %, negro
  desde 200 %); después garage-051: velocidad media, % de subida por km, metros de subida
  por hora, promedio y máximo por salida y vista semanal (sin migración); velocidad
  máxima, cadencia, temperatura y pulsaciones (migración 0013 y nueva descarga); energía
  y potencia como estimación «≈», sólo en estadísticas; en Estadísticas y en la ficha de
  bici y de pieza. Detalle en `bd show garage-051`.
- **Después de prod:** calorías (una llamada a Strava por salida).
- **garage-047, fricciones:** el usuario pidió arreglarlas («apenas puedas, el orden me
  da igual. anotalas cuando las arregles, que repasaremos antes de ir a prod»). Van
  después de garage-050, porque tocan los mismos formularios y hay un solo escritor. Cada
  una se anota en las notas de garage-047 con su commit.
- **garage-052:** repaso con el usuario antes de prod; lo cierra él.
- **Sin decidir:** bucket de fotos (garage-010), objetivo y tendencia de Grafana.

## 4 nov: Anillos a un agente por vez, y garage-053

- Workflow de Anillos `wf_e92e9968-3fe` en marcha en la copia `../stravagancia-garage-050`
  (rama `garage-050-anillos`, sin fusionar). El 3 nov el usuario pidió un solo agente cada
  vez y mantener las 3 rondas: los revisores van en serie. Solo la ronda 1 de F1 conserva
  `parallel()` en el script, para que la reanudación encuentre su caché.
- A las 07:40 del 4 nov: 15 de 19 fases hechas, suite de la copia 3329 passed más el fallo
  esperado (dato de los agentes, sin verificar por mí todavía). Las revisiones de F1 y F2
  llegaron al tope de 3 rondas, con hallazgos medios en la última, corregidos pero sin otra
  ronda que lo confirme. Sin hallazgos de gravedad alta.
- Parciales para el repaso: tema en Safari (solo Chrome) y nombres muy largos a 320 px.
- garage-053 nueva, decidida por el usuario el 4 nov: posponer bici o componente entero.
  Sin decidir: qué más de docs/garage-vs-probikegarage.md entra antes de prod.
- Orden al terminar Anillos: verificar, fusionar en `garage` sin push, y seguir con 047,
  053 y 051, de uno en uno. Después el repaso garage-052, que cierra el usuario.

**4 nov, 09:21: PAUSADO a petición del usuario («pausa apenas puedas, que comienzo a trabajar»).**
No lanzar nada hasta que lo pida. Sin agentes en marcha; copia limpia en `66ea10b`, 72 commits
sobre `28df904`; 16 de 19 fases hechas; suite de la copia 3382 passed más el fallo esperado
(dato del corrector). Quedan: revisor visual de F3 ronda 2 (parado a los 3 min, se repite),
corrector y ronda 3 de F3, F4a–c con su revisión y la revisión final: hasta 26 agentes.
Reanudar cuando lo pida, con `Workflow({scriptPath, resumeFromRunId: "wf_e92e9968-3fe"})`; el
script está en `~/.claude/projects/-Users-maxicombina-src-learning-django-stravagancia/276b1f3f-d1b9-4a12-a522-884416c9ae3b/workflows/scripts/garage-050-anillos-wf_e92e9968-3fe.js`,
y solo sirve desde esta misma sesión. Lanzar antes `caffeinate`, parado también. Si la sesión ya
no existe, seguir a mano desde esa fase: cada fase hecha es un commit de la rama `garage-050-anillos`.

## 1 nov ~21:25 UTC: tras el reinicio, todo levantado de nuevo

- Clústeres recreados con los helpers: pruebas 55434
  (`/private/tmp/garage018-validation-hvbuxnjc`) y demo 55433
  (`/private/tmp/garage018-demo-0tjfjhtw`). Demo restaurada desde
  `garage-demo-2026-11-01-pre-reboot.dump` (sha256 comprobado; `pg_restore`
  y después `migrate`: «No migrations to apply»): 41 tablas; `demo` 79 salidas
  / 13 objetos, `maxi` 350 / 50, `maxi-manual` 0 / 50, igual que antes de apagar.
- Demo 8766 (`GARAGE_STRAVA_USER=demo`, log `/private/tmp/garage-demo-8766.log`)
  y tablero 8765 (`/private/tmp/garage-board-8765.log`) en marcha como tareas en
  segundo plano de la sesión de Claude (mueren con ella).
- garage-050: crítica adversarial de la spec relanzada (agente Opus); después,
  revisión §9.

## 1 nov ~19:50 UTC: guardado antes de reiniciar el equipo (pedido del usuario)

- **Al reiniciar se pierden** los clústeres de `/private/tmp` (demo 55433, pruebas
  55434), la demo 8766 y el tablero 8765. **Copia de la demo justo antes:**
  `~/.cache/stravagancia/demo-backups/garage-demo-2026-11-01-pre-reboot.dump`
  (41 TABLE DATA; `demo` 79 salidas, `maxi` 350, `maxi-manual` 0; sha256 en
  `.sha256` al lado). Restaurar con la receta de abajo («Sesión del 29 oct»):
  clúster nuevo → `pg_restore` → `migrate`, en ese orden.
- **Copiado fuera de /tmp** a `~/.cache/stravagancia/session-2026-11-01/` (chmod 700;
  contiene datos personales, nunca al repo): `design-work/` (scripts de contraste,
  auditorías y capturas de las tres maquetas; sin perfiles de Chrome; los README de
  `design/` citan su ruta antigua en /private/tmp), `scratchpad/` (comparaciones y
  verificaciones del 1 nov), `anillos-spec-inventarios.md` y
  `anillos-spec-borrador.md`.
- **garage-050 («Anillos» en la app):** spec en
  `.claude/specs/2026-11-01-garage-estilo-anillos-spec.md`, **borrador** (§1–§8;
  workflow detenido antes de la crítica adversarial). Siguiente: crítica + revisión
  (§9) con agentes Opus, luego el usuario mira los supuestos D#, luego fase 1.
  Fuentes ya descargadas con permiso del usuario en
  `~/.cache/stravagancia/fonts-anillos/` (PROCEDENCIA.md con sha256).
- **Retomar la conversación:** el usuario trabaja dentro de herdr (gestor de
  terminales para agentes; integración `claude` v10, restauración nativa activada):
  al volver a lanzar `herdr` reabre el panel y ejecuta `claude --resume
  e4119f18-d0d5-41a4-ab0f-a9e0f58a41f8`. Si no, `claude --resume` en el repo.

## 1 nov (tarde, con el usuario): histórico de Strava, confirmación contra PBG y diseño

- **Sincronización real hecha por el usuario** (`serve` en su Terminal, claves de
  `.env` vía el helper): `maxi` (id 2) con su atleta, estado ok. «Importar
  histórico» desde 2010-01-01 (dos trabajos, ambos completados): **350 salidas**,
  sin duplicados, ~205 de otros deportes descartadas. `garage_probikegarage_verify
  --owner 2` con `mapping-demo-maxi-2026-10-29.json`: 350/350 y bicis iguales;
  sólo 3 diferencias esperadas en piezas retiradas (R043-6, D10, R043-11).
  Informe en `~/.cache/stravagancia/probikegarage/verify-maxi-after-strava-2026-11-01.txt`;
  copias de la base `garage-demo-2026-11-01-pre-strava.dump` y `-post-strava.dump`
  en `~/.cache/stravagancia/demo-backups/`. El servidor 8767 lo paró el usuario.
- **Confirmación «tenemos lo mismo que ProBikeGarage»** (workflow
  `wf_9087522f-5b3`, 7 agentes Opus, sólo lectura): salidas 350/350 campo a campo,
  3771/3771 pares salida×pieza, piezas/historial/montajes/reglas iguales salvo
  decisiones documentadas; 287 páginas de Garage renderizadas como `maxi`.
  Resultado y 7 hallazgos nuevos en la spec de garage-043 §13; las diferencias de
  presentación, en garage-047.
- **Tipo de cuadro:** una de las dos bicis figuraba en Strava como «Road Bike»; con
  permiso del usuario la IA la cambió en strava.com a «Mountain Bike» (sólo ese
  campo). La API confirma las dos bicis como «Mtb». Garage no guarda el tipo.
- **garage-049, dirección visual** (pedido del usuario, en paralelo): workflow
  `wf_75ac61aa-411` (3 diseñadores, 3 revisores, 3 correctores, 1 README; Opus).
  `design/option-1` «Anillos» (parecida a PBG, continuista), `option-2`
  «Bitácora», `option-3` «Telemetría»; `design/README.md` compara y **recomienda
  la 3** por fases. Contraste AA 0 fallos en las tres; garaje ficticio, sin datos
  personales. Sólo maquetas: la app no cambia. **Falta que el usuario elija.**
- **Siguiente con el usuario:** su elección de diseño; garage-042 (probar chips de
  Material: Montados 26, Disponibles 5, En uso 0, Retirados 19, Todos 50, en
  `maxi`); priorizar garage-047; garage-045; iconos (041 §7.7); casefold de `.env`.

## 1 nov (mañana, con el usuario paso a paso): Strava a `maxi` y garage-048

- **Usuario para Strava: `maxi` (id 2)**, elegido por el usuario tras comprobar
  que `maxi` y `maxi-manual` tienen los mismos datos (detalle abajo, en la
  sesión del 31 oct – 1 nov). Receta de TESTING.md con `GARAGE_STRAVA_USER=maxi`.
- **garage-048** («usa .env, sin miedo»): el helper lee de `.env` sólo
  `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` y `STRAVA_REFRESH_TOKEN`; el resto
  del archivo se descarta y el hijo sigue sin abrir `.env` ni guardar tokens.
  Spec garage-044 §7 (decisiones) y §8 (resultado, hallazgos). Workflow
  `wf_0b9b17bf-945` (implementar con TDD, revisores de secretos y de casos
  límite, correcciones). Re-verificado por la sesión principal: suite 2801 + 45,
  `check` y `makemigrations --check` limpios. Sin probar: la ruta real
  `<repo>/.env` (la comprueba el usuario con `check`) y Strava real.
- **Histórico:** con el botón «Importar histórico» (≤5 llamadas y ≤200
  actividades por pulsación; ante un 429 para y «Continuar» reanuda). El usuario
  preguntó por reutilizar `load_missing_activities` del legado: descartado
  (tablas del legado y detalle por actividad); cuota compartida con Stravagancia
  en Render. Notas en garage-044.
- **Pendiente de decisión del usuario:** el gancho que impide abrir `.env`
  distingue mayúsculas y APFS no (`.ENV` lo abriría); anterior a 048; propuesta
  `casefold()` en `local_strava.py` e `isolation.py`.

## Sesión del 31 oct – 1 nov: garage-046, réplica a mano de ProBikeGarage por la UI

**Petición del usuario.** «Nada de importación, sino que vayas recorriendo en el
browser lo que tengo y lo pases tú a mano»; «empezar por todo»; «los km que
salgan de Strava, cuando hayamos hecho una sync»; y al final «todo lo que puedas,
hacé, no me preguntes; dejá anotado y lo hablamos luego». También confirmó que
Garage y Stravagancia son **dos apps diferentes** (ya decidido en garage-029/030:
Garage baja sus propias salidas; nunca reutilizar `Activity` del legado; sólo
comparten la credencial de la aplicación de Strava).

**Resultado (verificado).** Nuevo usuario de la demo **`maxi-manual` (id 3,
contraseña igual al nombre, usuario normal)** con **todo** lo de ProBikeGarage
dado de alta por los formularios de 8766 desde el Chrome del usuario: 46
categorías (42 del juego inicial + Frenos, Insertos tubeless, Rodamientos,
Roldanas; los objetos usan 17), 30 tipos, 2 bicis, 50 objetos (19 retirados con
su fecha), 62 montajes (23 anidados, 26 abiertos), 59 reglas (38 repetibles + 21
vidas útiles «Sustitución», 2 sin ancla), 8 lecturas de uso inicial (4 piezas) y
184 intervenciones: 419 envíos, 0 errores de validación. El primer envío de cada
tipo de formulario se hizo a la vista (rellenar, abrir la zona, UTC, Guardar); el
resto con `fetch` POST desde la misma pestaña con sesión (mismas vistas y
validaciones). **Comparado campo a campo con `maxi` (id 2, la salida revisada del
importador): 0 diferencias**; notas sin CR ni espacios sobrantes.
`garage_probikegarage_verify` con `--owner 3` y el mapa nuevo sale idéntico byte
a byte al de `--owner 2`: todo empareja; sólo difieren los usos (0 de 350
salidas), como se espera sin Strava. Contraste visual de 5 componentes (3
activos, 2 retirados, uno con anidados) en PBG frente a Garage: coinciden.
ProBikeGarage en vivo es idéntico al volcado del 25 oct (hashes de 8 familias;
PBG no sincroniza Strava desde el 18 oct); en PBG sólo se leyó.

**Decisiones tomadas por la IA sin consultar (revisar con el usuario; detalle en
`bd show garage-046`).** (1) Usuario nuevo en vez de vaciar `maxi` (ni la UI ni
el admin pueden: FK PROTECT, sin borrado de bicis/objetos/montajes/lecturas).
(2) Por `StravaAccount.athlete_id` único, el primero que sincronice se queda el
atleta: con `maxi-manual`, `maxi` ya no podrá. (3) Valores del plan puro
`build_plan()` del importador (no se ejecutó el importador). (4) Fechas en UTC con
`time_zone=UTC` en cada envío. (5) Copias antes y después de cada fase. El
crítico propuso como alternativa sincronizar directamente `maxi`; no se siguió
por la petición expresa del usuario.

**Archivos (fuera del repo; datos personales):**
`~/.cache/stravagancia/probikegarage/manual-replica/worksheet.json` (hoja, 419
envíos) y `state.json` (id de PBG → UUID de `maxi-manual`);
mapa `~/.cache/stravagancia/probikegarage/mapping-demo-maxi-manual-2026-11-01.json`;
copias en `~/.cache/stravagancia/demo-backups/` (`…-baseline`, `…-0026-pre-replica`,
`…-0047-inventario`, `…-0057-montajes`, `…-0106-reglas`, `…-0115-intervenciones`;
41 TABLE DATA cada una). **Restauración ensayada** en un clúster desechable
(55435, borrado): 41 tablas, 1262 filas, 0 diferencias. La receta de
restauración tras un reinicio: `garage_demo_pg.py start` (clúster vacío) →
`pg_restore` de la última copia → `migrate` (en ese orden; si se migra antes,
`pg_restore` falla).

**1 nov, más tarde (con el usuario): Strava va a `maxi`, no a `maxi-manual`.**
El usuario preguntó si los dos tenían los mismos datos y, tras la respuesta,
eligió `maxi` (id 2). Comprobado ese día, sólo lectura: exportación de las tablas
de los dos dueños y comparación tabla por tabla, **0 diferencias**; recuentos
iguales (30 tipos, 2 bicis, 50 objetos, 62 montajes, 59 reglas, 8 lecturas, 184
intervenciones); `garage_probikegarage_verify` de `--owner 2` y `--owner 3`
idénticos (333 líneas). Sólo cambian las categorías (`maxi` 17, las usadas;
`maxi-manual` 46 con las de serie, usa las mismas 17) y que `maxi` tiene sus 2
`StravaGear` ya vinculadas; la sincronización las
reutiliza por `(owner, gear_id)` (`garage/services/strava_sources.py`). Ninguna
`StravaAccount` existía. `maxi-manual` queda sin Strava, como referencia (no se
borra sin que el usuario lo pida). Esto sustituye la decisión (2) de arriba.

**Lo que queda al usuario (en este orden).** Confirmar la spec de garage-044
(D1–D11, sobre todo D4 y D5); en su Terminal, la receta de TESTING.md
«garage-044» **con `GARAGE_STRAVA_USER=maxi`**: «Sincronizar ahora», comprobar
en Más → Strava → «Bicis de Strava» que las 2 bicis salen vinculadas,
«Importar histórico» una vez **cambiando la fecha a 2012-01-01** y «Continuar»
hasta completado. Después la IA lanza la verificación (sólo lectura, con
`garage_demo_pg.py run … --owner 2` y `mapping-demo-maxi-2026-10-29.json`) y lista las
salidas de Strava que PBG no tenía (VirtualRide/GravelRide/EBike, posteriores al
25 oct o editadas), que el usuario decide aceptar o excluir. Referencia de PBG por bici: fuera del repo, en
`~/.cache/stravagancia/session-2026-11-03/referencias-reales.md`; diferencias esperadas en la verificación:
las 8 explicadas en la spec del importador (§10 y D10).

**Feedback de UI encontrado al cargar:** recogido en **garage-047** (sin
priorizar; no tocar nada hasta hablarlo con el usuario).

**Efecto en el Chrome del usuario:** su pestaña de 8766 queda con la sesión de
`maxi-manual` (8766 comparte cookies: la de `maxi` se cerró). Procesos al cerrar:
demo 8766 (PID 46807, `GARAGE_STRAVA_USER=demo`), tablero 8765 y PostgreSQL
55433/55434 siguen en marcha desde el 29 oct; nada en 8767. Repo: sin cambios de
código; sólo documentación y Beads; sin commits ni push.

## Sesión del 29 oct (Fable orquestando, agentes Opus): clústeres recreados, garage-044 y garage-045

El usuario pidió aprovechar un par de horas sin él («haz lo que puedas de lo que
haya pendiente, usa subagentes, a las 23:00 corta»). Hecho:

- **Los clústeres de /private/tmp habían desaparecido** (reinicio del Mac
  después del 26 oct). Recreados: pruebas 55434 (`garage_test_pg.py start`,
  estado `/private/tmp/garage018_pg_state.json`, datos
  `/private/tmp/garage018-validation-nm4spa8e`) y demo 55433
  (`garage_demo_pg.py start` + `migrate` + `tools/garage_demo_seed.py`; estado
  `/private/tmp/garage_demo_pg_state.json`, datos `/private/tmp/garage018-demo-hz3itws9`).
  Demo 8766 (`GARAGE_STRAVA_USER=demo`) y tablero 8765 relanzados en segundo
  plano (`/private/tmp/garage-demo-8766.log`, `/private/tmp/garage-board-8765.log`).
- **`maxi` recreado en la demo** (id 2, staff y superusuario, contraseña «maxi»
  como pidió el 25 oct; anotado en `~/.cache/stravagancia/garage-demo-users.json`)
  y **la importación de ProBikeGarage repetida por Fable** (esta vez el
  clasificador de permisos no la bloqueó): 0 errores, los mismos 6 avisos del
  25 oct, 17 categorías, 2 bicis vinculadas a Strava, 50 objetos (19
  retirados), 62 montajes, 30 tipos, 38 reglas + 21 vidas útiles, 184
  intervenciones, 8 lecturas, 0 salidas. **Mapa nuevo**
  `~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-29.json` (el
  del 25 oct ya no sirve: los UUID cambiaron con el clúster). Entrada de `maxi`
  verificada por HTTP (`/accounts/login/` → 302 y `/garage/` con sesión).
  `garage_probikegarage_verify` con el mapa nuevo funciona y muestra, como se
  esperaba sin salidas, sólo diferencias de uso (−210/−133 salidas por bici y
  sus km/h/m, y lo mismo por componente); la salida quedó fuera del repo.
- **garage-044** (ajustes locales con Strava real): spec diseñada por Fable en
  `.claude/specs/2026-10-29-garage-ajustes-locales-strava-spec.md` (D1–D11,
  pruebas §2, entrega §3; **el usuario no la ha confirmado aún**: todo es
  aditivo y reversible) e implementada por un agente Opus (resultado más abajo,
  «Resultado de los agentes»).
- **garage-045** (nuevo bead): integrar `dd607f6` y `45a7cf6` de `main` en
  `garage`. Un agente Opus preparó la fusión en un worktree aparte con la rama
  `garage-integrate-main` (merge commit **sólo** en esa rama; `garage` y su
  árbol de trabajo intactos; sin push). El usuario decide adoptarla o borrarla
  (comandos más abajo).

### Resultado de los agentes (29 oct)

**garage-045, fusión de `main` (agente Opus, 20:40–20:55 CET; verificada por
Fable con `git log`/`git worktree list`):** rama `garage-integrate-main`,
merge commit `c3eb532` (padres `576ec9c` = `garage` y `45a7cf6` = `main`),
worktree en `<scratchpad de la sesión>/wt-integrate-main`
(`/private/tmp/claude-501/-Users-maxicombina-src-learning-django-stravagancia/ef971d05-45f5-465c-aa33-345363cac96c/scratchpad/wt-integrate-main`;
`git worktree list` lo muestra). `garage` y su árbol de trabajo intactos; sin
push; sin `Co-Authored-By` (regla del usuario). Hallazgos:

- Conflicto real sólo en `strava_integration/tests.py`: se conservaron las
  pruebas de ambos lados; a las de `main` se les añadió `owner_id` (en `garage`
  el legado sólo procesa eventos de su atleta). `views.py` se fusionó solo (el
  handoff anterior lo daba por conflicto): orden JSON-objeto →
  `subscription_matches` → `accept_event` de Garage (pista guardada, hilo tras
  el commit) → filtro `Athlete.strava_id` → `create` lanza el hilo
  `create-<id>` y responde; `update` síncrono sin renombrar; `delete` igual.
  `settings.py`: barrera de pytest, `_force_ipv4_outbound`
  (`GEOCODING_FORCE_IPV4`/`RENDER`) tras `load_dotenv`, bloque de Garage
  intacto. `conftest.py`: `install()` arriba, reinicio de geocodificación y
  fixture `app_caplog` de `main`.
- Arreglos que exigió la fusión (13 + 1 pruebas fallaban al principio): la
  tabla de verdad IPv4 de `main` importaba `strava_app.settings` (rechazado
  bajo pytest) → ahora compila la función con `ast`; la prueba de subproceso
  de `main` habría leído el `.env` real → `PYTHON_DOTENV_DISABLED=1` + audit
  hook; `test_webhook_ignores_events_of_other_athletes` añade
  `thread_cls.assert_not_called()`;
  `garage/tests_strava_sync.py::test_legacy_and_garage_both_receive_the_owner_athlete`
  adaptado al flujo `create-<id>` (único archivo de `garage/` tocado).
- Suite en el worktree (PostgreSQL 55435 propio, ya parado y borrado):
  **2733 + 45 subcasos** en 188,75 s (2690 de `garage` + 43 de `main`);
  `check` y `makemigrations --check` limpios.
- **Adoptar** (desde `garage`, checkout principal): `git merge --ff-only
  garage-integrate-main`; después `git worktree remove <ruta>` y `git branch
  -d garage-integrate-main`. Los archivos sin seguimiento de garage-044 no
  tocan los 7 archivos de la fusión. Si antes se hace otro commit en `garage`,
  usar `git merge garage-integrate-main`. **Descartar**: `git worktree remove
  --force <ruta> && git branch -D garage-integrate-main`. Riesgo: las pruebas
  de 044 no se ejecutaron contra la fusión; tras adoptarla, pasar la suite
  completa en el checkout principal. Registros en
  `<scratchpad>/full-suite.log` (fallos iniciales) y `full-suite-2.log` (verde).
- **Revisión de la fusión por Workflow (ultracode, 21:12–21:22 CET; 7 agentes
  Opus: 3 revisores —webhook, pruebas, ajustes/geocodificación— y 2
  verificadores escépticos por hallazgo): 0 defectos introducidos por la
  fusión.** `views.py` = `main` + hunks de `garage`; `settings.py` = `main` +
  bloque de Garage; `renaming.py`/`tests_renaming.py` idénticos a `main`;
  `tests.py` 42 pruebas = 37 de `main` + 5 propias de `garage`
  (`test_webhook_create_dispatches_rename_thread` pasó a llamarse en `main`
  `test_webhook_create_answers_before_fetching`, que cubre lo mismo y más).
  Dos hallazgos **anteriores a la fusión** (legado; no corregidos, anotados en
  garage-045): un POST al webhook con cuerpo no UTF-8 da 500 en vez de 400
  (`json.loads` lanza `UnicodeDecodeError`, no `JSONDecodeError`; arreglo:
  `except ValueError`), y las pruebas negativas de `update`/`delete` del
  legado no distinguen «filtrado por atleta» de «rama ejecutada» (falta una
  prueba positiva de `update` de un Ride propio). Veredicto: adoptable.

**garage-044 (agente Opus implementador, 20:40–21:00 CET; revisor adversarial
Opus, 21:05–21:22):** implementada **sin migración** y sin tocar
`strava_integration/`, `garage/`, `settings.py`, `settings_test.py`,
`isolation.py`, `manage.py` ni `conftest.py`. Archivos nuevos:
`strava_app/settings_local.py`, `test_support/local_strava.py`
(`install_local()` + funciones puras), `tools/handoff/garage_local_strava.py`
(`check` / `serve [puerto]` / `run <comando de manage.py>`),
`tests_local_strava.py`; docs: TESTING.md («garage-044», con la receta del
usuario), docs/garage-data-sources.md, tools/handoff/README.md,
docs/validation/garage-044.json. Primera verificación: suite **2738 + 45**
(191,37 s). Desviaciones del implementador en la spec §4. **Revisión
adversarial (spec §5, `tests_local_strava_review.py`, 7 pruebas
`test_r044_n`): 11 hallazgos**, dos importantes: (R1) un `--` en `run` dejaba
el `--settings` suelto y `manage.py` habría cargado producción (Neon);
(R2) con `GARAGE_LOCAL_DEBUG=1` la página 500 mostraba `client_secret` y
`refresh_token` si el guardián de red saltaba dentro de
`refresh_access_token()`. Menores: sin `django.request` en `LOGGING` un 500 no
deja traza; el guardián no filtraba el método HTTP (un `PUT` a Strava
pasaría); la receta dejaba el `export` en `~/.zsh_history`. Nits:
`diffsettings` imprime `GARAGE_SYNC_TOKEN`; cookies de sesión compartidas con
la demo; `serve` en 8766 choca con la demo; recuento de funciones;
duplicaciones. Fable decidió aplicar R1–R10 (DJANGO_SETTINGS_MODULE en el
hijo + `--settings` tras el subcomando; sin `GARAGE_LOCAL_DEBUG`; guardianes
con `OSError` → `ConnectionError` → «network»; `django.request` ERROR; sólo
`GET /api/v3/…` y `POST /oauth/token`; cookies propias; `serve` en 8767;
`diffsettings` rechazado; `export` con espacio delante y nunca con `!` en
Claude Code). **Correcciones aplicadas y re-verificadas (implementador Opus,
21:25–21:35 CET; spec §6)**: R1–R10 hechas, R11 ya cubierto; `NetworkDenied`
deriva de `requests.exceptions.ConnectionError` (y por tanto de `OSError`)
para que también el rechazo de `Session.send` acabe como «network» en Garage;
única prueba del revisor adaptada, `test_r044_4` (`except NetworkDenied`);
7 mutaciones comprobadas. Re-verificación: 113 pruebas de los tres archivos
(9 + 53 + 51), `check` y `makemigrations --check` limpios, **suite completa
2752 + 45 subcasos (189,08 s)**, 0 bases residuales, `check` sintético contra
la demo OK y `run diffsettings` rechazado (Fable repitió las pruebas rápidas,
`inspect` y los dos `check`: iguales). `docs/validation/garage-044.json`
(status `implemented_reviewed_fixed`, bloque `review`). Segunda ronda de
revisión por workflow (lentes «fuga/escape» y «receta de punta a punta con
valores sintéticos») lanzada a las 21:38; su resultado, más abajo si llegó
antes del corte. **Pendiente del usuario: confirmar D1–D11 con los cambios de
§6 (D5, D6, D8, D9 cambiaron) y ejecutar la receta en su Terminal** (nunca la
IA): ` export` de las credenciales **solo y con espacio delante** (un bloque
pegado se guardaría en el historial), `check`, `serve` (8767), «Sincronizar
ahora», «Importar histórico» desde 2012-01-01 **una sola vez** y después
«Continuar importación» hasta completado, `garage_probikegarage_verify` con el
mapa del 29 oct y, al acabar, `unset` de las tres variables.
- **Segunda ronda de revisión por Workflow (21:38–22:04 CET; 8 agentes Opus:
  lentes «fuga/escape» y «receta de punta a punta con valores sintéticos», un
  verificador por hallazgo): 0 defectos en el código corregido.** La receta
  funciona con valores sintéticos: `check`, `serve 8767`, login, Garaje, Más →
  Strava (sin llamar a Strava), listas, estáticos, PWA; cookies
  `garage_local_sessionid`/`garage_local_csrftoken`; convive con la demo 8766;
  `run garage_probikegarage_verify --help` y `run migrate --plan` funcionan;
  `test`/`shell`/`diffsettings`/`migrate -- x` rechazados. Dos hallazgos
  confirmados, de documentación, ya corregidos (TESTING.md, spec D9, README):
  pegar el bloque de la receta relleno guardaría las credenciales en
  `~/.zsh_history` (zsh sólo mira el primer carácter del comando entero: la
  línea va sola) y «2 pulsaciones» de «Importar histórico» era engañoso
  (la segunda crea otro trabajo desde la página 1; se sigue con «Continuar
  importación»). Notas sin cambio: `check` no comprueba que el clúster 55433
  responda (falla alto y claro en `serve`); las variables exportadas siguen en
  la shell después (`unset` al acabar; visibles con `ps -E` para el mismo
  usuario).

### Al cerrar la sesión del 29 oct (~22:15 CET)

- **Quedan en marcha a propósito** (el usuario pidió cortar el trabajo a las
  23:00, no apagar lo local): demo 8766 (`settings_test`, `GARAGE_STRAVA_USER=demo`,
  log `/private/tmp/garage-demo-8766.log`), tablero 8765
  (`/private/tmp/garage-board-8765.log`), PostgreSQL 55433 (demo, con `maxi`
  importado) y 55434 (pruebas). Para parar sin perder la demo: `kill` de los
  dos `runserver`/`garage_progress.py` y `pg_ctl -D <root>/data -m fast stop`
  con los roots de los ficheros de estado (nunca la acción `stop` del helper de
  la demo). Un reinicio del Mac borra `/private/tmp`: receta de recuperación en
  «Última entrega: garage-043», último punto.
- Worktree `wt-integrate-main` (scratchpad de la sesión) y rama
  `garage-integrate-main` (`c3eb532`) a la espera del usuario (adoptar o
  borrar; comandos arriba). Si el scratchpad desaparece, `git worktree prune`;
  la rama sigue.
- Sin commits en `garage` ni push. Cambios sin seguimiento: los archivos de
  garage-044 (`strava_app/settings_local.py`, `test_support/local_strava.py`,
  `tools/handoff/garage_local_strava.py`, `tests_local_strava.py`,
  `tests_local_strava_review.py`, spec y `docs/validation/garage-044.json`);
  modificados: CLAUDE.md, TESTING.md, GARAGE_TASKS.md, docs (handoff,
  contexto, data-sources, progress-state), `tools/handoff/README.md`,
  `.beads/issues.jsonl` (garage-044 in_progress con notas, garage-045 nuevo).
- **Siguiente acción concreta**: el usuario (1) decide garage-045 (`git merge
  --ff-only garage-integrate-main` desde `garage` y, después, suite completa
  en el checkout principal con las pruebas de 044), (2) confirma la spec de
  garage-044 (D1–D11 con §6) y (3) ejecuta la receta de TESTING.md
  («garage-044») en su Terminal: histórico de Strava de `maxi` y
  `garage_probikegarage_verify`. Nada de esto lo hace la IA. Después,
  feedback de UI en la demo y, al final, el despliegue (garage-023).

## Aviso importante: migraciones de Garage aplicadas en producción (Neon)

El 12 oct a las 16:15 (hora de Madrid) se creó el contenedor Docker
`stravagancia_django` junto con el de Grafana (`docker compose up`). Su
entrypoint ejecuta `migrate` contra la base de producción (DATABASE_URL de Neon
en docker-compose.yml) y, al montar el repositorio con Garage, aplicó
`garage.0001`–`0008` en Neon. Lo muestran los registros locales de Docker. No
lo hizo ninguna IA, y nadie consultó ni escribió en Neon para verificarlo.
Consecuencias:

- Las migraciones `garage.0001`–`0008` **no se pueden editar ni reordenar**; las
  nuevas deben ser aditivas.
- No volver a levantar el servicio `web` de docker compose (sólo `grafana` si
  hace falta): ejecutaría `migrate` en producción con lo que haya en el repo.
  **Desde el 18 oct hay cuatro migraciones locales que no están en Neon**:
  `garage.0009_maintenancesnooze` (garage-034), `garage.0010_strava_source`
  (garage-030 fases 1–2), `garage.0011_category_icon` (garage-041) y
  `garage.0012_elevation_power` (garage-030 fase 3). Levantar `web` las
  aplicaría allí. `CLAUDE.md` («Retomar ahora») las nombra y dice que la
  siguiente es la 0013.
- La 0012 **no es sólo aditiva**: sustituye los CHECK
  `garage_maintenancerule_has_threshold` y `garage_snooze_has_amount` por
  versiones que aceptan el desnivel (las filas actuales los cumplen). Hay que
  decírselo al usuario explícitamente y que lo apruebe antes de desplegarla
  (garage-023).
- Pendiente del usuario: decidir si deja esas tablas (vacías, inofensivas para
  la app antigua) o si autoriza revertirlas, y si cambia docker-compose para que
  `web` no migre contra Neon.

El mismo contenedor reconstruyó `.venv` el 13 oct con paquetes **Linux**
(`/usr/local/bin/python3.11`, `*.cpython-311-aarch64-linux-gnu.so`). Ese `.venv`
pertenece ahora a la imagen Docker: no tocarlo. Para trabajar en macOS hay un
entorno aparte creado con `uv sync --frozen`:

```bash
export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
```

Los helpers `tools/handoff/garage_{test,demo}_pg.py` usan esa variable si existe.

## Última entrega: garage-043, importar ProBikeGarage (25 oct, en curso)

El usuario quiere **migrar sus datos de ProBikeGarage** a Garage y replicar el
estado (material con fecha de instalación, km, horas, desnivel, intervalos,
intervenciones, salidas); «si hay que re-bajar de Strava, se re-baja».
Especificación con el mapeo y las decisiones D1–D12:
`.claude/specs/2026-10-25-garage-probikegarage-import-spec.md`. Bead
`garage-043` (depende de 030). **Sin migración** (la 0013 sigue reservada).

- **Volcado hecho el 25 oct** desde el Chrome del usuario con su sesión
  (extensión Claude in Chrome; sólo `GET` a `api.probikegarage.com`; no se
  cambió nada en ProBikeGarage; la pestaña se cerró al terminar). Archivos en
  `~/.cache/stravagancia/probikegarage/` (**fuera del repo; datos personales:
  nunca a fixtures, docs ni demo**): `probikegarage-2026-10-25-compact.json`
  (formato v2 que lee el importador; 2 bicis, 50 componentes —19 retirados,
  que la API oculta salvo con `filter=all`—, 62 montajes, 59 intervalos, 177
  intervenciones, 350 salidas) y `probikegarage-2026-10-25-raw.json`
  (respuestas crudas por ruta). Técnica que funcionó para sacar 3 MB del
  navegador: el token de la API queda en la página (`window.__pbgHeaders`,
  capturado parcheando `fetch`; nunca se mostró), las respuestas se juntan en
  un `<textarea>` y se copian con teclas reales (`cmd+a`, `cmd+c` del tool
  `computer`) → `pbpaste` en el Mac. No sirvieron: `javascript_tool` (trunca a
  ~1 KB), `navigator.clipboard`/`execCommand('copy')` (sin gesto), `fetch` a
  `127.0.0.1` (Chrome lo bloquea: Local Network Access) ni descargas (piden
  permiso). REA no hizo falta (el análisis del 17 oct ya daba la API). El
  puerto CDP 9222 no estaba abierto.
- **Plan**: importador de un solo uso sobre un Garage vacío
  (`garage_import_probikegarage`, `--dry-run`, `--mapping`) + verificación
  (`garage_probikegarage_verify`) que compara bicis, componentes, reglas y
  salidas con el volcado. Las salidas vienen de Strava (garage-030, «Importar
  histórico» desde 2012-01-01) con `StravaGear` ya vinculado; las del volcado
  sólo verifican. Intervalos `repeat=false` («Max life») → vida útil;
  `elapsed-time` → días; uso inicial → lecturas de vida estimadas; horquilla
  «desde siempre» → desde el montaje más antiguo de su bici; desnivel del uso
  inicial omitido (sin migración).
- **Estado (25 oct, 18:50 UTC): implementada, revisada, corregida y
  re-verificada** por agentes Opus (spec §9 implementación, §10 revisión con
  11 hallazgos minor/nit, §11 correcciones, §12 re-verificación; informe
  `docs/validation/garage-043.json`). Código nuevo:
  `garage/importers/probikegarage.py`, `garage/services/probikegarage_import.py`,
  comandos `garage_import_probikegarage` (`--owner`, `--dry-run`, `--mapping`,
  `--zone`) y `garage_probikegarage_verify`, pruebas
  `garage/tests_probikegarage_import.py` (65) y `tests_probikegarage_review.py`
  (7). Suite completa **2690 + 45 subcasos** (219 s); `check`,
  `makemigrations --check` e `inspect` limpios. `--dry-run` del volcado real
  (Fable y los tres agentes): 0 errores, 6 avisos; crearía 17 categorías, 2
  bicis vinculadas a Strava, 50 objetos (19 retirados), 62 montajes (23
  anidados), 30 tipos, 38 reglas, 21 vidas útiles, 184 intervenciones y 8
  lecturas iniciales.
- **Importación real hecha por el usuario (25 oct, ~19:00 UTC)** en el clúster
  demo 55433, usuario `maxi` (id 2; contraseña fuera del repo, en
  `~/.cache/stravagancia/garage-demo-users.json`): 0 errores, 6 avisos; en la
  base: 2 bicis, 50 objetos (19 retirados), 62 montajes (26 abiertos), 59
  reglas (38 + 21 vidas útiles), 184 intervenciones, 8 lecturas, 2 `StravaGear`
  vinculados, 17 categorías, **0 salidas** (hasta el histórico de Strava). Mapa
  en `~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-25.json`.
  (El clasificador de permisos de Claude Code había bloqueado a Fable la
  aplicación real por datos personales; el comando fue:)

  ```bash
  export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
  python3 tools/handoff/garage_demo_pg.py run manage.py garage_import_probikegarage \
    ~/.cache/stravagancia/probikegarage/probikegarage-2026-10-25-compact.json \
    --owner 2 --mapping ~/.cache/stravagancia/probikegarage/mapping-demo-maxi-2026-10-25.json \
    --settings=strava_app.settings_test
  ```

  Después, en la demo 8766 como `maxi`: Más → Strava → «Importar histórico»
  desde 2012-01-01 (**no es posible con `settings_test`**: ver «Aviso para el
  histórico de Strava» más abajo y la tarea garage-044) y, al terminar,
  `garage_probikegarage_verify <volcado> --owner 2 --mapping <mapa>` con el
  helper de la demo. La verificación compara en `exported_at` del volcado;
  se esperan 8 diferencias explicadas (spec §10, final).
- Clústeres recreados el 25 oct (el reinicio del Mac los borró): pruebas 55434
  (`stravagancia_test_018`, estado en `/private/tmp/garage018_pg_state.json`,
  `VALIDATION_DIR=/private/tmp/garage018-validation-q9x6iq36`) y demo 55433
  (migrada a 0012 y con el seed ficticio; demo / garage-demo). Demo 8766
  (`GARAGE_STRAVA_USER=demo`) y tablero 8765 relanzados en segundo plano
  (logs en `/private/tmp/garage-demo-8766.log` y `/private/tmp/garage-board-8765.log`).
- **Acceso del usuario a la demo (25 oct, tarde)**: no podía entrar. Causas
  encontradas y resueltas, en orden: (1) usaba `/admin/` (exige staff): `maxi`
  es ahora staff y superusuario; (2) django-axes lo bloqueó (5 intentos, 1 h):
  `manage.py axes_reset` con el helper de la demo; (3) causa de fondo: el helper
  `tools/handoff/garage_demo_pg.py run` limpia el entorno (sólo deja pasar
  `GARAGE_STRAVA_USER`), así que la contraseña generada por Fable nunca llegó a
  `create_user` (quedó `x`). A petición expresa del usuario («ponele maxi de
  password y dale») la contraseña de `maxi` en la demo local es ahora el propio
  nombre de usuario (anotado en `~/.cache/stravagancia/garage-demo-users.json`,
  fuera del repo). Entrada verificada por HTTP en `/accounts/login/` (302 →
  `/garage/`, con sus dos bicis). Sólo vale para el clúster local 55433.
- **Aviso para el histórico de Strava (hallazgo del 26 oct, al cerrar)**: con
  `strava_app.settings_test` **no se puede hablar con Strava**:
  `test_support/isolation.py` (`install()`) elimina todas las variables
  `STRAVA_*` del entorno, pone valores sintéticos, bloquea `.env` y sustituye
  `requests.sessions.Session.send` por una función que lanza «Real HTTP is
  disabled in tests». Además el helper de la demo sólo deja pasar
  `GARAGE_STRAVA_USER`. El modo token de Garage obtiene el access token con
  `strava_integration.utils.refresh_access_token()` (lee `STRAVA_CLIENT_ID`,
  `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN` del entorno y, si existe
  `.env`, reescribe en él el refresh/access token: comportamiento del legado).
  Los únicos ajustes alternativos son `strava_app.settings` (producción: cargan
  `.env` y apuntan a Neon por `DATABASE_URL`; **prohibidos para esto**). Por
  tanto el paso «el usuario arranca el servidor con su token» documentado hasta
  ahora **no tiene ajustes con los que hacerse**: hace falta un módulo de
  ajustes local nuevo (p. ej. `strava_app.settings_local`): base PostgreSQL local
  (55433) obligatoria, variables `STRAVA_*` reales tomadas del entorno que
  exporte el usuario (nunca leer `.env` desde la IA), HTTP permitido sólo hacia
  `www.strava.com`, `DEBUG` y `axes` como la demo, y que `refresh_access_token`
  no reescriba `.env` (o que el usuario lo acepte). Registrado como
  **garage-044** (abierta, depende de 030 y 043; implementación por agente Opus
  tras diseñar la spec y acordarla con el usuario). Hasta entonces, `maxi` en la
  demo tiene el inventario completo pero 0 salidas, y `garage_probikegarage_verify`
  mostrará las diferencias de uso esperadas por falta de salidas.
- **Pendiente del usuario**: entrar en la demo 8766 como `maxi` y revisar el
  inventario migrado; confirmar `maxi` como usuario de Garage para
  `GARAGE_STRAVA_USER`; decidir garage-044 (ajustes locales con Strava real) y
  después «Importar histórico» desde 2012-01-01; confirmar D1–D12 (en especial
  D2: dos intervalos **repetibles** titulados «Max Life»/«Check Max Life»,
  ambos de piezas retiradas, quedan como reglas normales); después,
  `garage_probikegarage_verify`.
- **Todo lo local apagado al cerrar la sesión (26 oct 07:15 UTC, «apaga el
  docker, todo lo local»)**: demo 8766 y tablero 8765 parados; PostgreSQL 55433
  (demo) y 55434 (pruebas) parados con `pg_ctl -m fast stop` **conservando los
  directorios de datos** (`/private/tmp/garage018-demo-jtz9zq_9/data`,
  `/private/tmp/garage018-validation-q9x6iq36/data`) y los ficheros de estado
  `/private/tmp/garage_demo_pg_state.json` y `/private/tmp/garage018_pg_state.json`;
  no se usó la acción `stop` de los helpers porque borra los datos
  (`shutil.rmtree`), y la base demo 55433 contiene la importación real de `maxi`.
  Un reinicio del Mac los borra. Para volver a levantarlos sin perder la demo:
  `pg_ctl -D <root>/data -l <root>/postgres.log -w -o '-h 127.0.0.1 -p 55433 -k
  <root> -c max_connections=30 -c shared_buffers=32MB' start` (55434 igual con
  su root y puerto); después `garage_demo_pg.py run manage.py runserver
  127.0.0.1:8766 --noreload --insecure --settings=strava_app.settings_test` con
  `GARAGE_STRAVA_USER=demo` y `tools/garage_progress.py` para el tablero. Si
  los datos se perdieron (pasó el 29 oct): `garage_demo_pg.py start` (clúster
  vacío), `run manage.py migrate --settings=strava_app.settings_test`,
  `run tools/garage_demo_seed.py`, recrear `maxi` (id 2, staff y superusuario)
  y repetir la importación con un `--mapping` **nuevo** (el importador rechaza
  un mapa existente); el vigente es `mapping-demo-maxi-2026-10-29.json`.
  OrbStack/Docker también parado (`orbctl stop`; sólo corrían contenedores
  `mcp/grafana` de Claude).

## Entrega anterior: garage-042, ciclo de vida del material visible (18–19 oct)

Primer feedback de UI del usuario en las pruebas locales: quiere ver de un
vistazo, como en ProBikeGarage, qué material está montado, cuál disponible,
cuál en uso sin montar y cuál retirado. Especificación
`.claude/specs/2026-10-18-garage-ciclo-vida-material-spec.md` (decisiones §6,
revisión §7, re-verificación §8); informe `docs/validation/garage-042.json`.
**Sin migración**: la última sigue siendo la 0012 y la siguiente, la 0013.
Decisiones del usuario: «Retirado» se queda; un juego de pastillas es una sola
ficha, sin cantidades; el motivo al retirar queda para una tarea futura.

- **Servicio** `garage/services/lifecycle.py`: única fuente del estado y de su
  texto (`ItemLifecycle`, `item_lifecycles`, `filter_state` con `Exists` en la
  base de datos, `mount_resolver`), y etiqueta `{% life_text %}` en `garage_ui`.
  Estados en el instante `at`: **Retirado el …** (`retired_at <= at`),
  **Montado** («En Gravel desde el …», «Sobre Rueda trasera · Gravel desde el …»),
  **En uso · contextos** (perfil de uso vigente), **Disponible** o **Sin
  estrenar** (nunca montado, sin perfil, sin lectura previa, sin inicio de uso ni
  inclusión por excepción). Una retirada programada conserva el estado y añade
  «· se retira el …».
- **Material**: chips Montados · Disponibles · En uso · Retirados · Todos;
  fila «Categoría · estado»; `active` sigue aceptado como «no retirado ahora».
  Inicio («Disponible»/«Sin estrenar» en vez de «Guardado»), ficha y «Cuánto
  dura cada uno» usan los mismos textos. Bicis y Categorías no cambian.
- **Flujo Opus** (wf_860d7699): implementación → revisión independiente
  (8 hallazgos: 1 important —«Sin estrenar» ignoraba las inclusiones por
  excepción—, 2 minor, 5 nit) → corrección (7 arreglados; R042-5 rechazado:
  «sin montar» en las alertas es el lugar, compartido con Taller) →
  re-verificación `ready` (8/8). Suite completa **2618 pruebas + 45 subcasos**
  (183,91 s); `check`, `makemigrations --check` e `inspect` limpios.
  Presupuestos de consultas: Material ≤ 7; ficha suelta ≤ 44, montada ≤ 47;
  categoría ≤ 28.
- **Nota menor sin corregir** (anterior a 042): con una retirada programada,
  las acciones de la ficha leen `retired_at` sin mirar la fecha (muestran
  «Reactivar», ocultan «Montar» y «Añadir pieza»). Funciona porque «Reactivar»
  cancela la retirada. Decidir con el usuario.
- Demo 8766 reiniciada con el código nuevo para que el usuario lo pruebe.
- 19 oct (14:06 UTC): trabajo en pausa a petición del usuario y estado
  guardado. Demo 8766 y tablero 8765 levantados de nuevo como tareas en
  segundo plano de la sesión de Claude (mueren con ella; relanzarlos con los
  comandos de «PostgreSQL de pruebas y demo»). Nada en curso: ningún agente ni flujo activo.
  Pendiente del usuario: probar 042 en la demo, decidir la nota menor de arriba
  y confirmar el cambio en la deducción de iconos (spec 041 §8).

## Entrega anterior: garage-030 fase 4, operación diaria (18 oct)

Especificación `.claude/specs/2026-10-18-garage-strava-fase4-spec.md` (modo
token; maestra §3 «Disparo», «Revocación externa», §5 «Worker de Cloudflare»);
contrato en `docs/garage-domain.md` §16 («Operación diaria») y
`docs/garage-data-sources.md`. **Sin migración nueva**: la última sigue siendo
la 0012 y la siguiente, la 0013. Dos mitades:

- **Servicio**: `strava_sync._sync_owner(owner)` es el trabajo único de
  «Sincronizar ahora» (`sync_now`) y de `sync_all(now=None)`, que purga los
  avisos de más de 30 días y recorre las cuentas del propietario configurado
  (nunca crea la cuenta) ⇒ `SyncAllResult(accounts, pending, status, error,
  purged, absences)`. Ausencia como pista (`_after_window`, `ABSENCE_HINTS = 20`,
  sólo con la semana completa, sin error ni actividades inservibles), revocación
  (`revoked_at` sólo cuando Strava rechaza el token mismo: la renovación o
  `GET /athlete` tras una renovación; nulo en cuanto `GET /athlete` responde o
  al terminar bien; un `network`, un 429 u otro final fallido no lo tocan) y
  purga (`REVOKED_PURGE_DAYS = 30`, sólo `sync_all`, con `remove_strava_data`):
  a partir del día 30 en Madrid (`purge_date`/`purge_due`, la fecha que muestra
  la pantalla) y sólo si en esa misma ejecución Strava sigue rechazando el
  token. Endpoint `POST /garage/strava/sync-all/`
  (`garage:strava-sync-all`, `strava_views.sync_all`): sin sesión ni CSRF,
  `X-Sync-Token` con `hmac.compare_digest`; 404 a cualquier método si
  `GARAGE_SYNC_TOKEN` falta o tiene menos de 32 caracteres; 405 si no es POST;
  403 sin cuerpo; 200 JSON también si falla. Comandos `garage_sync_token`
  (imprime `secrets.token_urlsafe(48)`, no escribe archivos) y
  `garage_strava_sync` (ejecuta `sync_all()` e imprime el JSON). Una línea INFO
  en `garage.services.strava_sync`. Pruebas `garage/tests_strava_operation.py`
  (64: 45 de la entrega y 19 netas de la revisión).
- **Worker** (`keepalive/cloudflare-worker.js`): `scheduled()` despacha por
  `event.cron` (espacios normalizados). `*/12 * * * *`, y cualquier otro cron,
  es el keep-alive de siempre, sin cambios. `5 7,8 * * *` (UTC) es la
  sincronización y sólo actúa cuando en `Europe/Madrid` son las 09: las 09:05
  en verano y en invierno, una vez al día (también los dos días de cambio de
  hora). Hace `POST` a `env.SYNC_URL` con `X-Sync-Token: env.SYNC_TOKEN`
  (secreto del Worker) y `User-Agent: curl/8.7.1`, sin cuerpo,
  `AbortSignal.timeout(45000)` por llamada y 2 s entre llamadas; para en
  `pending == 0`, `error != ""`, una respuesta no 200, una llamada fallida o
  agotada, un JSON inesperado o a las 6 llamadas. Sin `SYNC_URL` o `SYNC_TOKEN`
  escribe qué nombre falta (nunca valores) y no llama. Nunca registra el token
  ni la URL (de un error sólo su `name`). El handler `fetch` sólo hace el ping.
  Nunca sigue una redirección (`redirect: "manual"`): un 3xx para con su
  código y el token no viaja a otra URL.
  `keepalive/README.md` explica los dos triggers, la variable, el secreto y que
  los configura el usuario en el panel. Pruebas `keepalive/worker.test.mjs`
  (39, `node --test`, `fetch`/`Date`/`setTimeout`/`AbortSignal.timeout`
  simulados).
- **Pantalla Más → Strava** (`_page`, `strava.html`): para el propietario
  configurado, «Sincronización automática: configurada. El Worker de Cloudflare
  la pide cada día a las 9:05 (hora de Madrid)» (sin cuenta añade «a partir de la
  primera sincronización manual», porque `sync_all` no la crea) o «no
  configurada (falta GARAGE_SYNC_TOKEN).», según
  `strava_views.sync_token_configured()`, sin mostrar el ajuste. Con
  `revoked_at`: aviso `pending st-due` «Strava rechaza el token desde el
  <fecha>. Renueva STRAVA_REFRESH_TOKEN en Render. Si sigue así, lo
  sincronizado desde Strava se borrará automáticamente el <purge_date>.»
  («desde el» en la zona de quien mira; la fecha de borrado es el día de Madrid
  en que la ejecución diaria purga). Sin `GARAGE_SYNC_TOKEN` no promete nada
  automático: «…se borrará en la primera sincronización diaria a partir del
  <fecha>; sin sincronización automática, sólo si alguien ejecuta manage.py
  garage_strava_sync.». Sustituye al texto genérico de `unauthorized`;
  cualquier otro error (p. ej. 429) se sigue mostrando. Sin consultas nuevas,
  sin JavaScript ni estilos en línea. Pruebas en `garage/tests_strava_views.py`
  (+9, y +5 de la revisión).
- Decisiones fuera del spec (servicio): 404 a cualquier método sin token
  válido (el 405 sólo con él); ausencia con `>` estricto contra el `after`
  pedido, sin pistas si hubo actividades inservibles y sin segunda pista con un
  borrado pendiente de la misma actividad; un `delete` confirmado que sigue en
  Strava guarda lo devuelto (nunca crea una fuente); `sync_all` sin cuenta ⇒
  `idle` (y no escribe nada para una cuenta quitada a mano mientras corre),
  para en el primer error. (Worker y
  pantalla): un fallo, timeout o JSON inesperado para el bucle ese día; un cron
  desconocido hace el keep-alive; el aviso de revocación y la línea automática
  sólo para el propietario configurado (la purga diaria no toca otra cuenta).
- Límites: la purga ocurre en la ejecución diaria de la fecha mostrada (o en la
  primera posterior si ese día no hubo ejecución o falló por red o 429) y sólo
  si el Worker (o `garage_strava_sync`) llama a `sync-all`. Detectada por la
  ejecución diaria, la purga llega justo a los 30 días (±1 h por el cambio de
  hora); detectada con el botón de madrugada, hasta unas 9 h después (la
  ejecución es a las 09:05). Con la regla anterior (`≥ 30 días`) caía casi
  siempre el día 31, un día después de la fecha mostrada. La ausencia supone
  `activity:read_all` (comprobarlo antes de desplegar, abajo). Borrados de más
  de 7 días sólo llegan por webhook. El
  logger `garage` no se ve en Render hasta garage-023. Nada probado contra
  Strava ni Cloudflare reales; nada desplegado. El servidor demo 8766 se
  reinició con el código final (18 oct) y con `GARAGE_STRAVA_USER=demo`, así
  que Más → Strava muestra el estado del propietario configurado.
- Validación (TESTING.md, «garage-030 fase 4»): `node --check` correcto y
  `node --test keepalive/worker.test.mjs` 39/39; suite completa **2552 pruebas + 45 subcasos** (176 s, tras la revisión; **2578 + 45** tras los arreglos de herramientas, abajo);
  check sin problemas, makemigrations «No changes detected», 0 bases
  residuales; capturas a 390 px (claro y oscuro) de Más → Strava (antes de la
  revisión).
- **Revisión de código independiente hecha** (spec §5): 2 importantes (purga
  sin comprobar el token; un `network` reiniciaba el plazo de 30 días) y 7
  menores (403/401 tras aceptar el token, fecha de purga, `TARGET` del README,
  redirecciones del Worker, `activity:read_all`, cuenta quitada durante la
  ejecución, token en una página 500 con DEBUG), todas corregidas con pruebas.
- **Re-verificación independiente hecha** (spec §6): 9/9 arreglos verificados;
  una aserción frágil (`"kJ" not in html` frente al token CSRF, en
  `garage/tests_elevation_screens.py`) corregida; informe
  `docs/validation/garage-030-fase-4.json`.
- Arreglos de herramientas del mismo día (agentes Opus): el tablero 8765
  acepta las subtareas jerárquicas de Beads (`garage-031.1`…; antes `/state.json`
  respondía 503 «identificador inválido»; `tests_progress.py` +6); el helper de
  la demo deja pasar `GARAGE_STRAVA_USER`, `settings_test.py` la lee y bajo
  pytest `isolation.install()` la vacía (`tests_test_environment.py` +2).

## Despliegue (garage-023): lo que falta configurar

Nada de esto lo hace una IA ni se ha hecho: lo configura el usuario cuando
autorice el despliegue (garage-023). Nunca escribir tokens en el repositorio.

- **Render, variables de entorno**:
  - `GARAGE_STRAVA_USER`: usuario de Garage dueño del atleta de Stravagancia
    (pendiente de que el usuario lo indique). Vacío ⇒ Garage no sincroniza.
  - `GARAGE_SYNC_TOKEN`: **≥ 32 caracteres**; generarlo con `python manage.py
    garage_sync_token` (imprime 64 caracteres una vez, no escribe archivos).
    Vacío o corto ⇒ `sync-all` responde 404 y no hay sincronización diaria.
  - `STRAVA_WEBHOOK_SUBSCRIPTION_ID` (opcional): id de la suscripción del
    webhook; con él, los eventos de otra suscripción se descartan.
  - Arranque con **`gunicorn --timeout 60`**: «Sincronizar ahora» y cada
    `sync-all` duran unos 30 s; el Worker espera 45 s por llamada.
  - Logger `garage` (INFO) en `LOGGING` para ver la línea diaria.
- **Antes de activar la fase 4, comprobar `activity:read_all`** (a mano, en
  producción, lo hace el usuario): la ausencia en la semana y los `delete`
  sólo borran con un 404, que sólo prueba algo si el token de Stravagancia ve
  las actividades privadas. Con una salida **privada** («Solo tú») de los
  últimos 7 días (una existente o una de prueba), pulsar «Sincronizar ahora» y
  comprobar que aparece en Garage. Si no aparece, el token no tiene
  `activity:read_all`: no configurar el Worker y avisar (una salida que se haga
  privada se borraría de Garage en un día). Una salida de prueba se borra
  después en Strava (también la recibe el webhook del legado).
- **Cloudflare, Worker `strava-keepalive`** (panel; ver `keepalive/README.md`):
  pegar `keepalive/cloudflare-worker.js` en Edit code y **sustituir `TARGET`**
  (aquí `REDACTED`) por la URL real de `/healthz/` que ya tiene la copia del
  panel **antes de Deploy**: desplegarlo tal cual rompe el keep-alive (Render
  se duerme y el POST de las 09:05 choca con un arranque en frío de más de
  45 s). Cron Triggers `*/12 * * * *` (ya existe) y **`5 7,8 * * *`**;
  variable `SYNC_URL` = `https://<app>.onrender.com/garage/strava/sync-all/`
  (con `https` y la barra final: el Worker no sigue redirecciones y un 301
  para la sincronización); **secreto** `SYNC_TOKEN` = el mismo valor que
  `GARAGE_SYNC_TOKEN`.
- **Migraciones**: `garage.0009`–`0012` sólo locales, **no están en Neon**.
  Nota sólo para el despliegue: la 0012 sustituye dos CHECK
  (`garage_maintenancerule_has_threshold` y `garage_snooze_has_amount`) por
  versiones que admiten el desnivel; las filas actuales los cumplen y en Neon
  las tablas de Garage están vacías. No preguntar por ello antes de desplegar
  (orden del usuario, 18 oct: local → Strava real → despliegue). Aplicarlas
  sólo en el despliegue autorizado, nunca con `docker compose up web` (migra
  contra Neon).
- **Tras desplegar**: `python manage.py garage_strava_sync` en la consola de
  Render (mismo trabajo acotado, imprime el JSON) y, al día siguiente, los
  registros del Worker a las 09:05 (Observability → Logs).

## Entrega anterior: garage-030 fase 3, desnivel y potencia (18 oct)

Especificación `.claude/specs/2026-10-18-garage-strava-fase3-spec.md` (incluye
garage-037); contrato en `docs/garage-domain.md` §17 y enmiendas de §13, §14,
§14 bis, §15 y §16. Dos mitades: **datos** (migración `garage.0012_elevation_power`,
sólo local; tuplas `CORE/USAGE/POWER/RIDE_METRICS`, FIT, Strava, materialización,
exportación) y **pantallas**:

- Reglas y aplazamientos por desnivel: `maintenance_due.METRICS` (último),
  `presentation.UNITS` «m» / `NAMES` «Desnivel» / `MARKS` «↑», `thresholds()`
  («20.000 m de desnivel»), `snooze_reached`, `.only()`; formularios de regla,
  vida útil y posponer con «Desnivel (m)» en metros enteros (`elevation_field`
  en `maintenance_forms.py`). Un aplazamiento con una salida sin desnivel queda
  «por revisar» y el aviso se ve.
- Pantallas: «↑ 1.234 m» (filtro `metric_m`) en Salidas, Histórico,
  previsualización FIT, Inicio, bici, objeto, intervención y efecto de la
  revisión; potencia («Ø», «máx», «NP», kJ; filtro `power_figures`) sólo en la
  revisión y el detalle de la salida (`_ride_measures.html`). Única regla CSS
  nueva: `.stats.four` (y `.stats + .stats`). Sin JavaScript nuevo.
- Estadísticas: desnivel del período, por bici, por material y por mes
  (`?chart=elevation` en Estadísticas). La potencia media no se suma.
- Menores de fases 1–2 en `strava_sync.py`/`strava_client.py`: la última ronda
  ya no se traga los avisos tardíos, un lote lleno sigue en otra ronda (o en un
  worker nuevo), «Sincronizar ahora» responde en unos 30 s
  (`RESPONSE_SECONDS`: conexión + lectura recortadas a lo que queda; código
  interno `deadline`; no es un límite estricto porque requests no acota DNS,
  un cuerpo a goteo ni la renovación del token, y el techo duro es el de
  gunicorn, 60 s) y los perfiles usan `sport_label`.
- Pruebas: `garage/tests_elevation_screens.py` (42, hoy 46 tras la revisión);
  suite de esa mitad 2429 pruebas + 45 subcasos (TESTING.md, «garage-030 fase 3,
  mitad de pantallas» y «revisión de código»).
- Revisión de código (spec §5, todo corregido): `WholeNumberInput` lee
  «20.000» como 20.000 m (Django lo guardaba como 20) en regla, vida útil y
  posponer, también salidas, días y tiempo; campos FIT opcionales repetidos o
  mal formados ⇒ desconocidos (el archivo entra); timeout conexión + lectura ≤
  lo que queda; una regla cuyo intervalo no tiene ninguna salida con desnivel
  queda «Sin datos» (no «En curso ≥ 0 %»), con «N sin desnivel», «↑ ≥» y la
  indicación de volver a importar FIT o histórico de Strava donde el desnivel es
  un mínimo. Pruebas: `garage/tests_elevation_review.py` (39); suite **2473
  pruebas + 45 subcasos**, check, makemigrations sin cambios, 0 bases residuales.
- Re-verificación (Opus, spec §6): 4/4 arreglos comprobados; 2 hallazgos
  nuevos menores corregidos por el orquestador: el campo exacto que conserva
  la regla del teléfono cuando el desnivel tiene decimales (puesto desde el
  admin) es ahora `DecimalInput` («1.234,5» vale, «2.000» se rechaza como
  ambiguo en vez de leerse como 2 m; 1 prueba) y el docstring de
  `strava_client` dice «como mucho (5, 20)». `CLAUDE.md` actualizado (0012
  sólo local, siguiente 0013, aviso de los dos CHECK). Suite **2474 pruebas +
  45 subcasos** (docs/validation/garage-030-fase-3.json). Demo 55433 migrada
  a 0012 y servidor 8766 reiniciado.
- Pendiente: probar el parser con la muestra FIT del usuario (spec maestra
  §7.3) y contra Strava real; la fase 4 se entregó después (arriba).

## Entrega anterior: garage-041, categorías iniciales con icono (18 oct)

Pedido del usuario: «en material me faltan muchas categorías» → juego inicial
«con su icono». Especificación `.claude/specs/2026-10-18-garage-categorias-iniciales-spec.md`.

- **Migración `garage.0011_category_icon`** (sólo local, **no está en Neon** ni
  en la demo 55433): `Category.icon` (`''` = deducir del nombre) y CHECK
  `icon = '' OR icon ~ '^[a-z_]+$'`. Las fases 3–4 de Strava deberán usar 0012.
  La demo de 8766 sigue con el código anterior cargado (`--noreload`): al
  reiniciarla habrá que aplicar 0011 a su base o fallará al leer categorías.
- Código: `garage/icons.py` (`ICON_CHOICES`: 43 claves con nombre y palabras
  clave; `match_icon`, `item_icon_key`, `category_icon_key`),
  `services/categories.py` (`STARTER`, `create_starter_categories`,
  `missing_starter`, `starter_offer`, `suggest_icon`), `category_views.py`
  (`category-starter`, POST), `IconGrid` y `CategoryWebForm` en `web_forms.py`,
  `_icon_grid.html`, `_starter.html`, 32 símbolos nuevos en `_icons.html`,
  estilos al final de `garage.css`, columna `icon` en la exportación
  (`docs/garage-export.md`) y lista desplegable en el admin.
- Decisiones además de la especificación:
  - El §3 tiene **42** categorías (no 37), y se crean todas.
  - El botón sale siempre en Categorías mientras falte alguna, en Material sólo
    si está vacío y en Crear material si no hay ninguna categoría.
  - **«Según el nombre» guarda `''`** y el icono se deduce cada vez; corregido
    en la revisión (antes congelaba la sugerencia). Las categorías sin icono
    abren el formulario con esa opción marcada y su casilla dibuja el icono
    sugerido. Una clave que ya no esté en la lista también se trata como `''`.
- **Cambio visible, pendiente de que el usuario lo confirme.** La deducción ya no
  sigue la tabla antigua:
  - Va sin acentos; las palabras clave casan como palabra completa (con
    plural); gana la escrita antes (el núcleo: «Llave de cadena» es
    herramienta, «Bolsa de sillín» bolsa) y, a igual posición, la más larga.
    Lo fijó la re-verificación (spec §8): antes mandaba la longitud y una
    clave casaba dentro de otra palabra («Recambios» daba desviador).
  - El nombre del objeto va antes que el de su categoría.
  - Hay iconos nuevos. Por ejemplo, «Disco» en «Frenos» pasa de freno a disco,
    «Llanta» de rueda a llanta, «Plato» de casete a platos, «Calas» de
    zapatilla a calas y «Cámara» en «Cubiertas» de cubierta a cámara.

  Vida útil orientativa: la llanta conserva la de la rueda. Disco, platos,
  calas y cámara se quedan sin cifra, porque la que heredaban era la de otra
  pieza (1.500 km de pastillas para un disco). Las opciones están en la spec,
  §7.7. Si el usuario prefiere la regla antigua, se cambia en
  `garage/icons.py` y `lifespan_forms.SUGGESTIONS` sin migración.
- Revisión independiente hecha: 1 hallazgo importante y 6 menores, todos
  corregidos con prueba (spec §7). Re-verificación: los 7 comprobados; 2 menores
  nuevos en la deducción, corregidos (spec §8).
- Pruebas:
  - `garage/tests_categories.py`: 91 casos (52 + 25 de la revisión + 14 de la
    re-verificación).
  - Suite completa: ver `docs/validation/garage-041.json`.
  - check, makemigrations e `inspect` limpios (TESTING.md).
- Demo 55433 migrada a 0011 y servidor 8766 reiniciado el 18 oct (usuario
  demo / garage-demo); el botón «Crear las categorías habituales» sale en
  Categorías.
- Pendiente: que el usuario confirme el cambio visible de la deducción.

## Entrega anterior: garage-030 fases 1–2, Strava en «modo token» (18 oct)

El usuario aprobó el alcance de §0 de
`.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`: el mismo refresh
token de Stravagancia, sólo su cuenta, sólo ciclismo, sin OAuth (garage-040).
Especificación de la fase con las decisiones tomadas:
`.claude/specs/2026-10-18-garage-strava-fase1-2-spec.md`; contrato en
`docs/garage-domain.md` §16 (y enmienda de §10).

- **Migración `garage.0010_strava_source`** (sólo local; **no está en Neon**:
  levantar `web` de Docker Compose la aplicaría junto con 0009). Aditiva salvo
  dos CHECK ampliados (tipo de fuente y de trabajo), que las filas FIT cumplen.
  Modelos `StravaAccount`, `StravaGear`, `StravaEvent`; columnas
  `ActivitySource.external_id/gear_id/possible_duplicate` e
  `ImportRun.items_imported/items_skipped`.
- Código: `garage/sports.py` (familia ciclismo, mapa de Strava),
  `services/strava_client.py` (HTTP, `timeout=(5, 20)`, `parse_float=Decimal`,
  401/429), `services/strava_sources.py` (observación, vinculación, separar,
  unir, bicis, quitar lo sincronizado), `services/strava_sync.py` (cuenta env,
  «Sincronizar ahora», histórico reanudable, webhook), `strava_views.py`,
  `strava_forms.py`, `strava.html`; precedencia por clase en
  `services/rides._recalculate`; perfiles por familia en `usage_profiles` y
  `ride_review`; exportación aditiva (`strava_gear`, columnas de `sources`).
- Legado tocado sólo en `strava_integration/views.py`: despacho por atleta (el
  legado sólo procesa su `Athlete.strava_id`), `subscription_id` y
  `compare_digest` en la verificación; sus pruebas añaden `owner_id`.
- Pantallas: Más → Strava (`/garage/strava/`), trabajo Strava en el histórico
  (sin archivo), origen y «posible duplicado» en Salidas y en la salida,
  «Separar fuente», «Unir con…», «No es un duplicado», «Powered by Strava».
- **Variables nuevas**: `GARAGE_STRAVA_USER` (usuario de Garage dueño del
  atleta) y `STRAVA_WEBHOOK_SUBSCRIPTION_ID` (opcional; si existe, otro id se
  descarta). La primera entrega decía haberlas añadido a
  `strava_app/settings.py` y **no estaban** (hallazgo bloqueante de la
  revisión); desde la revisión del 18 oct sí: `os.getenv(..., '')`, con una
  prueba que lee el archivo (no se tocó `.env`).
- Límites: `refresh_access_token()` del legado sigue sin `timeout` (no se tocó);
  Garage y el legado renuevan el mismo token (mismo riesgo de rotación que ya
  corría el legado); se supone `activity:read_all`; la paginación del histórico
  es por número de página (un borrado durante la importación puede desplazar una
  actividad, la sincronización de 7 días lo compensa en lo reciente); el logger
  `garage` no está configurado en producción (garage-023). Pendiente: fases 3
  (desnivel y potencia, 0011) y 4 (ausencia como pista, `sync-all`, Worker),
  probar contra Strava real y capturas.
- **Revisión de código (18 oct)**: 13 hallazgos corregidos con pruebas, sin
  migración nueva; detalle en la sección «Revisión de código» de la
  especificación corta. Lo principal: páginas de 50 y ≈ 12 consultas por
  actividad nueva (antes ≈ 82), «Sincronizar ahora» acotado a 14 peticiones y
  25 s, un hilo del webhook por atleta y proceso tras el commit, sin llamadas a
  Strava dentro de transacciones y con el orden de bloqueos propietario →
  evento, «Unir con…» que ya no borra notas ni excepciones (y avisa antes),
  FIT duplicado marcado, estados y modalidades en español.
- Pruebas: ver TESTING.md («garage-030 fases 1–2»): 118 de Strava, 42 del
  legado; suite completa **2201 pruebas + 45 subcasos**; check, makemigrations
  y cero bases residuales.

## Entrega anterior: ideas de ProBikeGarage, garage-034 a 039 (17–18 oct)

El usuario hizo un análisis REA de ProBikeGarage
(`docs/research/2026-10-17-probikegarage-rea.md`) y pidió incorporar lo que
falta: posponer vencimientos, componentes anidados; desnivel y Strava «luego»
(030 sigue aplazada). Se fue a dormir: «ve haciendo. ante la duda, documenta las
opciones y elige una», y quiere una comparación final con ProBikeGarage
recordando lo que Garage hace mejor (material por bici o deporte: casco,
zapatillas). Tareas creadas: 034 posponer, 035 piezas anidadas, 036 uso en cada
intervención y comparar piezas, 038 retirar con lo montado, 037 desnivel
(diseñar, no implementar sin el usuario), 039 comparación final.

**garage-034 (cerrada)**: `MaintenanceSnooze` + migración aditiva 0009 (sólo
local), `services/snoozes.py`, `snooze_forms.py`, `snooze_views.py`
(`maintenance-rule-snooze`), estado «Pospuesto» en `presentation.py`, Inicio,
Taller, fichas, detalles técnicos y exportación (`snoozes`). Especificación con
decisiones y revisiones: `.claude/specs/2026-10-17-garage-posponer-spec.md`;
contrato en `docs/garage-domain.md` §14 bis. Pruebas `garage/tests_snoozes.py`.

**garage-035 (cerrada)**: `services/parts.py`, `parts_views.py`,
`part_forms.py` (`item-part-create`), sección «Piezas» y entradilla anidada en la
ficha, y «También en esta visita» en Registrar mantenimiento
(`maintenance_views._together`, `_together.html`): una intervención por regla
marcada, atómico, alcance en la fecha elegida. Especificación
`.claude/specs/2026-10-18-garage-piezas-spec.md`. Pruebas `garage/tests_parts.py`.

**garage-036**: `services/service_usage.py` (uso desde la anterior y hasta la
siguiente por intervención; «Cuánto dura cada uno» por categoría), filtros
`span_text`, `span_short`, `metric_km`, `whole_days`, `_event_usage.html`,
`_part_lives.html`. Especificación
`.claude/specs/2026-10-18-garage-uso-intervenciones-spec.md`. Pruebas
`garage/tests_service_usage.py`.

**garage-038**: `services/retirement.py` (`mounted_in`, `retire_one`,
`retire_with_parts`, `PartsChanged`), `RetireWebForm` y casilla «Retirar lo que
sale» en Reemplazar. Especificación `.claude/specs/2026-10-18-garage-retirar-spec.md`.
Pruebas `garage/tests_retire_parts.py`.

**garage-037**: sólo diseño (`.claude/specs/2026-10-18-garage-desnivel-spec.md`);
no implementar sin el usuario. **garage-039**: comparación en
`docs/garage-vs-probikegarage.md`.

**Strava por usuario (18 oct, pendiente de aprobación)**: el usuario quiere
sincronizar desde Strava con un botón «Conectar con Strava» (OAuth 2.0 por
usuario, tokens cifrados en la base), desnivel y potencia. Especificación
conjunta `.claude/specs/2026-10-18-garage-strava-oauth-sync-spec.md`
(revisión 2 tras dos revisiones independientes). Fases 1–2 implementadas el
18 oct (arriba). El usuario respondió §9 el 18 oct: modo token (el mismo
refresh token de Stravagancia, sólo su cuenta, `GARAGE_STRAVA_USER`), sólo
ciclismo, OAuth por usuario apuntado en garage-040 (§0 de la especificación).
El 18 oct dio el «adelante» («hazlo con agentes, opus 5.5»). Un agente
implementador Opus 5.5 trabajó las fases 1–2 hasta que el usuario pidió una
pausa para reiniciar el Mac; **se detuvo a mitad de trabajo**, con el código ya
en disco: `garage/services/strava_client.py`, `strava_sources.py`,
`strava_sync.py`, `garage/strava_forms.py`, `strava_views.py`, pruebas
`garage/tests_strava_*.py`, migración 0010 (si existe en `garage/migrations/`)
y la especificación corta `.claude/specs/2026-10-18-garage-strava-fase1-2-spec.md`.
Estaba redactando TESTING.md y este relevo cuando se paró: **nada de esto está
probado ni revisado**. Al retomar: leer la especificación corta, ejecutar la
suite completa (`check`, `makemigrations --check`, `inspect`), arreglar lo que
falle o relanzar el implementador con el mismo encargo (está en la conversación
y en §0/§7 de la especificación maestra), y después la revisión independiente y
la re-verificación. Tras el reinicio hay que volver a levantar los clústeres
PostgreSQL desechables (demo 55433 con su seed y la migración 0009/0010; el de
pruebas lo crea el helper), el tablero 8765 y la demo 8766 (comandos más abajo). Puntos
delicados que las revisiones fijaron: revocar en Strava afectaría al token del
legado (excepción para el atleta del propietario), el webhook no está firmado
(eventos como pistas confirmadas por API), `METRIC_FIELDS` se divide para que
la potencia no entre en `ItemUsage`, vinculación FIT↔Strava determinista.

Suite completa tras 038: **2066 pruebas + 45 subcasos pasan**; check,
makemigrations y cero bases residuales.

La demo (`tools/garage_demo_seed.py`) incluye ahora una rueda trasera con casete
y disco anidados; la base demo actual recibió lo mismo con un script local.

## Entrega anterior: garage-032 y garage-033 (17 oct)

El usuario pidió seguir («sigue sigue q es sabado») y, a mitad de trabajo, que
cada componente tenga vida útil por km o por tiempo, lo primero que llegue,
«mejor que probikegarage». Sin modelos ni migraciones.

**garage-032**: resto de pantallas al estilo B. Especificación revisada:
`.claude/specs/2026-10-17-garage-movil-2-spec.md`.

1. 032.1:
   - Hora local en todos los formularios: `garage/local_forms.py`
     (`LocalDateTimeInput`, `localize`; la zona del usuario, el selector nativo
     y UTC si la hora se repite o el valor no es exacto). Se aplica en
     `views.form_page`.
   - Taller: `services/workshop.py`, `maintenance.html`, `_wear_row.html`
     compartida con Inicio.
   - Formularios web de mantenimiento en `maintenance_forms.py`:
     `ServiceEventWebForm`, `MaintenanceRuleWebForm` (km y horas exactos),
     `ServiceTypeWebForm`, `DecimalInput` (coma decimal, «3.000» ambiguo) y
     `SpanishWebMixin`. El admin conserva sus formularios y mensajes.
   - Detalle de intervención y fotos.
2. 032.2: ficha de bici (`views.bike_dashboard`, `bike_detail.html`) y `?bike=`
   en Salidas.
3. 032.3: Estadísticas por período (`statistics_views.py`: chips, cifras,
   gráfico de todas las salidas, reparto por bici, material, gasto; informe
   detallado plegado). `monthly_usage(all_rides, through)`,
   `StatisticsReport.overall/no_bike`.
4. 032.4: listas de bicis, material y categorías, perfiles, histórico, salida
   avanzada y exportar con el estilo nuevo. `{% local_datetime %}` con
   `<time datetime>` en lugar de las fechas UTC.

**garage-033**: vida útil. Especificación:
`.claude/specs/2026-10-17-garage-vida-util-spec.md`.
- Una regla del tipo «Sustitución» del propietario, mostrada como «Vida útil».
- Servicio `services/lifespan.py`; formulario `lifespan_forms.py`; página
  `items/<uuid>/lifespan/` (`lifespan_views.py`, `lifespan.html`) con km,
  horas y tiempo (1 mes = 30 días, 1 año = 365 días) y sugerencias por pieza.
- Inicio por defecto: inicio de uso, fecha de compra, primer montaje u hoy.
- Al reemplazar un montaje, la pieza nueva puede heredarla (atómico).
- «Vida útil» en ficha, Inicio, Taller y avisos técnicos.

Pruebas nuevas: `garage/tests_mobile_{workshop,bike,stats,lists}.py` y
`tests_lifespan.py`. Ajustes intencionados:
- `tests_views.py`: cookie UTC.
- `tests_maintenance.py`: «12,34».
- `tests_mobile_item.py`: la bici tiene ficha propia.

Suite completa: **1959 pruebas + 45 subcasos pasan** (96 s); check, makemigrations y cero bases residuales.

Revisiones independientes (todas corregidas con pruebas):
- Especificación de 032.
- Código de 032.1–.2: moneda propuesta, «3.000», mensajes, umbrales exactos.
- Código de 032.3–.4 y verificación: «Personalizado» con filtros, mensajes del
  admin, fechas que desbordan.
- Código de 033 y verificación de la segunda ronda: sin bloqueantes; corregido con pruebas.
- Re-verificación final de 033: un 500 con zona horaria inválida y el aviso de sustitución sin regla; corregidos con pruebas.

Mutaciones comprobadas (redondeo silencioso, reasignación de errores, moneda):
cada una hace fallar una prueba; archivo restaurado con hash idéntico. Capturas
a 390 px en claro/iPhone y oscuro/Android de Taller, formularios, ficha de
bici, Estadísticas, listas y vida útil.

Límites declarados:

- Teléfono real sólo con HTTPS (garage-023); la tarea garage-031 sigue abierta por eso.
- `LANGUAGE_CODE` sigue en `en-us` por la app antigua: los mensajes en español
  se aplican en los formularios web de mantenimiento y de vida útil; otros
  formularios antiguos pueden mostrar mensajes de Django en inglés.
- Vida útil: los km anteriores de una pieza usada aún no cuentan (se avisa).
- El filtro del histórico interpreta las fechas en la zona del usuario (antes UTC).

## Siguiente paso

1. **garage-032 y garage-033 cerradas** (17 oct). Probarlas en un teléfono real
   junto con 031 tras desplegar.
2. **garage-031**: sólo falta probarla en un teléfono real (depende de 023).
3. **garage-010**: propuesta (`docs/garage-photo-bucket-proposal.md`) y script
   (`tools/handoff/garage_bucket_check.py`) listos; falta que el usuario autorice
   y cree bucket/credencial en `~/.config/garage-s3-test.env`.
4. **garage-022** depende de 010; **garage-023**: logger `garage`, `STORAGES`,
   docker-compose sin migrate contra Neon.
5. **garage-043** (25 oct): importador de ProBikeGarage implementado, revisado,
   re-verificado y aplicado al volcado real (el 25 oct por el usuario; base
   perdida con un reinicio y **repetida el 29 oct** por Fable con el mapa
   `mapping-demo-maxi-2026-10-29.json`; sección «Sesión del 29 oct»). Queda:
   que el usuario revise el inventario como `maxi`; confirmar la spec de
   **garage-044** (implementada y revisada el 29 oct) y seguir su receta
   (TESTING.md «garage-044»): histórico desde 2012-01-01,
   `garage_probikegarage_verify` con el mapa del 29 oct y confirmar D1–D12.
   **garage-042** implementada y verificada (19 oct); falta que el usuario la
   pruebe en la demo y decida la nota menor de las acciones con retirada
   programada. **garage-030**: fases 1–4 hechas en modo token (la 4, sin migración).
   Revisión de código de la fase 4 hecha, corregida y re-verificada (spec §5
   y §6). **Orden fijado por el usuario (18 oct)**: (a) probar todo en local
   con la demo 8766 (el usuario va a dar feedback sobre la UI; recogerlo en
   Beads y priorizarlo con él antes de tocar nada); (b) resolver la
   sincronización real desde Strava en local (hace falta su usuario de Garage
   para `GARAGE_STRAVA_USER`, que arranque él el servidor con su token de
   entorno —nunca leer `.env`— y su muestra FIT, spec maestra §7.3);
   (c) el despliegue es lo último (bloque «Despliegue (garage-023)», con la
   comprobación de `activity:read_all`, y Cloudflare real).
6. Ideas de ProBikeGarage aún sin tareas (preguntar): posponer avisos, comparar
   duración de componentes, desnivel. Las plantillas de alta quedaron cubiertas
   en parte por las sugerencias de vida útil.

7. **`main` avanzó el 25 oct (legado, no Garage)**: commits `dd607f6` (sin caché
   negativa de geocodificación, espejo `overpass.openstreetmap.fr`, diagnóstico
   `getaddrinfo`) y `45a7cf6` (el webhook `create` responde antes de pedir el
   detalle: fetch → store → rename en el hilo `create-<id>`; `settings.py` fuerza
   IPv4 saliente en Render salvo `GEOCODING_FORCE_IPV4=0`). Desplegados en Render
   con autodeploy. **garage-045 (29 oct)**: fusión preparada en la rama
   `garage-integrate-main` (merge `c3eb532`, worktree aparte, sin push;
   `garage` sigue en `576ec9c`). `views.py`, `settings.py` y `conftest.py` se
   fusionaron solos; el único conflicto real fue `strava_integration/tests.py`.
   Suite en el worktree 2733 + 45; revisión por workflow: 0 defectos de la
   fusión. El usuario la adopta (`git merge --ff-only garage-integrate-main`
   desde `garage`) o la borra (ver «Sesión del 29 oct»).

## Estado de tareas y evidencia

- Cerradas: 001–009, 011, 012, 014–020, 028, 029. 013/021 cerradas N/A.
- 010 in_progress (falta bucket real). 031 abierta (sólo teléfono real). 032 y 033 cerradas el 17 oct.
- 042 in_progress (implementada, revisada y re-verificada el 19 oct; pendiente de que el usuario la pruebe en la demo).
- 030 in_progress (fases 1–4 en modo token hechas y verificadas; faltan pruebas locales con el usuario, Strava real y el despliegue). 037 cerrada con la fase 3. 022/023 pendientes; 024–027 futuras.

Informes: docs/validation/garage-0{17,18,19,20}.json y docs/garage-validation.json
(= 020). Los artefactos de /private/tmp de sesiones anteriores **desaparecieron**
con el reinicio del 13–16 oct (actualización de macOS); los JSON del repo
conservan los resultados.

## PostgreSQL de pruebas y demo (recreados el 29 oct)

Pruebas: 127.0.0.1:55434, base stravagancia_test_018, rol stravagancia_test
(sin superusuario, contraseña sintética stravagancia_test). Estado en
/private/tmp/garage018_pg_state.json, datos en /private/tmp/garage018-validation-nm4spa8e.
Demo: estado /private/tmp/garage_demo_pg_state.json, datos
/private/tmp/garage018-demo-hz3itws9 (contiene la importación real de `maxi`:
no usar la acción `stop` del helper, que borra los datos).

```bash
export GARAGE_TEST_PYTHON=/Users/maxicombina/.cache/stravagancia/venv-macos/bin/python
python3 tools/handoff/garage_test_pg.py run -m pytest garage/tests_mobile_review.py -q --tb=short -p no:cacheprovider
python3 tools/handoff/garage_test_pg.py run manage.py check --settings=strava_app.settings_test
python3 tools/handoff/garage_test_pg.py run manage.py makemigrations --check --dry-run --settings=strava_app.settings_test
```

Demo: 127.0.0.1:55433, base stravagancia_test_demo, datos ficticios generados
por `tools/garage_demo_seed.py` (usuario demo / garage-demo): dos bicis,
sillines A→B→A, cadena que pasó de Gravel a Carretera, casco y zapatillas por
perfil, ~8 meses de salidas, una salida sin bici y reglas en varios estados.
Servidor (tarea en segundo plano de la sesión de Claude; puede detenerse):

```bash
GARAGE_TEST_PYTHON=$GARAGE_TEST_PYTHON python3 tools/handoff/garage_demo_pg.py run manage.py runserver 127.0.0.1:8766 --noreload --insecure --settings=strava_app.settings_test
```

El helper de la demo deja pasar `GARAGE_STRAVA_USER` (y nada más) a Django, para
que Más → Strava muestre el estado del propietario configurado (anteponer
`GARAGE_STRAVA_USER=demo`); el helper de pruebas no lo hace.
`strava_app/settings_test.py` lee esa variable, y bajo pytest
`test_support/isolation.py::install()` la quita del entorno (con
`GARAGE_SYNC_TOKEN`), así que en las pruebas vale "".

La demo está migrada a `garage.0012_elevation_power` (18 oct); la fase 4 no
añade migraciones, así que no hay nada que aplicarle.

Si la demo desaparece: `garage_demo_pg.py start`, `run manage.py migrate
--settings=strava_app.settings_test` y `run tools/garage_demo_seed.py`.
No ejecutar pytest con el helper de demo. Su acción `stop` BORRA los datos.
Nunca dos suites a la vez en 55434.

Tablero http://127.0.0.1:8765/ (`tools/garage_progress.py`): en marcha como
tarea en segundo plano de la sesión de Claude; relanzarlo si no responde. Desde
el 18 oct admite los ids jerárquicos de las subtareas de Beads
(`garage-NNN.N`); antes, con ellas en la exportación, `/state.json` daba 503.

## Beads y documentación al continuar

```bash
bd list --all --limit 0
bd show garage-031
bd --sandbox --dolt-auto-commit off --actor claude update <id> --append-notes 'Resultado comprobado'
bd --sandbox --dolt-auto-commit off --actor claude export --output .beads/issues.jsonl
```

No bd init/sync/dolt push/pull, no staging. No commits, pushes, despliegue,
.env, migraciones/cargas en Neon, bucket público o planes de pago.
