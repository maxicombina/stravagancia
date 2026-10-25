# Especificación garage-034: posponer vencimientos

Fecha: 17 de octubre de 2026. Autor: Claude. Tarea Beads: `garage-034`.
Pedido del usuario tras el análisis de ProBikeGarage
(`docs/research/2026-10-17-probikegarage-rea.md`): «posponer un vencimiento de
algo, ya sea por días, km, etc.». El usuario está ausente y pidió: «ante la duda,
documenta las opciones y elige una». Rama `codex/garage-plan`; sin commits,
staging, push ni despliegue. **Una migración aditiva nueva (0009), sólo en
PostgreSQL local; nunca en Neon.**

## 1. Punto de partida

Una `MaintenanceRule` (también la «Vida útil» de garage-033) vence con el primer
umbral alcanzado; la presentación la muestra como Vencido, Revisar o Próximo
(«requiere atención») y no hay forma de silenciarla salvo registrar una
intervención o cambiar la regla. ProBikeGarage permite posponer una bici, un
componente o un intervalo una cantidad de un tipo (km, días…), ver lo que queda y
dejar de posponer.

## 2. Decisiones (con las opciones descartadas)

| Tema | Opciones | Elegida y por qué |
|---|---|---|
| Qué se pospone | a) una regla; b) todas las reglas de una bici o pieza; c) ambas | **a) una regla.** El aviso es por regla; posponer «todo» ocultaría avisos que la persona no miró. b) puede venir después como atajo sobre a). |
| Cantidad | a) un único tipo (como ProBikeGarage); b) km, horas, salidas y días a la vez, **lo primero que llegue** | **b)**, coherente con las reglas y la vida útil de Garage. Al menos una cantidad. Termina con la primera que se alcanza: es lo prudente porque el aviso vuelve antes. |
| Desde cuándo | a) ahora; b) fecha elegible | **a) ahora** (hora del servidor). El servicio admite `at` para pruebas, pero nunca futuro ni anterior al último inicio o fin de un aplazamiento de la regla (sin solapes). |
| Cuándo se ofrece | a) siempre; b) sólo si requiere atención | **b) en la interfaz**: el botón sólo aparece si la regla está Vencida, para Revisar o Próxima. El servicio no lo exige: un aplazamiento sobre una regla al día queda latente y sólo actúa si vence dentro de lo pospuesto. |
| Fin | a) intervención posterior al inicio; b) **cualquier otra referencia** | **b)**: el aplazamiento guarda la referencia de la regla al crearse (`reference_at` y la intervención, si la hay) y sólo vale mientras la referencia actual sea esa. Así lo termina una intervención nueva aunque tenga fecha anterior (el formulario redondea la hora al minuto) y lo recupera borrarla. También terminan: alcanzar una cantidad (calculado), «Dejar de posponer», otro aplazamiento de la regla y mover la regla a otro destino o tipo (`save_maintenance` lo cierra). |
| Uso dudoso | a) contar lo desconocido como cero; b) no ocultar el aviso con uso desconocido | **b).** El aplazamiento está **activo** sólo si todas sus cantidades tienen un valor conocido por debajo de lo pospuesto; con uso pendiente de calcular el aviso se ve. Los km, horas y salidas observados son siempre un mínimo (el histórico nunca es completo): es una excepción consentida por la persona al posponer, y lo que queda se muestra «como máx.» en cada cantidad. **Límite:** todo aplazamiento lleva días como máximo (30 por defecto, visible y editable), para que un aviso no quede oculto para siempre si se dejan de registrar salidas. |
| Empeora durante el aplazamiento | a) dejar de ocultar al empeorar; b) mantenerlo pospuesto y mostrar el estado real | **b)**: posponer es justamente seguir usando la pieza; el estado real se ve en cada fila pospuesta («Vencido · quedan…»), en la ficha y en los detalles técnicos. |
| Estado mostrado | a) estado nuevo; b) marca sobre el estado real | **a) «Pospuesto»** (icono de despertador), sólo cuando el estado real requiere atención y el aplazamiento está activo. No cuenta en «Requiere atención». El estado real sigue visible en la ficha (anillo y cifras) y en los detalles técnicos. |
| Historial | a) campos en la regla; b) modelo propio | **b) `MaintenanceSnooze`**: conserva cada aplazamiento (inicio, cantidades, fin) y se exporta. |
| Administración Django | registrar o no | **No** en esta versión: se gestiona desde la web. |

## 3. Modelo y migración `0009_maintenancesnooze`

`MaintenanceSnooze(OwnedResource)`:

- `rule`: FK a `MaintenanceRule`, `CASCADE` (borrar la regla borra sus
  aplazamientos: no son historia de la pieza), `related_name="snoozes"`.
- `started_at` (DateTime, obligatorio), `ended_at` (DateTime, nulo = registro
  abierto; puede estar agotado o haber dejado de valer, eso se calcula).
- `reference_at` (DateTime, obligatorio) y `reference_event_id` (UUID, nulo):
  la referencia de la regla al posponer. Sin referencia no se puede posponer.
- `distance_m`, `moving_time_s` (Decimal 20,3), `ride_count`, `calendar_days`
  (enteros positivos), nulos = sin esa cantidad. Mismos límites y precisión
  exacta que las reglas (`exact_usage_value`).
- `notes` (texto, opcional).
- Restricciones: al menos una cantidad; cada cantidad > 0 y dentro del máximo;
  `ended_at >= started_at`; como máximo **un aplazamiento abierto por regla**
  (`UniqueConstraint(rule) WHERE ended_at IS NULL`).
- `clean`: instantes con zona; la regla es del mismo propietario.

Migración sólo aditiva (CreateModel). 0001–0008 no se tocan.

## 4. Servicio `garage/services/snoozes.py`

- `snooze_rule(actor, rule, *, distance_m=None, moving_time_s=None,
  ride_count=None, calendar_days=None, at=None, notes="")`: bajo el bloqueo del
  propietario; regla propia (404 ajeno); cierra el aplazamiento abierto de esa
  regla en `at` y crea el nuevo desde `at`. Error si no hay cantidades.
- `end_snooze(actor, rule, *, at=None)`: cierra el aplazamiento abierto; devuelve
  si había uno.
- `open_snooze(actor, rule)`: el abierto o `None`.

## 5. Cálculo (`maintenance_due`)

`MaintenanceDue` gana `snooze: SnoozeState | None = None` (al final, con valor
por defecto). Para cada regla: el aplazamiento con `started_at <= T` y
(`ended_at` nulo o `> T`), el más reciente; sólo cuenta si la regla tiene
referencia y `started_at >= referencia`. Sus métricas se calculan como las de la
regla pero desde `started_at` (sin lecturas): km/horas/salidas con los mismos
hechos (uso por objeto, o salidas de la bici), días de 24 h transcurridos. Estado
del aplazamiento: `reached` si alguna cantidad alcanzada, `unknown` si alguna sin
valor, `active` si no. Una consulta más por snapshot, sin escrituras en GET.

## 6. Presentación

- `STATES["snoozed"] = ("Pospuesto", "clock")`; severidad: tras Vencido,
  Revisar y Próximo, antes de Sin datos.
- `wear(due)`: `snoozed` verdadero si el estado real requiere atención y el
  aplazamiento está activo; `state` pasa a `snoozed`; `real_state` conserva el
  real; `snooze_metrics` con lo que queda («quedan 150 km o 5 días»).
- Inicio: los pospuestos salen de «Requiere atención» y del contador por bici;
  fila «N avisos pospuestos» hacia Taller.
- Taller: sección «Pospuestos» con lo que queda, cada fila a su página.
- Ficha de componente: en el panel de la regla, «Posponer» si requiere atención;
  si está pospuesta, «Pospuesto: quedan …; después vuelve a avisar», «Cambiar» y
  «Dejar de posponer».
- Ficha de bici: grupo «Pospuestos» bajo «Requiere atención»; las filas de
  reglas de la propia bici llevan a su página de aviso si requieren atención o
  están pospuestas (hoy enlazan a la misma ficha), si no a editar la regla.
- Revisión de salida: los cambios de estado incluyen «Pospuesto → Vencido».
- Página `maintenance/maintenance-rule/<uuid>/snooze/` (`maintenance-rule-snooze`),
  titulada con el nombre de la regla: estado real y, como acción principal,
  «Registrar <tipo>» (formulario de intervención con destino y tipo elegidos,
  `?type=`); si hay aplazamiento activo, lo que queda y «Dejar de posponer»
  (POST `action=end`); «Posponer el aviso» / «Volver a posponer desde ahora» con
  atajos que son botones de envío (`preset`, funcionan sin JavaScript: 1 semana,
  2 semanas, 1 mes = 30 días, 10 % de cada umbral redondeado hacia arriba con
  mínimo 1 y 30 días si la regla no tiene días) y formulario km, horas, salidas,
  días (obligatorio, 30) y nota. Un aplazamiento agotado o con uso desconocido se
  explica. Enlace a editar la regla o la vida útil.
- Detalles técnicos de avisos: «Pospuesto desde …» con sus cantidades.

## 7. Exportación

Tabla nueva `snoozes` (`rule_id`, `started_at`, `ended_at`, cantidades, `notes`),
referencia `rule_id → maintenance_rules`. Formato `garage-export` versión 1
ampliado de forma aditiva (un lector de la versión 1 puede ignorar la tabla
nueva); se documenta en `docs/garage-export.md`.

## 8. Pruebas

Modelo (restricciones, propiedad), servicio (crear, reemplazar, cerrar, 404
ajeno, sin cantidades), cálculo (activo, alcanzado por cada métrica, primero que
llega, desconocido sin materialización, histórico parcial, intervención
posterior lo invalida, borrar la intervención lo recupera, `at` anterior al
inicio, aplazamiento cerrado), presentación (estado y orden, textos), pantallas
(Inicio, Taller, fichas, página, GET sin escrituras, 404 ajeno, CSRF/POST),
exportación y presupuesto de consultas. Suite completa, `check`,
`makemigrations --check`, capturas y revisión independiente.

## 9. Revisión de la especificación (17 oct)

Revisión independiente: 1 bloqueante y 7 importantes, todos resueltos antes de
cerrar el código (§2, §3 y §6 ya reflejan las decisiones):

- Bloqueante: una intervención con fecha redondeada al minuto quedaba antes del
  inicio y no terminaba el aplazamiento → se guarda la referencia al posponer.
- Mover la regla de destino o tipo → se cierra su aplazamiento abierto.
- Igualdad de fechas contradictoria → resuelto por la referencia guardada.
- Mínimo observado → excepción documentada, cantidades marcadas una a una y
  máximo de días obligatorio.
- Estado que empeora → se mantiene pospuesto con el estado real visible.
- `at` sin límites → nunca futuro ni anterior al último aplazamiento.
- Fin sólo calculado → textos para agotado y uso desconocido; `ended_at` nulo
  no significa activo (documentado en la exportación).
- Lugares olvidados → grupo en la ficha de bici, «Nada pendiente» en Inicio,
  `REFERENCES`, prueba de exportación ajena, `scoped_inventory`, revisión de
  salida, editor de la vida útil.
- Menores: atajos que funcionan sin JavaScript, nota, doble toque inocuo y
  aviso de que 0009 nunca debe llegar a Neon (Docker Compose migra al arrancar).

## 10. Revisión de código y re-verificación (18 oct)

Código: sin bloqueantes. Importante corregido: un aplazamiento activo sobre una
regla que aún no requiere atención (posponer por adelantado, o tras cambiar
umbrales) se describía como «pendiente de calcular» y no se podía terminar;
ahora la página distingue pospuesto, por adelantado, terminado y sin calcular,
siempre permite cerrarlo, y la ficha lo muestra («Pospuesto por adelantado»).
Menores corregidos: hora tomada tras el bloqueo, 404 si la regla desaparece,
días que quedan redondeados hacia arriba, estado real en las filas pospuestas de
la bici, textos vacíos, frase duplicada, sólo las cantidades alcanzadas, tope de
36 500 días en el atajo, pruebas de CSRF/405, ZIP y referencia movida.
Re-verificación: las siete correcciones verificadas; corregidos además la
concordancia («queda 1 día», «Se llegó a …»), textos cuando no hay aviso, el
enlace al aplazamiento desde filas de la bici y detalles técnicos.
