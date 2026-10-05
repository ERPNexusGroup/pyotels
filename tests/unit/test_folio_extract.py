"""
Unit tests del parser de folio.

El HTML de los fixtures es una copia literal de lo que devuelve
/reservation_c2/folio/{id} en el hotel 18330, no una invention: ver
docs/otelms_endpoints.md §3 y los scripts que lo capturaron
(tests/manual/test_folio_cargos_multiples.py y test_folio_pagos_concreto.py).

El caso que más importa es `test_cargos_con_descripcion_poblada`: el
parser anterior quitaba las celdas vacías antes de leer por posición, así
que con Descripción vacía salía bien por casualidad y con Descripción
rellena devolvía el id en el nombre y la descripción en el precio. Ese
fallo silencioso es el motivo de que estas tablas se lean por cabecera.
"""
from decimal import Decimal

from otelms.scraping.folio_extract import parse_folio


def _page(*tables: str) -> str:
    """Concatena tablas en una página. Los huecos se pasan como cadenas
    vacías: parse_folio busca cargos en la tabla 1, pagos en la 2 y
    precio por noche en la 7, así que la posición importa."""
    return "<html><body>" + "".join(tables) + "</body></html>"


def _empty(n: int = 1) -> str:
    """n tablas vacías, para llegar a la posición que se quiere probar."""
    return "<table></table>" * n


CHARGES_HEADER = (
    "<tr>"
    "<th>Fecha y hora de prestación de servicios</th><th>№</th><th>Título</th>"
    "<th>Entidad legal</th><th>Descripción</th><th>Número</th>"
    "<th>Precio</th><th>Cantidad</th><th></th><th></th>"
    "</tr>"
)

PAYMENTS_HEADER = (
    "<tr>"
    "<th>Fecha de pago</th><th>Fecha de creación</th><th>№</th>"
    "<th>Entidad legal</th><th>Descripción</th><th>Tipo</th><th>Cantidad</th>"
    "<th>Método de pago</th><th>vPOS Número de la tarjeta</th>"
    "<th>vPOS Estado</th><th>Сheque fiscal</th>"
    "</tr>"
)

ROOM_CHARGES_HEADER = (
    "<tr><th>Fecha</th><th>Precio por una noche</th><th>Precio</th></tr>"
)


class TestCharges:
    """Tabla 1: cargos."""

    def _folio(self, rows: str) -> str:
        # Los cargos están en la tabla 1, así que hace falta una antes.
        return _page(_empty(), f"<table>{CHARGES_HEADER}{rows}</table>")

    def test_cargos_con_descripcion_poblada(self):
        """Replica la reserva 23354: aquí el parser antiguo se desplazaba."""
        html = self._folio(
            "<tr><td>2026-08-10 03:31:00</td><td>7736</td><td>Servicio</td>"
            "<td>Hotel Ensueños by HHG</td><td>IVA(15%)</td><td>1</td>"
            "<td>6.91</td><td>6.91</td><td></td><td></td></tr>"
            "<tr><td></td><td>49563</td><td>Alojamiento</td>"
            "<td>Hotel Ensueños by HHG</td><td></td><td>1</td>"
            "<td>46.05</td><td>46.05</td><td></td><td></td></tr>"
            "<tr><td></td><td>Total:</td><td>52.96</td><td></td></tr>"
        )

        services = parse_folio(html, "23354")["services"]

        assert len(services) == 2
        first = services[0]
        assert first["id"] == "7736"
        assert first["name"] == "Servicio"
        assert first["legal_entity"] == "Hotel Ensueños by HHG"
        assert first["description"] == "IVA(15%)"
        assert first["date"] == "2026-08-10 03:31:00"
        assert first["quantity"] == Decimal("1")
        assert first["price"] == Decimal("6.91")
        assert first["amount"] == Decimal("6.91")

    def test_cargos_con_descripcion_vacia(self):
        """Replica la reserva 23564, donde Descripción viene vacía."""
        html = self._folio(
            "<tr><td></td><td>49842</td><td>Alojamiento</td>"
            "<td>Hotel Ensueños by HHG</td><td></td><td>1</td>"
            "<td>70.00</td><td>70.00</td><td></td><td></td></tr>"
            "<tr><td></td><td>Total:</td><td>70.00</td><td></td></tr>"
        )

        services = parse_folio(html, "23564")["services"]

        assert len(services) == 1
        assert services[0]["id"] == "49842"
        assert services[0]["name"] == "Alojamiento"
        assert services[0]["price"] == Decimal("70.00")
        assert services[0]["amount"] == Decimal("70.00")

    def test_la_fila_de_total_no_es_un_cargo(self):
        html = self._folio(
            "<tr><td></td><td>Total:</td><td>70.00</td><td></td></tr>"
        )
        assert parse_folio(html, "1")["services"] == []

    def test_cantidad_es_el_importe_de_la_linea(self):
        """En la tabla de cargos 'Cantidad' es el total, no las unidades.

        Con Número=2 y Precio=10, el total de la línea es 20 aunque la
        columna diga 1. Confundir las dos columnas es lo que hacía que los
        cargos no cuadraran con el total del folio.
        """
        html = self._folio(
            "<tr><td></td><td>900</td><td>Minibar</td><td>Hotel</td>"
            "<td>Bebidas</td><td>2</td><td>10.00</td><td>20.00</td>"
            "<td></td><td></td></tr>"
        )
        svc = parse_folio(html, "1")["services"][0]
        assert svc["quantity"] == Decimal("2")
        assert svc["price"] == Decimal("10.00")
        assert svc["amount"] == Decimal("20.00")


class TestPayments:
    """Tabla 2: pagos."""

    def _folio(self, rows: str) -> str:
        # Los pagos están en la tabla 2.
        return _page(
            _empty(2), f"<table>{PAYMENTS_HEADER}{rows}</table>"
        )

    def test_pago_real(self):
        """Replica la reserva 23356, el primer pago con datos de verdad."""
        html = self._folio(
            "<tr><td>2026-09-27</td><td>2026-09-27 10:40:45</td><td>17954</td>"
            "<td>Hotel Ensueños by HHG</td><td></td><td>Pago</td><td>324.00</td>"
            "<td>Efectivo</td><td>---</td><td>Terminar el pago</td>"
            "<td>No fiscal</td><td></td><td></td></tr>"
            "<tr><td></td><td></td><td></td><td></td><td></td><td>Total:</td>"
            "<td>324.00</td><td></td></tr>"
        )

        payments = parse_folio(html, "23356")["payments"]

        assert len(payments) == 1
        pmt = payments[0]
        assert pmt["id"] == "17954"
        assert pmt["date"] == "2026-09-27"
        assert pmt["created_at"] == "2026-09-27 10:40:45"
        # El bug original leía amount='Efectivo' y lo descartaba por no ser
        # un número, así que no se guardaba ningún pago.
        assert pmt["amount"] == Decimal("324.00")
        assert pmt["method"] == "Efectivo"
        assert pmt["payment_type"] == "Pago"
        assert pmt["card_status"] == "Terminar el pago"

    def test_pago_con_descripcion_poblada(self):
        """Con Descripción rellena el mapeo antiguo también se desplazaba."""
        html = self._folio(
            "<tr><td>2026-06-29</td><td>2026-08-03 21:09:20</td><td>17747</td>"
            "<td>Hotel</td><td>Anticipo reserva</td><td>Pago</td><td>50.00</td>"
            "<td>Transferencia bancaria</td><td>---</td>"
            "<td>Terminar el pago</td><td>No fiscal</td><td></td><td></td></tr>"
        )

        pmt = parse_folio(html, "23299")["payments"][0]

        assert pmt["id"] == "17747"
        assert pmt["description"] == "Anticipo reserva"
        assert pmt["amount"] == Decimal("50.00")
        assert pmt["method"] == "Transferencia bancaria"

    def test_folio_sin_pagos_solo_tiene_el_pie(self):
        html = self._folio(
            "<tr><td></td><td></td><td></td><td></td><td></td><td>Total:</td>"
            "<td>0.00</td><td></td></tr>"
        )
        assert parse_folio(html, "23564")["payments"] == []


class TestRoomCharges:
    """Tabla 7: precio por noche."""

    def test_precio_por_noche(self):
        # El precio por noche está en la tabla 7.
        html = _page(
            _empty(7),
            "<table>"
            "<tr><th>Fecha</th><th>Precio por una noche</th><th>Precio</th></tr>"
            "<tr><td>2026-10-09</td><td>Por tarifa (Tarifa:Directa)</td>"
            "<td>35.00</td></tr>"
            "<tr><td>2026-10-10</td><td>Por tarifa (Tarifa:Directa)</td>"
            "<td>35.00</td></tr>"
            "</table>",
        )

        charges = parse_folio(html, "23564")["room_charges"]

        assert len(charges) == 2
        assert charges[0]["date"] == "2026-10-09"
        assert charges[0]["amount"] == Decimal("35.00")


class TestRobustez:
    """Follos que no encajan con lo esperado."""

    def test_html_vacio_no_revienta(self):
        result = parse_folio("", "1")
        assert result["services"] == []
        assert result["payments"] == []
        assert result["room_charges"] == []

    def test_folio_corto_sin_tablas(self):
        result = parse_folio("<html><body><p>nada</p></body></html>", "1")
        assert result["reservation_id"] == "1"
        assert result["services"] == []

    def test_importe_no_numerico_no_rompe(self):
        html = _page(
            _empty(),
            "<table><tr><th>№</th><th>Título</th><th>Cantidad</th></tr>"
            "<tr><td>1</td><td>Algo</td><td>N/A</td></tr></table>",
        )
        svc = parse_folio(html, "1")["services"][0]
        assert svc["amount"] is None