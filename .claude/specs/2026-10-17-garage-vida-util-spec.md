# Especificación garage-033: vida útil por componente

Fecha: 17 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-033`.
Pedido del usuario: «cada componente ha de tener vida útil por tiempo o por km.
o el primero de ambos. mejor que probikegarage». Rama `codex/garage-plan`; sin
commits, staging, push ni despliegue. **Sin modelos ni migraciones.**

## 1. Punto de partida

El motor ya lo permite: una `MaintenanceRule` por objeto con km, horas, salidas
o días; vence con el primer umbral alcanzado, avisa al 90 % y, con histórico
incompleto, el uso es un mínimo («≥»). Su referencia es la última intervención
del mismo tipo y objeto o, sin ella, un ancla explícita (`anchor_at`); sin
ninguna, «Sin datos». Lo que falta es hacerlo visible y fácil:

- hoy hay que crear un tipo, luego una regla y fijar el ancla a mano;
- el tiempo va en días;
- al reemplazar una pieza, la nueva no hereda nada.

## 2. Decisiones

| Tema | Decisión |
|---|---|
| Modelo | La vida útil es la regla **de un objeto** con el tipo de intervención del propietario llamado «Sustitución» (se crea al primer uso; único por nombre sin distinguir mayúsculas; no se puede renombrar mientras algún objeto la use). Se muestra como «Vida útil»; una regla de bici de ese tipo es una regla normal. Registrar una intervención «Sustitución» la reinicia (pieza que se cambia conservando la ficha). |
| Umbrales | km, horas en movimiento y tiempo. Lo primero que llegue. Al menos uno: vaciarlos todos es un error y quitarla es un botón explícito. Un umbral de salidas puesto en el Taller se conserva y se muestra. |
| Tiempo | Número + unidad (días, meses, años). 1 mes = 30 días y 1 año = 365 días; se guarda en días y se muestra el resultado («= 730 días»). Al editar: años si es múltiplo de 365, meses si lo es de 30, si no días. |
| Inicio | Fecha y hora local «Cuenta desde», no futura. Por defecto: inicio de uso registrado (`acquisition_anchor_at`); si no, fecha de compra (medianoche local); si no, primer montaje; si no, ahora. Si hay alguna «Sustitución» registrada, cuenta desde la última (como cualquier regla) y la página lo dice. |
| Repuesto | Al reemplazar un montaje, casilla «La pieza nueva hereda la vida útil» (sólo si la saliente tiene). Crea la misma vida útil en la entrante desde el instante del reemplazo, en la misma transacción; si la entrante ya tenía «Sustituciones», registra otra en ese instante para que cuente desde ahí. Avisa si la entrante ya tenía vida útil y de que la saliente sigue contando días. |
| Sugerencias | Orientativas, por tipo de pieza deducido como el icono: cadena 3.000 km; casete 10.000 km; cubierta 4.000 km; pastillas 1.500 km; rueda 20.000 km; zapatillas 10.000 km; casco 5 años. Botones que rellenan el formulario (sin JavaScript se leen como texto). Se indica «depende del uso y del terreno». |
| Material usado | Sus km anteriores no cuentan para esta vida útil en esta versión; se dice en el formulario. |

## 3. Servicio `garage/services/lifespan.py`

- `LIFE_TYPE = "Sustitución"`.
- `lifespan_rule(actor, item)`: la regla de vida útil del objeto o `None`.
- `default_start(actor, item, *, zone, at)`: inicio por defecto (§2).
- `set_lifespan(actor, item, *, distance_m, moving_time_s, calendar_days, start)`:
  en una transacción con el bloqueo del propietario crea el tipo si falta y
  crea, actualiza o (todo vacío) elimina la regla. Valida con los servicios
  existentes (`save_maintenance`, `delete_maintenance`); propiedad y 404 como
  el resto.
- `inherit_lifespan(actor, *, outgoing, incoming, at)`: copia umbrales con
  ancla `at` si la entrante no tiene; devuelve la regla o `None`.

## 4. Pantallas

- Ficha de componente: la vida útil va primero, titulada «Vida útil», con la
  nota «Vence con lo primero que llegue: 3.000 km o 365 días» y el enlace
  «Editar vida útil». Sin vida útil: panel «Define su vida útil» con enlace.
- `items/<uuid>/lifespan/` (`item-lifespan`): formulario (km, horas, tiempo +
  unidad, desde), sugerencias, «Quitar vida útil». Volver a la ficha.
- Inicio y Taller: las filas de esa regla dicen «Vida útil» en vez del tipo.
- Reemplazar montaje: casilla de herencia y mensaje «La pieza nueva hereda la
  vida útil: …».
- Formularios de km y horas con coma decimal (`DecimalInput` de 032).

## 5. Revisión independiente (17 oct)

Sin bloqueantes. Corregido con pruebas: referencia real con sustituciones
anteriores, umbral de salidas visible, inicio futuro rechazado, tipo por nombre
(reglas de bici y renombrado), texto de períodos personalizados, mensajes de
herencia, enlace de «Sin datos», «… o …», días en vivo y accesibilidad.

## 6. Pruebas

Servicio (crear, actualizar, quitar, tipo único, propiedad, valores exactos,
inicio por defecto en cada caso, herencia sí/no), formulario (unidades de
tiempo y su ida y vuelta, coma, al menos un umbral, fecha local), ficha y
filas con «Vida útil», reemplazo con y sin herencia, intervención
«Sustitución» que reinicia, 404 ajeno, GET sin escrituras. Suite completa,
check, makemigrations, capturas y revisión independiente.
