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

Origen: `scraping/auth.py` (no tocar). Verificado en cada script de
`tests/manual/`.

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

Son la vía natural para cerrar y abrir fechas (Fase 2, Tarea 2.1).

---

## 5. Endpoints NO verificados

Ninguno de estos se ha visto funcionar. No escribas código contra ellos sin
un `tests/manual/test_<nombre>.py` que lo compruebe antes:

- Cierre y apertura de fechas: existen las vistas (`restrict_calendar`) pero no
  se ha localizado el `POST` que las ejecuta.
- Cualquier cosa de reservations_v2 / booking engine.