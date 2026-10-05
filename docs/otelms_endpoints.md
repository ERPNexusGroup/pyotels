# Endpoints de OtelMS

Inventario de lo que se ha confirmado contra el portal real (hotel **18330**),
con la evidencia que lo respalda. Todo lo de aquí se descubrió abriendo
scripts de `tests/manual/` contra el portal, no leyendo el código: si un
endpoint no está en esta tabla, no está verificado.

Regla de la casa: **HTTP primero.** Si un endpoint devuelve HTML server-side,
se usa `requests`/`httpx`. Camoufox/Playwright queda como respaldo, y solo
en `*_playwright.py`.

---

## 1. Login

| | |
|---|---|
| `GET /login_c2/single_login?hmsid={hotel_id}` | Fija la cookie de sesión. Sin este GET, el POST devuelve la página de login. |
| `POST /login_c2/do_single_login` | `hotel`, `login`, `password`, `action=login`. Header `Referer` al `single_login` correspondiente. |

El POST responde con el HTML de destino, no con un JSON: **el login se da por
bueno si la respuesta contiene `reservation_c2/calendar`**, no por el código
HTTP (que es 200 también cuando falla).

Ojo con cómo lo devuelve: **no es un 302, es un
`<meta http-equiv='refresh' content='0;url=/reservation_c2/calendar'>`.** Un
cliente con `follow_redirects=True` no lo sigue, la respuesta se queda en
`/login_c2/do_single_login` y la sesión queda a medio hacer. Por eso:

- El criterio de éxito es el refresh del body, nunca la URL final. Comprobar
  `"login" in resp.url.path` da falso negativo **siempre** con este portal:
  eso es lo que hacía que `get_authenticated_http_session` lanzara
  `AuthenticationError` sin excepción. Corregido en `scraping/auth.py`.
- Hay que hacer GET al destino del refresh para completar las cookies.

Origen: `scraping/auth.py` y `services/calendar_sync_service.py`. Verificado en
cada script de `tests/manual/`.

---

## 1.1 Login HTTP asíncrono (`get_authenticated_http_session`)

Devuelve un `httpx.AsyncClient` ya autenticado. **No se puede meter en
`async with`**: el login ya lo usó para las peticiones y httpx sólo acepta
`__aenter__` una vez, sobre un cliente sin abrir. Se cierra con
`await client.aclose()`. Es lo que hace `_client_for()` en
`scraping/restrictions.py`.

---

## 2. Calendario

| | |
|---|---|
| `GET /reservation_c2/calendar` | HTML completo. `GET` no necesita parámetros: devuelve el mes en curso. |
| `GET /reservation_c2/calendar?date=YYYY-MM-DD` | other month. Verificado cambiando el parámetro de fecha. |

Las reservas no vienen en una tabla sino dispersas en el marcado del grid, con
el `resid` como atributo (`div[resid='...']`). Los parsers viven en
`scraping/calendar_markup_v2.py` (v2, el bueno) y `scraping/calendar_extract.py`
(v1, el que usaba `parse_folio`).

**Cuidado con `Descripcion`/tooltip:** el mismo `resid` puede aparecer varias
veces en el HTML (una por cada celda del grid que ocupa). `tests/manual/test_calendar_duplicate_resids.py`
lo verificó: 13 reservas, 13 `resid` distintos, 0 duplicados. Hay que
deduplicar por `resid`.

Evidencia: `tests/manual/test_http_calendar_ua.py`.

### 2.1 Disponibilidad por categoría — la fila resumen

**No existe endpoint de disponibilidad.** El portal la publica dentro del
propio calendario, en una fila por categoría que `parse_categories_v2`
descartaba por pensar que era ruido: celdas con `room_id="0"` y `category_id`,
con un `div.calendar_sum` dentro.

```html
<td category_id="13" class="calendar_td" day_id="20731" room_id="0">
  <div class="calendar_sum" id="availability_13_20731" style="width: 35px;">8</div>
</td>
```

`day_id` es el mismo serial que usan las celdas normales (días desde epoch), y
el `id` del div es `availability_{category_id}_{day_id}`.

Con el calendario del 2026-10-05 (46 días, del 5 de octubre al 19 de noviembre)
salen **414 celdas: 9 categorías × 46 días**.

**El número no se puede recalcular.** Se contrastó contra
`habitaciones - ocupadas` y difieren en **163 de 414 celdas**:

| Categoría | Habitaciones | Fecha | OtelMS | Calculado |
|---|---|---|---|---|
| 13 Matrimonial | 12 | 2026-10-05 | 8 | 10 |
| 13 Matrimonial | 12 | 2026-10-09 | 0 | 7 |
| 13 Matrimonial | 12 | 2026-10-12 | 10 | 12 |
| 14 Doble Individual | 4 | 2026-10-05 | 4 | 4 |

Dos motivos: el hotel retiene habitaciones por encima de las ocupadas (la
categoría 13 nunca pasa de 10 aunque tenga 12), y hay días a `0` que no están
bloqueados por reservas sino cerrados a propósito (fines de semana, inventario).
Para las categorías pequeñas (4, 2, 1 habitaciones) los dos números sí coinciden.

Implementación: `parse_availability_v2()` y la tabla `category_availability`
(ver `docs` y la Tarea 1.1 del `VALIDATION_REPORT.md`).
Evidencia: `tests/manual/test_calendar_availability.py`.

---

## 3. Folio — `/reservation_c2/folio/{resid}`

Es el endpoint que trae los consumos y los pagos. **No está en el modal del
calendario**: `ModalParser` solo ve un resumen (huésped, fechas, tarifa,
saldo), así que pedir detalle por modal nunca dará services ni payments.

| | |
|---|---|
| `GET /reservation_c2/folio/{resid}` | HTML de ~180 KB. Devuelve 200 con HTML de login si la sesión caducó, hay que comprobarlo. |

### 3.1 Tablas y su índice

El folio lleva 11 tablas. El índice importa porque no hay ids estables en el
HTML, solo posición:

| # | Contenido |
|---|---|
| 0 | Formulario de datos del huésped |
| 1 | **Cargos** (servicios consumidos) |
| 2 | **Pagos** |
| 3 | Facturación (ucraniano) |
| 4 | Tarjetas del huésped |
| 5 | Vehículo |
| 6 | Notas |
| 7 | Room charges (precio por noche) |
| 8 | Comentarios |
| 9 | Registro de actividad |
| 10 | Resumen de servicios (`Услуга` / `Сумма` / `К оплате`) |

> La tabla 10 **no se usa**: sus filas salen idénticas y repetidas
> (`Обед 180.00` ×3) y no cuadran con el total del folio (52.96 en la reserva
> 23354). Es una fila de plantilla de JS, no un dato. No(parsearla) evita
> meter cargos fantasma en la BD.

### 3.2 Columnas reales: cargos (tabla 1)

Leídas de la reserva **23354**, que tiene más de una línea:

```
[0] Fecha y hora de prestación de servicios   '2026-08-10 03:31:00'
[1] №                                          '7736'
[2] Título                                     'Servicio'
[3] Entidad legal                              'Hotel Ensueños by HHG'
[4] Descripción                                'IVA(15%)'
[5] Número                                     '1'
[6] Precio                                     '6.91'
[7] Cantidad                                   '6.91'
```

Notas:

- `№` es el número de línea de cargo y sirve como clave primaria (`Service.id`).
- **`Cantidad` no es un número de unidades, es el importe total de la línea.**
  Con `Número=1`, `Precio=6.91` y `Cantidad=6.91`. El nombre de la columna
  engaña: las unidades están en `Número`, que es donde hay que leer la cantidad.
- La fila de total del pie (`['', 'Total:', '52.96', '']`) hay que descartarla.
- La fecha viene vacía en las líneas de tipo `Alojamiento` (el alojamiento se
  imputa a las fechas de la reserva, no a una línea con hora propia).

### 3.3 Columnas reales: pagos (tabla 2)

De la reserva **23356**:

```
[0] Fecha de pago            '2026-09-27'
[1] Fecha de creación        '2026-09-27 10:40:45'
[2] №                        '17954'
[3] Entidad legal            'Hotel Ensueños by HHG'
[4] Descripción              ''
[5] Tipo                     'Pago'
[6] Cantidad                 '324.00'      <-- el importe
[7] Método de pago           'Efectivo'    <-- el método
[8] vPOS Número de la tarjeta '---'
[9] vPOS Estado              'Terminar el pago'
[10] Сheque fiscal           'No fiscal'
```

El `Cantidad` de un pago **sí es el importe**. La cabecera de la tabla declara
21 columnas pero las filas de datos traen 13 celdas: los índices 11–17 están
vacíos y el 18–19 son el `Total:` del pie, así que **el índice de celda solo
es válido hasta la columna 10**.

### 3.4 El fallo que este documento justifica

El `parse_folio` anterior quitaba las celdas vacías (`non_empty`) y luego
accedía por posición. Con `Descripción` y `Fecha` vacías el resultado salía
bien por casualidad; en cuanto una de las dos dos se rellena, **todo el
registro se desplaza**:

| Campo | Valor real | Lo que devolvía |
|---|---|---|
| `id` | `7736` | `'2026-08-10 03:31:00'` |
| `name` | `Servicio` | `'7736'` |
| `legal_entity` | `Hotel Ensueños by HHG` | `'Servicio'` |
| `quantity` | `1` | `'Hotel Ensueños by HHG'` |
| `price` | `6.91` | `'IVA(15%)'` |
| `amount` | `6.91` | `'1'` |

En pagos era peor: `amount` leía `'Efectivo'` y `_parse_decimal` devolvía
`None`, así que los pagos no se guardaban nunca.

**Regla: mapear por nombre de cabecera, nunca por posición.** Se resuelve la
cabecera a índices una vez y se lee cada celda por su columna. Así las
columnas vacías dejan de mover el resto.

Evidencia: `tests/manual/test_folio_cargos_multiples.py` y
`tests/manual/test_folio_pagos_concreto.py` (ambos guardan el HTML crudo
junto al script).

---

## 4. Menú completo del portal

Extraído de `/reservation_c2/status` ("Escritorio"), que es el único sitio
donde vive el menú completo. **Estas son todas las rutas de la aplicación**;
si algo no está aquí, no existe como página (salvo que sea un `POST` a un
formulario):

| Enlace del menú | Ruta |
|---|---|
| Tabla de reservas / HMS v1.0 | `/reservations/calendar/` |
| HMS v2.0 | `/reservation_c2/calendar` |
| ∑ Precios y disponibilidad | `/reservation_c2/price_calendar` |
| Restricciones | `/reservation_c2/restrict_calendar` |
| Estado | `/reservation_c2/status` |
| Informes (lista de reservas) | `/reservation_c2/rlist/{página}` |
| Crear reserva grupal | `/reservation_c2/group_reservation` |
| Lista de comentarios | `/reviews_c2/reviews_list` |
| Recomendaciones | `/recommendations/recommendations_list` |
| Buzón | `/mailbox_c2/messageslist/1/1` |
| Configuración | `/admin_settings_c2/global_settings` |
| Ayuda | `https://wiki.otelms.com/` |

Evidencia: `tests/manual/test_inhouse_discover.py`.

### 4.1 No existe endpoint de in-house

**No hay vista de in-house en OtelMS.** El menú está completo arriba y no la
tiene. Se implementa derivado en `GET /reservations/in-house`.

Lo importante es **no filtrar por `Estado`**. La lista de reservas
(`/reservation_c2/rlist/{n}`) trae la columna `Estado` con valores `Reservación`,
`Check in` y `Check out`, y parece la fuente obvious del in-house, pero no lo es.
Barrido completo del 2026-10-05 (270 reservas en 9 páginas de 50):

| Estado | Reservas |
|---|---|
| Reservación | 243 |
| Check in | 22 |
| Check out | 5 |

**Las 22 "Check in" tienen la salida ya pasada** — van del 2026-08-08 al
2026-10-03 — y ninguna pernocta ese día. Filtrar por estado daría 22 huéspedes
que ya se fueron; el hotel estaba vacío. El estado en OtelMS es lo último que
se actualiza y el que menos vale.

El criterio correcto es el rango de fechas, `check_in <= fecha < check_out`, que
es lo que ya hace `RoomRepository.get_occupied_for_date`.

### 4.2 `/reservation_c2/rlist/{n}` — la lista de reservas

La tabla más completa del portal: **52 filas, 23 columnas con cabecera
nombrada**. Se lee por nombre de columna, nunca por posición.

`#` · `Reserva` · `Номер/tov. Категорія` · `Тип номера` · `Номер` · `Гість` ·
`Користувач` · `Кількість гостей` · `Додаткове ліжко` · `Місце для дитини` ·
`Джерело` · `Тариф` · `Статус` · `Приїзд` · `Проживання` · `Від'їзд` · `Сума` ·
`Знижка` · `Оплачено` · `Залишок` · `Дата` · `Телефон` · `E-mail`

En el despliegue español salen traducidas (`Reserva`, `Habitación`, `Huésped`,
`Estado`, `Entrada`, `Estancia`, `Salida`, `Importe`, `Descuento`, `Pagado`,
`Saldo`), pero el encabezado es ukraniano en el HTML original.

- El `{n}` es **paginación**, no un filtro: 50 filas por página. `rlist/0` y un
  valor no numérico devuelven **500**.
- Trae `Номер/Категория` (número + categoría en una celda) y `Тип номера`
  (categoría), campos que el calendario no da.
- Trae `Pagado` y `Saldo` separados; el calendario solo da el saldo.

### 4.3 `/reservation_c2/restrict_calendar` y `/price_calendar`

Dos rejillas más de 46 días, y **la primera fila de `restrict_calendar` es
exactamente la disponibilidad del calendario** (`8, 10, 10, 10, 0, 0, 0, 10,
10, 10, 0, 10, …`). Confirma por una segunda vía el `div.calendar_sum` de §2.1.
`price_calendar` lleva las mismas cifras debajo de los precios por categoría.

`restrict_calendar` es además la vista desde la que se cierran y abren fechas.
Consta de tres formularios:

| Form | method | action | Campos |
|---|---|---|---|
| búsqueda | GET | `/reservation_c2/search` | `search` |
| filtro/rejilla | POST | `/reservation_c2/restrict_calendar` | `bool`, `date_shift`, `month_shift`, `today`, `restrict_rates[]`, `categories[]` |
| cerrar/abrir | POST | `/reservation_c2/save_restrict_close_open` | `restrict_type`, `date` |

`categories[]` son las 9 categorías (13 Matrimonial … 21 Overbooking) y
`restrict_rates[]` las dos tarifas (1 Standard, 2 Feriados).

### 4.4 Cerrar y abrir fechas: el POST real son dos, y sólo uno funciona

Sonó como un endpoint y son dos distintos. La evidencia está en
`tests/manual/test_restrict_select_and_modal.py`, que reproduce la selección de
la UI por HTTP, y en `test_restrict_full_flow.py`, que la ejecuta entera.

**El que funciona: `ajax_calendar_restricts` → `save_restricts`.** Son dos
llamadas encadenadas:

1. **`POST /reservation_c2/ajax_calendar_restricts`**, con la selección que
   hace el arrastre de la UI. El campo se llama `resstrict_data` (con tres
   "s", del portal) y va indexado:

   ```
   resstrict_data[0][rate_id]=1
   resstrict_data[0][date]=20776          ← el day_id numérico, NO la fecha ISO
   resstrict_data[0][fulldate]=2026-11-19 ← aquí sí la fecha ISO
   resstrict_data[0][category_id]=21
   ```

   El servidor guarda la selección y devuelve un modal de 5 KB con el form
   `#dialogForm`: `category_id`, `rate_id`, `datein`, `dateout`, `closed`
   (0 Abierto / 1 Cerrado / 2 No cambiar), `closedonarrival`, `closedondeparture`,
   `minstaythrought`, `minstayarrival`, `maxstay` y siete `week[0..6]`.

2. **`POST /reservation_c2/save_restricts`**, con ese form serializado
   (es lo que hace `$('#modal-dialog2 form').serialize()`). Responde JSON:

   ```json
   {"ok":1,"intdatein":20776,"intdateout":20776,"category_id":"21","rate_id":"1",
    "restricts_data":{"21":{"1":{"20776":{"closed":"1", "day":"18"}}}},
    "count_restricts_data":1,"days":{"20776":"18"}}
   ```

**El paso 1 no se puede saltar.** Un POST directo a `save_restricts` responde
`{"ok":1, ..., "count_restricts_data":0}` y **no cambia nada**: el portal acepta
la llamada, dice que fue bien y deja la celda igual. Reproducido en
`test_restrict_save_roundtrip.py` (cambió: False) frente a
`test_restrict_full_flow.py` (cambió: True). `count_restricts_data` es el número
de días realmente afectados y es el único sitio donde se ve si la operación
sirvió; `ok:1` solo no significa nada.

**Estado de una celda.** Se lee de las clases del `<td>`, porque el portal no lo
serializa en ningún atributo: abierta es `calendar_td ui-selectee` con su
`<div class="current_data3">` y el número de día; cerrada pierde ese div y gana
`bg_padlock` + `calendar_price_change`. El modal además devuelve `closed` con la
opción vigente marcada, que sirve para consultar sin cerrar nada.

**Verificado en vivo.** Round-trip de una celda (categoría 21 Overbooking,
tarifa 1, 2026-11-19 — el último día de la rejilla y el más lejos de cualquier
estancia): cerrada → `bg_padlock` y `count_restricts_data:1`; abierta →
celda idéntica a la de partida. Quedó como estaba.

**El que no se ha ejercido: `save_restrict_close_open`.** El JS de la misma
página pone `restrict_type = 1` en `close_save()` y `restrict_type = 2` en
`open_save()`, o sea 1 = Cerrar y 2 = Abrir. Pero su form **no lleva
categorías** — sólo `restrict_type` y el rango `date` del daterangepicker—, así
que qué celdas tocaría no está determinado por el propio request. No se ha
llamado contra el portal por eso: no es reversible con la certeza que hace
falta. El código anterior lo usaba con los valores **invertidos** (0 = cerrar,
1 = abrir), o sea que habría cerrado las fechas que se le pidieran abrir.

### 4.5 La lectura: `GET /restrictions` no persiste nada

`src/otelms/api/routes/restrictions.py` expone la rejilla como endpoint HTTP
pero **no guarda nada en la base de datos** (a diferencia de la disponibilidad,
que sí va a `category_availability`). Se decidió así a propósito, no por
comodidad:

- Las restricciones son pocas y muy móviles. Recepción abre un día y el
  cambio se ve al momento; una tabla devolvería una foto justo de lo que más
  importa ver al día.
- La rejilla son 46 días. Una fila por celda cerrada son decenas, no miles, y
  aun así se quedarían obsoletas entre syncs.

La consecuencia práctica es que **esta ruta pega contra OtelMS en cada
llamada**: es más lenta que el resto del API y cuenta como scraping. Por eso
la respuesta trae `"source": "otelms/restrict_calendar"` siempre fijo, para
que el cliente distinga una lectura en vivo de un dato cacheado. Sólo se
devuelven las celdas **cerradas**: la ausencia de un par `{category_id, date}`
significa "abierta", no "sin datos". El orden de `items` lo impone la ruta
(fecha, categoría) y no el HTML de la rejilla.

Lo que **no** se ha resuelto: la escritura (cerrar/abrir) no está expuesta por
HTTP. `close_dates()` / `open_dates()` de `scraping/restrictions.py` funcionan y
están probadas contra el portal, pero exponerlas significa escribir contra un
portal de terceros sin `dry-run` ni undo, así que queda para cuando haya una
decisión explícita sobre quién puede cerrar un día y con qué auditoría.

### 4.6 Check-in, check-out y mover una reserva

Descubierto en el folio, que es donde vive el botón. Cada reserva tiene dos
enlaces con `reservation_id` y su respective URL:

```html
<a id="do_checkin"  href="/master_c2/step_1/23565/?landing_page=folio">
<a id="do_checkout" href="/master_c2/checkout_step_1/23565?landing_page=folio">
```

Esos dos **no hacen nada**: abren un asistente de varios pasos.

| Asistente | Pasos | El último hace |
|---|---|---|
| Check-in | `step_1` detalles · `step_2` huéspedes · `step_3` servicios y pagos · `step_4` | el check-in |
| Check-out | `checkout_step_1` fechas · `checkout_step_2` factura preliminar · `checkout_step_3` | el check-out |

**Las tres operaciones reales, leídas del `panel-footer` del último paso:**

| Operación | Método | URL |
|---|---|---|
| Check-in | `GET` | `/reservation_c2/set_checkin/{resid}/status` |
| Check-out | `GET` | `/reservation_c2/set_checkout/{resid}/status` |
| Mover / cambiar fechas | `POST` | `/reservation_c2/update_reservation` |

Ojo con las dos primeras: son **un enlace `<a href>` verde**, no un form. Sin
token, sin POST, sin confirmación. El `/status` final es un segmento literal
de la ruta, no un parámetro. Es decir: **`GET` a esas URLs cambia el estado de
una estancia real.** Que no se confunda con que sean inofensivas por ser GET.

La tercera es distinta. `/master_c2/step_1` postea a `update_reservation` con
26-30 campos: `reservation_id`, `room_id`, `category`, `datein`, `dateout`,
`duration`, `adults`, `checkintime`, `checkouttime`, `price_type`,
`percent_discount`, `service_main_amount` y **un `day_price[day_id]` por
noche**. La pestaña del check-out se titula "Cambiar las fechas de la
estancia", o sea que ese form *es* la operación de mover.

`landing_page` vale `master_checkin` o `master_checkout` y decide a qué
asistente vuelve el portal. No es decorativo.

Dos trampas medidas, no supuestas:

1. **El form del check-out de una reserva que no ha llegado trae
   `duration` negativo.** Para 23565 (llegada 2026-10-09, consultada el
   2026-10-05) el portal devuelve `dateout` = hoy y `duration` = `-4`.
   Reenviar ese form tal cual guardaría una estancia de -4 noches.
2. **El `room_id` sale dos veces**: un `hidden` con la habitación actual y un
   `select`. El `select` sólo trae la actual; la lista real se repuebla por
   JS al cambiar `category`. Los dos campos tienen que coincidir.

Por eso `move_reservation()` **relee el form del portal y sólo cambia el campo
pedido** en vez de construir el payload: los precios por noche los pone el
portal, no esta API. Un `day_price` inventado es un cobro inventado.

### 4.7 Las clases del folio NO dicen si el huésped ha llegado

En el folio (`/reservation_c2/folio/{resid}`) los dos botones traen una clase
extra: `withtoggle` o `withtoggle d0`.

`d0` parece un marcador de "deshabilitado", y la hipótesis era que
serviría para saber el estado de arrivals sin ejecutar un check-out. **Es
falsa**, y hay contraejemplo limpio:

| resid | realidad | check-in | check-out |
|---|---|---|---|
| 23356 | dentro desde 2026-09-20 | `withtoggle` | `withtoggle d0` |
| 23565 | llega 2026-10-09, nunca ha llegado | `withtoggle` | `withtoggle d0` |
| 23552 | — | `withtoggle d0` | `withtoggle` |
| 23558 | — | `withtoggle d0` | `withtoggle` |

23356 y 23565 tienen **HTML idéntico** y estados opuestos. Lo que estas clases
miden es otra cosa (por lo visto, si la fecha de salida está cerca), pero no
es el arrival. No se construya un detector de check-in encima de esto: el
criterio que sí se sostiene es el rango de fechas, como en §4.1.

---

## 5. Endpoints NO verificados

Ninguno de estos se ha visto funcionar. No escribas código contra ellos sin
un `tests/manual/test_<nombre>.py` que lo compruebe antes:

- `/reservation_c2/set_checkin/{resid}/status` y
  `/reservation_c2/set_checkout/{resid}/status`: las URLs están **leídas del
  HTML** y el cliente de `src/otelms/scraping/checkin.py` está probado con
  `MockTransport`, pero **no se han llamado contra el portal**. Un check-in
  mueve una estancia con huéspedes dentro y un check-out cierra una factura.
- `/reservation_c2/update_reservation`: mismo caso. El form se ha leído y
  parseado en vivo contra 23565 y 23356, pero no se ha enviado ninguno.
- `/reservation_c2/save_restrict_close_open`: el form y el JS existen y se han
  leído (§4.4), pero no se ha llamado contra el portal.
- Cualquier cosa de reservations_v2 / booking engine.

Reproducir: `tests/manual/test_checkin_wizard.py`,
`test_checkin_final_steps.py`, `test_move_update_reservation.py`,
`test_checkin_state_detect.py`. Los cuatro son **sólo GET**.