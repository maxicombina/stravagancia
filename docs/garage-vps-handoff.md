# Relevo de Garage para un Claude en un VPS

Escrito el 8 nov 2026 desde el portátil del usuario (macOS). Complementa, no
sustituye, a `CLAUDE.md`, `docs/garage-handoff.md` (el estado detallado, 1269
líneas, sólo hasta el 4 nov) y `docs/garage-context.md`. Léelos antes de actuar.

## 0. Antes de nada: pregunta al usuario qué quiere de ti en el VPS

El encargo concreto no está escrito en ningún sitio. Las opciones razonables son
(a) continuar Garage en local con pruebas, o (b) preparar el despliegue
(garage-023). **La (b) está fuera de alcance hasta que el usuario lo pida
expresamente**: «el despliegue es lo último» (18 oct) y «sin despliegue» sigue
vigente. No asumas la (b) por estar en un servidor.

## 1. El código ya está en el VPS (comprobado el 8 nov)

Este documento decía antes que el código no estaba allí; era falso. El árbol del
VPS (`/home/maxi/src/learning/django/stravagancia`) es una copia completa del
portátil, no un clon limpio:

- `garage` en `28df904` y el worktree `../stravagancia-garage-050` en `66ea10b`
  (rama `garage-050-anillos`, 72 commits sobre `garage`), igual que en el portátil.
- Mismos cambios sin commitear que allí (Beads, spec de Anillos, CLAUDE.md,
  handoff, estado de progreso, base de Metabase, `.serena/`).
- `origin/garage` sigue en `e09bfb0`: nada se ha subido. **Sin push salvo
  petición del usuario.**
- Es una copia, no una sincronización: el portátil y el VPS divergen desde ahora.
  Coordina con el usuario antes de commitear en uno u otro. El estado de Beads
  (`.beads/`) también diverge.
- No sé cómo se copió (rsync o similar); no lo he comprobado.

## 2. Lo que hay y lo que no hay en el VPS

- **`.env` presente** (387 bytes, permisos 644: legible por cualquiera en el
  servidor). No lo he leído. Según CLAUDE.md ahí viven credenciales de Neon
  (`DB_*`, `NEON_PASSWORD`) y de Strava. **No lo abras ni lo muestres**; las
  pruebas lo bloquean a propósito. Conviene que el usuario decida si debe estar
  en el VPS y haga `chmod 600 .env` (no lo he tocado; no sé quién lo copió).
- **Strava real** la ejecuta el usuario, nunca la IA. Neon/producción: sólo
  lectura si hace falta contexto; mejor no usarla desde aquí.
- **Datos reales del usuario** (volcado de ProBikeGarage, bicis, `gear_id`, km)
  viven en `~/.cache/stravagancia/` del portátil. En el VPS ese directorio **no
  existe**; no lo reconstruyas. `maxi` y `maxi-manual` no existen allí; la demo
  ficticia (`demo`) se rehace con el seed.
- **`.venv` del repo**: existe en el VPS y es de Linux (Python 3.11.18; lo
  reconstruyó el contenedor del portátil). CLAUDE.md pide no tocarlo. No he
  probado que funcione ni que tenga las dependencias; prueba con un venv propio
  fuera del repo.
- **Herramientas** (comprobado en un shell interactivo del VPS, 8 nov): están
  `bd` 1.3.4, `uv` 0.13.7, Claude Code 2.1.319 y `python3` 3.11.13 (mise). En un
  `ssh host cmd` no interactivo no salen en el PATH: usa `bash -ilc`. **Falta**
  `psql`/`pg_ctl`, necesarios para el PostgreSQL local aislado: habrá que
  instalarlo (pide permiso al usuario). Si usas `bd`, mismas reglas que en local
  (sección 6.2); su estado en el VPS es una copia que diverge.
- **Rutas de macOS** (`/Users/maxicombina/...`, `venv-macos`, `GARAGE_TEST_PYTHON`,
  alias `cp`/`rm`): ignóralas. El gancho de `.env` distingue mayúsculas en Linux,
  a diferencia de APFS (spec 044 §8).
- **Chrome del usuario** (Claude in Chrome): no existe allí.
- **Procesos del portátil** (demo 8766, tablero 8765, PostgreSQL 55433/55434) no
  están en el VPS. Recréalos con `tools/handoff/` (`garage_demo_pg.py`,
  `garage_local_strava.py`, …) **tras leerlos**: pueden asumir rutas de macOS.

## 3. Reglas que siguen vigentes (resumen; manda CLAUDE.md)

- Rama obligatoria `garage`. **Sin push, sin commit y sin despliegue salvo
  petición expresa.** `main` intacto.
- Nada de `git clean`, `reset`, `checkout` de archivos ni `stash`: hay mucho
  trabajo sin seguimiento.
- **No arrancar Docker Compose completo**: su servicio Django apunta a Neon y
  corre migraciones en producción (ya pasó el 12 oct). Sólo PostgreSQL local
  aislado.
- Migraciones **0009–0012 son sólo locales** (no están en Neon). La siguiente
  es la **0013**. Las nuevas, sólo aditivas; no editar ni reordenar 0001–0008.
- Pruebas: `python -m pytest` con `settings_test` y PostgreSQL real dedicado;
  sin SQLite, sin HTTP real. No desactivar las protecciones del bootstrap. Tests
  primero, y enseñar la salida real: «o lo has ejecutado, o dices que no».
- Strava como fuente de Garage: solo «modo token»; OAuth por usuario
  (garage-040) sin empezar. Nunca reutilizar las tablas Activity del legado.
- Fotos: sin bucket ni credenciales hasta propuesta y autorización (garage-010).
- Garage y Stravagancia son apps distintas.

## 4. Cómo trabaja el usuario con los agentes

- Sesión principal orquesta, documenta y verifica; **todo lo que sea implementar
  lo hace un agente `model: "opus"`**, nunca otro modelo salvo orden expresa.
- **Un agente a la vez**, con hasta 3 rondas de revisión por bloque («prefiero 3
  rondas, pero más lento»). Una tarea de producto y un escritor de modelos/
  migraciones a la vez.
- Revisión adversarial antes de dar algo por bueno; intenta refutar cada
  hallazgo reproduciéndolo antes de aceptarlo.

## 5. Estado del trabajo (verificado el 8 nov salvo lo marcado)

Verificado hoy en el portátil: `bd ready` sólo lista garage-045 y garage-047; worktree
`stravagancia-garage-050` en `66ea10b`.

| Tarea | Estado |
|---|---|
| garage-050 «Anillos» | **Pausada por el usuario el 4 nov.** 16 de 19 fases hechas en la rama `garage-050-anillos`. Faltan: revisor visual de F3 ronda 2, corrector y ronda 3 de F3, F4a–c con su revisión y la revisión final. **No relanzar hasta que el usuario lo pida.** El workflow `wf_e92e9968-3fe` sólo se reanuda desde la sesión original del portátil; en otro sitio hay que seguir a mano desde la fase en que quedó (cada fase hecha es un commit). |
| garage-045 (fusión de `main`) | Adoptada en `garage` (`28df904`). Beads aún la muestra abierta: ciérrala sólo con el usuario. |
| garage-051 (más estadísticas) | Después de 050. Detalle en `bd show garage-051`. Migración 0013 prevista. |
| garage-047 (fricciones de UI) | El usuario pidió arreglarlas tras 050; anotar cada una en Beads con su commit. |
| garage-052 | Repaso con el usuario antes de prod; lo cierra él. |
| garage-053 | Posponer bici o componente entero. Después de 050. |
| Calorías | Después de prod. |
| garage-023 despliegue, 031 PWA en teléfono, 010 fotos, 040 OAuth | No empezar. |

Suite de referencia: 2801 + 45 subcasos en `garage` (3 nov) y 3382 passed más un
fallo esperado en la copia de Anillos (dato de un agente, **no verificado por
mí**). En un VPS nuevo, ejecuta la suite antes de fiarte de estas cifras.

Sin decidir por el usuario: bucket de fotos, objetivo y tendencia (Grafana), qué
más de `docs/garage-vs-probikegarage.md` entra antes de prod, gancho de `.env`
sensible a mayúsculas (APFS no lo es, Linux sí: ojo si el VPS lo toca), y las
decisiones D1–D11 de garage-044.

## 6. Primeros pasos concretos

1. Confirma con el usuario el encargo (sección 0) y quién commitea (sección 1).
2. Comprueba rama, `git status`, `git log`, y que `bd ready` funciona
   (`bd --sandbox --dolt-auto-commit off --actor claude ...`; sin `bd init`,
   `sync` ni push/pull de Dolt). No edites `.beads/` a mano.
3. Levanta PostgreSQL local aislado y corre la suite; informa del resultado
   real, incluidos fallos.
4. Trabaja una tarea cada vez, de las de la sección 5, con agentes Opus.
5. Al terminar, actualiza `docs/garage-progress-state.json` y deja en el
   handoff: tarea, archivos, hallazgos pendientes, pruebas ejecutadas, procesos
   activos y siguiente acción.

## 7. Seguridad en un servidor expuesto

- No expongas la demo (8766) ni el tablero (8765) a Internet: enlázalos a
  127.0.0.1 y accede por túnel SSH. Las contraseñas de la demo son triviales
  (el nombre de usuario).
- Nada de secretos en el repo, logs ni en este documento.
