"""
Unit tests para parse_folio_complete y extracción exhaustiva del folio de reserva.
"""
from decimal import Decimal
from otelms.scraping.folio_deep_extract import parse_folio_complete


SAMPLE_FOLIO_HTML = """
<html>
<body>
<div class="nameofgroup">Reserva № 23641</div>
<div class="balans">Saldo: $0.00</div>

<div class="panel">
    <div class="panel-heading">Información básica</div>
    <table>
        <tr><td>Huésped:</td><td>Juan Pérez</td></tr>
        <tr><td>Teléfono:</td><td>+593991234567</td></tr>
        <tr><td>Correo electrónico:</td><td>juan@example.com</td></tr>
        <tr><td>Fuente:</td><td>Booking.com</td></tr>
    </table>
</div>

<div class="panel">
    <div class="panel-heading">Información de la estancia</div>
    <table>
        <tr><td>Llegada:</td><td>2026-11-10</td></tr>
        <tr><td>Salida:</td><td>2026-11-12</td></tr>
        <tr><td>Noches:</td><td>2</td></tr>
        <tr><td>Habitación:</td><td>101 - Matrimonial</td></tr>
        <tr><td>Tarifa:</td><td>Tarifa Estándar</td></tr>
    </table>
</div>

<div class="panel">
    <div class="panel-heading">Información desde el canal</div>
    <table>
        <tr><td>ID de reserva en OTA:</td><td>OTA-998877</td></tr>
        <tr><td>ID de reserva de habitación:</td><td>ROOM-112233</td></tr>
    </table>
</div>

<!-- Tabla 0: Huéspedes -->
<table>
    <tr><th>Huésped</th><th>Adultos</th><th>Niños</th></tr>
    <tr><td>Juan Pérez</td><td>2</td><td>0</td></tr>
</table>

<!-- Tabla 1: Servicios -->
<table>
    <tr><th>Fecha</th><th>№</th><th>Título</th><th>Entidad legal</th><th>Descripción</th><th>Número</th><th>Precio</th><th>Cantidad</th><th></th><th></th></tr>
    <tr><td>2026-11-10 14:00</td><td>1001</td><td>Lavandería</td><td>Hotel Ensueños</td><td>Lavado express</td><td>1</td><td>10.00</td><td>10.00</td><td></td><td></td></tr>
</table>

<!-- Tabla 2: Pagos -->
<table>
    <tr><th>Fecha de pago</th><th>Fecha creación</th><th>№</th><th>Entidad</th><th>Descripción</th><th>Tipo</th><th>Cantidad</th><th>Método</th></tr>
    <tr><td>2026-11-10 15:00</td><td>2026-11-10</td><td>501</td><td>Hotel</td><td>Pago inicial</td><td>Ingreso</td><td>50.00</td><td>Efectivo</td></tr>
</table>

<!-- Tabla 3: Hueco -->
<table></table>
<!-- Tabla 4: Hueco -->
<table></table>

<!-- Tabla 5: Vehículo -->
<table>
    <tr><th>Marca del automóvil</th><th>Color</th><th>Matrícula</th></tr>
    <tr><td>Toyota Yaris</td><td>Gris</td><td>ABC-1234</td></tr>
</table>

<!-- Tabla 6: Notas -->
<table>
    <tr><th>Fecha</th><th>Autor</th><th>Texto</th></tr>
    <tr><td>2026-11-09 10:00</td><td>Walter Cun</td><td>Huésped solicita late check-out</td></tr>
</table>

<!-- Tabla 7: Tarifas por día -->
<table>
    <tr><th>Fecha</th><th>Tarifa base</th><th>Precio</th></tr>
    <tr><td>2026-11-10</td><td>Tarifa Estándar</td><td>40.00</td></tr>
    <tr><td>2026-11-11</td><td>Tarifa Estándar</td><td>45.00</td></tr>
</table>

<!-- Tabla 8: Hueco -->
<table></table>

<!-- Tabla 9: Auditoría e historial de cambios -->
<table>
    <tr><th>Fecha y hora</th><th>Usuario</th><th>Acción</th><th>Detalles</th></tr>
    <tr><td>2026-11-09 18:00</td><td>Walter Cun</td><td>Modificación</td><td>Cambio de habitación a 101</td></tr>
</table>

</body>
</html>
"""


def test_parse_folio_complete_basic_fields():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert data["reservation_id"] == "23641"
    assert data["status"] == "Reserva"
    assert data["basic"]["client_name"] == "Juan Pérez"
    assert data["basic"]["phone"] == "+593991234567"
    assert data["basic"]["email"] == "juan@example.com"
    assert data["basic"]["source"] == "Booking.com"


def test_parse_folio_complete_stay_and_channel():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert data["stay"]["nights"] == 2
    assert "101" in data["stay"]["room_name"]
    assert data["stay"]["rate"] == "Tarifa Estándar"
    assert data["channel"]["channel_reservation_id"] == "OTA-998877"
    assert data["channel"]["room_reservation_id"] == "ROOM-112233"


def test_parse_folio_complete_vehicle():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert data["vehicle"]["brand"] == "Toyota Yaris"
    assert data["vehicle"]["color"] == "Gris"
    assert data["vehicle"]["plate"] == "ABC-1234"


def test_parse_folio_complete_notes():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert len(data["notes"]) == 1
    assert data["notes"][0]["author"] == "Walter Cun"
    assert "late check-out" in data["notes"][0]["text"]


def test_parse_folio_complete_night_rates():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert len(data["night_rates"]) == 2
    assert data["night_rates"][0]["date"] == "2026-11-10"
    assert data["night_rates"][0]["amount"] == Decimal("40.00")
    assert data["night_rates"][1]["date"] == "2026-11-11"
    assert data["night_rates"][1]["amount"] == Decimal("45.00")


def test_parse_folio_complete_change_history():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert len(data["change_history"]) == 1
    item = data["change_history"][0]
    assert item["user"] == "Walter Cun"
    assert item["action"] == "Modificación"
    assert "101" in item["details"]


def test_parse_folio_complete_services_and_payments():
    data = parse_folio_complete(SAMPLE_FOLIO_HTML, "23641")
    assert len(data["services"]) == 1
    assert data["services"][0]["title"] == "Lavandería"
    assert data["services"][0]["total"] == Decimal("10.00")

    assert len(data["payments"]) == 1
    assert data["payments"][0]["amount"] == Decimal("50.00")
    assert data["payments"][0]["method"] == "Efectivo"
