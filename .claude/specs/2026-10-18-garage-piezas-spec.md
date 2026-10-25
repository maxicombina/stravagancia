# Especificación garage-035: piezas anidadas

Fecha: 18 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-035`.
Pedido del usuario tras el análisis de ProBikeGarage: «lo de componentes
anidados». Ausente; pidió «ante la duda, documenta las opciones y elige una».
Rama `codex/garage-plan`; sin commits, staging, push ni despliegue. **Sin
modelos ni migraciones.**

## 1. Punto de partida

El dominio ya lo permite: `Installation.parent_item` monta un objeto dentro de
otro (casete y disco en la rueda trasera), con detección de ciclos en el tiempo,
posiciones exclusivas y uso que fluye hacia las piezas. Lo que falta:

- La ficha de componente sólo muestra sus piezas en el pliegue antiguo
  «Material montado sobre este objeto» (tarjetas de períodos).
- Montar una pieza se hace desde la pieza («Montar» → elegir «objeto de
  destino»), nunca desde el padre.
- Una intervención tiene un destino y un tipo: revisar una rueda y cambiarle el
  casete exige registrar dos veces (ProBikeGarage: «también se repararán todas
  las piezas, y sus intervalos de servicio, de los componentes seleccionados»).

## 2. Decisiones

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Propagar al registrar | a) implícita: registrar en el padre reinicia las reglas de todas sus piezas (ProBikeGarage); b) explícita: casillas con las reglas del destino y de sus piezas | **b).** En Garage cada intervención reinicia una regla concreta (lubricar no es cambiar el casete). Reiniciar en silencio reglas que no se hicieron sería falso. Ninguna casilla viene marcada. |
| Dónde | a) página nueva «mantenimiento en grupo»; b) el formulario actual con una sección «También en…» | **b)**: reutiliza fecha, notas, importe y moneda ya validados (coma decimal, hora local, moneda habitual). La intervención principal es la del formulario; cada regla marcada añade otra con su destino y tipo, la misma fecha y la misma nota. |
| Importe | a) repartir; b) sólo en la principal; c) uno por fila | **b)**: el importe es de la intervención principal; se dice en el formulario. Las demás quedan sin importe y se pueden editar después. |
| Alcance | — | El destino del formulario y todo lo montado en él ahora (para una bici, también lo anidado), sin objetos retirados. Se recalcula al enviar: una regla que ya no está en el alcance es un error y no se guarda nada. |
| Duplicado | — | Una regla marcada con el mismo destino y tipo que la principal no crea otra intervención. |
| Piezas en la ficha | — | Sección «Piezas» con las piezas montadas ahora (directas), su peor estado y «desde el…»; enlace «Añadir pieza». Cada pieza se gestiona desde su ficha (desmontar, reemplazar, mover). |
| Añadir pieza | a) reutilizar «Montar» desde la pieza; b) página desde el padre | **b)** `items/<uuid>/parts/new/`: elegir un objeto propio activo sin montar en ese instante (ni el propio objeto) y la fecha local; crea el montaje con `create_installation` (valida ciclos, retiros y solapes). |
| Ficha de una pieza | — | La entradilla dice «En <padre> · <bici>» cuando el padre va montado en una bici. |

## 3. Servicio `garage/services/parts.py` (como quedó implementado)

- `scope(actor, target, *, at)`: lista ordenada `(objeto o bici, padre o None)`:
  el destino y sus piezas montadas en `at` a cualquier profundidad (para una bici,
  lo montado directamente y lo anidado), sin retirados en `at`.
- `scope_rules(actor, target, *, at)`: reglas de esos destinos, en ese orden.
- `register_together(actor, main, rule_ids, *, shown)`: dentro de la transacción
  de la intervención principal; sin reglas marcadas no compara nada; si no,
  calcula el alcance en la fecha de `main` y lanza `ScopeChanged` si difiere de
  `shown`; crea una intervención por regla (sin importe) salvo la duplicada.
- `placement(actor, item, *, at)`: piezas directas y bici raíz en una consulta
  (para la ficha). `ancestors`, `part_candidates` y `add_part` (errores de
  montaje traducidos por código, `SPANISH`).

## 4. Pantallas

- Ficha de componente: sección «Piezas» tras «Montajes» (si tiene piezas o puede
  tenerlas): filas como «Montado ahora» de la bici; «Añadir pieza». El pliegue
  antiguo se conserva para el historial completo.
- Registrar mantenimiento (`service-event-create?item=` o `?bike=`, sólo al crear):
  sección «También en…» con una casilla por regla del alcance, agrupadas por
  destino («Rueda trasera › Casete»), con su estado. Texto: «Cada regla marcada
  registra otra intervención con la misma fecha y nota; el importe es sólo de la
  principal». Mensaje al guardar: «Registradas también: Vida útil de Casete,
  Revisión de Disco».
- `items/<uuid>/parts/new/` (`item-part-create`): formulario de pieza; volver a la
  ficha del padre.

## 5. Pruebas

Alcance (bici con anidados, objeto con nietos, retirados fuera, montajes
cerrados fuera), registro conjunto (atómico, sin importe en las extra, duplicado
omitido, regla fuera de alcance rechazada sin escribir nada, ajena 404 o error),
reinicio de las reglas marcadas (y fin de sus aplazamientos de garage-034),
pantallas (sección Piezas, añadir pieza con ciclo y solape rechazados, entradilla
anidada, formulario con casillas sólo al crear), GET sin escrituras. Suite
completa, `check`, `makemigrations --check`, capturas y revisión independiente.

## 6. Revisión de la especificación (18 oct) y decisiones añadidas

Revisión independiente: 1 bloqueante, 5 importantes y 7 menores. Decisiones:

1. **Instante del alcance (bloqueante).** El alcance es lo montado en la fecha de
   la intervención (`performed_at`), con `[inicio, fin)` y retiros en esa fecha.
   El GET lo muestra para la fecha inicial (ahora); el formulario envía la lista
   de reglas mostradas (`shown_rules`). Al enviar, bajo el bloqueo, si el alcance
   en la fecha elegida no coincide con lo mostrado, se vuelve a mostrar con la
   lista nueva y el aviso «Con esa fecha cambian las piezas montadas: revisa la
   lista», sin guardar nada. Con fecha futura no se admiten extras.
2. **Atomicidad.** La intervención principal y las extra se guardan en una sola
   transacción en la vista (`transaction.atomic` alrededor de `form.save()` y
   `register_together`); cualquier error deshace todo y vuelve a mostrar el
   formulario con las casillas marcadas.
3. **Destino fijo.** Cuando la sección se muestra (`?item=` o `?bike=` con reglas
   en el alcance), el destino del formulario queda fijo (campo deshabilitado);
   «Otro destino» enlaza al formulario sin destino.
4. **Vida útil.** La casilla de la vida útil de una pieza dice «Sustitución de
   <pieza> (misma ficha: reinicia su vida útil)», con la nota «¿Pieza nueva con
   ficha propia? Usa Reemplazar en su ficha».
5. **Lista larga.** Un `<details>` por destino con el número de reglas; abiertos
   los que requieren atención o están pospuestos, primero el destino principal.
   Se oculta la regla que coincide con el destino y el tipo ya elegidos (`?type=`).
6. **Errores en español** al añadir pieza: ciclo, solape, posición ocupada,
   retirado y referencia inválida por código.
7. **Añadir pieza.** Candidatos: objetos propios activos y sin montar ahora, sin
   el propio objeto ni sus antepasados actuales; la fecha elegida se valida al
   guardar. Posición exclusiva opcional (p. ej. `brake_disc`) y notas. Sin enlace
   para un padre retirado o con retiro programado.
8. **Consultas.** Estados de las piezas desde el mismo `maintenance_due` de la
   ficha; una sola lectura de montajes abiertos para piezas y entradilla.
9. **Entradilla.** «En <padre> · <bici raíz>» subiendo por los padres; «En
   <padre>» sin bici.
10. **Alcance seguro.** Conjunto de visitados ante datos inconsistentes; el
   material que sólo cuenta por perfiles de uso (casco, zapatillas) no es una
   pieza montada y no entra en el alcance.
11. **Aplazamientos.** No se llama a `end_snooze`: el aplazamiento deja de valer
   solo cuando cambia la referencia. Una intervención extra más antigua que la
   última de su regla no reinicia la cuenta y el mensaje lo dice.
12. **Propiedad.** Una regla enviada ajena o fuera del alcance es un error del
   formulario («Elige una opción válida»); padre ajeno en añadir pieza → 404;
   candidato ajeno o retirado → rechazado.
13. **Documentación.** El dominio describe las intervenciones extra: no quedan
   enlazadas a la principal (editarla o borrarla no las cambia) y el importe
   sólo es de la principal. Un doble envío duplica todas.

## 7. Revisión de código y re-verificación (18 oct)

Código: sin bloqueantes; 2 importantes corregidos con pruebas: el formulario
podía quedar trabado si, con la fecha elegida, la lista quedaba vacía (ahora sin
casillas marcadas no se compara y la sección se mantiene con «En esa fecha no
hay otras reglas en lo montado»), y las casillas no nombraban su pieza (ahora
«Sustitución de <pieza> (…)» o un prefijo oculto para lectores de pantalla).
Menores: tipo comparado por UUID, texto oculto en lugar de `aria-label`, código
muerto, `?type` conservado, mensaje neutro, `LIFE_TYPE`, más pruebas (bici,
duplicados, consultas constantes). Re-verificación: todo verificado.
