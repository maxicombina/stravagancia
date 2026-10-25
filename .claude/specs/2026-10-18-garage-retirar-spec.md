# Especificación garage-038: retirar al reemplazar y retirar con lo montado

Fecha: 18 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-038`.
Origen: análisis de ProBikeGarage («Reemplazar componente: … opción de retirar el
antiguo»; «Retirar una bici o un componente: se puede retirar también lo que
lleva montado o dejarlo disponible»). Usuario ausente: «ante la duda, documenta
las opciones y elige una». **Sin modelos ni migraciones.**

## 1. Punto de partida

- Reemplazar (`installation_action` `replace`) cierra el montaje saliente y abre
  el entrante; la pieza que sale queda activa y sin montar. Si tenía vida útil por
  días, sigue contando (ya se avisa).
- Retirar (`retire`) marca `retired_at` y cierra los montajes abiertos de esa bici
  u objeto y los de sus piezas directas (`_close_for_retirement`): lo montado queda
  disponible, sin retirar.

## 2. Decisiones

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Retirar la que sale | a) siempre; b) casilla marcada; c) casilla sin marcar | **c)**: no cambia lo que ya hace hoy, y cambiar ruedas de invierno o un sillín no es tirar la pieza. La casilla explica que se puede reactivar. |
| Cuándo se retira | — | En el mismo instante del reemplazo y en la misma transacción que el reemplazo y la herencia de vida útil: todo o nada. |
| Retirar con lo montado | a) siempre; b) casilla sin marcar con la lista | **b)**: la página de retirar lista lo montado en ese instante (lo directo y lo anidado, como el alcance de garage-035) y ofrece «Retirar también lo que lleva montado (3)». Sin marcar, como hoy: queda disponible. |
| Orden | — | Se calcula la lista antes de cerrar nada; se retira el destino y después cada pieza en ese instante, en una transacción. Un error en cualquiera deshace todo. |
| Vida útil de la que sale | — | Si se retira, no se avisa de que «sigue contando días» (deja de avisar al estar retirada). |

## 3. Servicio

`garage/services/retirement.py` (nuevo, sobre `retire_inventory` y
`parts._scope`):

- `mounted_in(actor, target, *, at)`: objetos montados en la bici u objeto en
  `at` (directos y anidados), sin el propio destino.
- `retire_with_parts(actor, target, *, at, parts)`: en una transacción retira el
  destino y, si `parts`, todo lo de `mounted_in` calculado antes de retirar.

## 4. Pantallas

- Reemplazar: casilla «Retirar <pieza que sale>» con ayuda «Deja de avisar y de
  aparecer como disponible; se puede reactivar».
- Retirar: lista de lo montado y casilla «Retirar también lo que lleva montado»;
  mensaje con lo retirado.

## 5. Pruebas

Reemplazo con y sin retirar (atómico con la herencia; sin el aviso de días),
retirar con y sin piezas (bici con anidados, objeto con nietos, lista calculada
antes de cerrar), errores que deshacen todo, ajenos 404, GET sin escrituras.

## 6. Revisión independiente (18 oct)

Sin bloqueantes; 2 importantes corregidos con pruebas: el conflicto con montajes
posteriores salía en inglés y sin nombrar la pieza (`retire_one` lo traduce y la
nombra), y retirar lo que sale desmontaba sus piezas sin decirlo (la ayuda y el
mensaje las nombran). Menores: la lista mostrada se compara con la de la fecha
elegida (`shown_parts`; si cambia, se muestra la nueva y se confirma guardando
otra vez), casilla también con retiro programado, plurales y género, reactivar no
reactiva las piezas, un reemplazo futuro no retira. Límite: cada objeto retirado
reconstruye el uso (una bici con cuatro piezas, cinco reconstrucciones).

Re-verificación: con un retiro ya programado la casilla no podía funcionar (sus
montajes ya se cierran en esa fecha): no se ofrece, ni «Retirar lo que sale» en
Reemplazar; las piezas se retiran desde su ficha. La ayuda y el mensaje de
Reemplazar nombran sólo las piezas directas (lo que llevan dentro sigue en ellas);
`retirement_overlap` también se traduce; «Reactivada» para bicis.
