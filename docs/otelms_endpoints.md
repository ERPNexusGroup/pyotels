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

## 4. Endpoints NO verificados

Ninguno de estos se ha visto funcionar. No escribas código contra ellos sin
un `tests/manual/test_<nombre>.py` que lo compruebe antes:

- Endpoint de in-house / huéspedes actuales.
- Cierre y apertura de fechas (lo que hay en `scraping/restrictions.py` está
  sin confirmar contra el portal).
- Cualquier cosa de reservations_v2 / booking engine.