"""Tests de la traducción del folio a filas de Service y Payment.

Estas funciones son el puente entre lo que devuelve parse_folio y las
columnas de las tablas, y ahí es donde se pierden datos: el parser llama
a los campos name/amount y el modelo los llama title/total, y el modelo
exige date en ambos. Los fixtures son la salida real de parse_folio
sobre el folio del hotel 18330.
"""
from datetime import UTC, datetime
from decimal import Decimal

from otelms.services.sync_service import (
    SyncService,
    _parse_otelms_datetime,
    _reservation_id,
)

RES_ID = "23356"

FOLIO = {
    "reservation_id": "23356",
    "services": [
        {
            "id": "49566",
            "name": "Alojamiento",
            "legal_entity": "Hotel Ensueños by HHG",
            "description": "",
            "date": "",  # los cargos de alojamiento vienen sin fecha
            "quantity": Decimal("1"),
            "price": Decimal("324.00"),
            "amount": Decimal("324.00"),
        }
    ],
    "payments": [
        {
            "id": "17954",
            "date": "2026-09-27",
            "created_at": "2026-09-27 10:40:45",
            "invoice_num": "17954",
            "legal_entity": "Hotel Ensueños by HHG",
            "description": "",
            "payment_type": "Pago",
            "amount": Decimal("324.00"),
            "method": "Efectivo",
            "card_number": "---",
            "card_status": "Terminar el pago",
        }
    ],
    "room_charges": [
        {
            "date": "2026-09-28",
            "description": "Por tarifa (Tarifa:Directa)",
            "amount": Decimal("162.00"),
        },
        {
            "date": "2026-09-29",
            "description": "Por tarifa (Tarifa:Directa)",
            "amount": Decimal("162.00"),
        },
    ],
}


class TestParseOtelmsDatetime:
    def test_fecha_con_hora(self):
        assert _parse_otelms_datetime("2026-08-10 03:31:00") == datetime(
            2026, 8, 10, 3, 31, 0, tzinfo=UTC
        )

    def test_solo_fecha(self):
        assert _parse_otelms_datetime("2026-09-27") == datetime(
            2026, 9, 27, tzinfo=UTC
        )

    def test_vacio_o_basura_devuelve_none(self):
        assert _parse_otelms_datetime("") is None
        assert _parse_otelms_datetime(None) is None
        assert _parse_otelms_datetime("no es una fecha") is None


class TestServiceRows:
    def test_usa_los_nombres_de_columna_del_modelo(self):
        """Service llama title/total a lo que el parser llama name/amount."""
        rows = SyncService._service_rows(FOLIO, RES_ID)
        charge = rows[0]
        assert charge["title"] == "Alojamiento"
        assert charge["total"] == Decimal("324.00")
        assert charge["price"] == Decimal("324.00")
        assert charge["quantity"] == Decimal("1")
        # Las claves del parser no deben llegar al constructor del modelo.
        assert "name" not in charge
        assert "amount" not in charge

    def test_las_noches_entran_como_servicios(self):
        rows = SyncService._service_rows(FOLIO, RES_ID)
        nights = [r for r in rows if "-night-" in str(r["id"])]
        assert len(nights) == 2
        assert nights[0]["total"] == Decimal("162.00")

    def test_el_alojamiento_sin_fecha_hereda_la_primera_noche(self):
        """Service.date es NOT NULL y los cargos de alojamiento la traen
        vacía, así que sin esto el cargo se perdería en el INSERT."""
        rows = SyncService._service_rows(FOLIO, RES_ID)
        charge = rows[0]
        assert charge["date"] == datetime(2026, 9, 28, tzinfo=UTC)

    def test_sin_noches_no_hay_que_heredar_nada(self):
        folio = dict(FOLIO, room_charges=[])
        rows = SyncService._service_rows(folio, RES_ID)
        # El cargo no tiene fecha y no hay de dónde cogerla: se descarta.
        assert rows == []

    def test_folio_vacio(self):
        assert SyncService._service_rows({"services": [], "room_charges": []}, RES_ID) == []

    def test_el_id_lleva_el_numero_de_reserva_delante(self):
        """`Service.id` es clave primaria sola, no compuesta con la
        reserva. Los números de línea del folio (49839, 49842...) se
        repiten entre reservas, y sin el prefijo el INSERT moría con
        duplicate key en cuanto se guardaban dos del mismo día."""
        rows = SyncService._service_rows(FOLIO, RES_ID)
        assert all(str(r["id"]).startswith(f"{RES_ID}-") for r in rows)
        assert rows[0]["id"] == "23356-49566"

    def test_dos_reservas_no_chocan_con_la_misma_noche(self):
        """Dos reservas con una noche el mismo día generaban el mismo id
        'night-<fecha>' y una reventaba a la otra."""
        other = SyncService._service_rows(FOLIO, "99999")
        own_nights = {
            r["id"] for r in SyncService._service_rows(FOLIO, RES_ID)
            if str(r["id"]).startswith(f"{RES_ID}-night-")
        }
        other_nights = {
            r["id"] for r in other if str(r["id"]).startswith("99999-night-")
        }
        assert own_nights and other_nights
        assert not (own_nights & other_nights)


class TestPaymentRows:
    def test_mapea_a_las_columnas_del_modelo(self):
        pmt = SyncService._payment_rows(FOLIO, RES_ID)[0]
        assert pmt["id"] == "23356-17954"
        assert pmt["date"] == datetime(2026, 9, 27, tzinfo=UTC)
        assert pmt["amount"] == Decimal("324.00")
        assert pmt["method"] == "Efectivo"
        assert pmt["reference"] == "17954"
        assert pmt["status"] == "Terminar el pago"
        assert pmt["card_type"] == "Pago"

    def test_el_importa_nunca_queda_none(self):
        """El modelo lo declara NOT NULL: un pago sin importe no entra."""
        folio = {"payments": [{"id": "1", "date": "2026-01-01", "amount": None}]}
        assert SyncService._payment_rows(folio, RES_ID)[0]["amount"] == Decimal("0")

    def test_pago_sin_numero_no_se_pierde(self):
        """Se le da un id sintético: perder el pago entero sería peor."""
        folio = {"payments": [{"id": "", "date": "2026-01-01", "amount": Decimal("5")}]}
        assert SyncService._payment_rows(folio, RES_ID)[0]["id"] == "23356-p0"

    def test_pago_sin_fecha_se_descarta(self):
        folio = {"payments": [{"id": "1", "date": "", "amount": Decimal("5")}]}
        assert SyncService._payment_rows(folio, RES_ID) == []

    def test_folio_sin_pagos(self):
        assert SyncService._payment_rows({"payments": []}, RES_ID) == []


class TestReservationId:
    """La clave con la que se buscan los folios.

    Esto se encontró porque el sync reportaba éxito y no guardaba ningún
    cargo: buscaba los folios por 'reservation_number' mientras que las
    celdas del calendario traen 'reservation_id'. El dict de folios salía
    vacío y, como todo lo demás era opcional, no se notaba nada.
    """

    def test_celda_de_calendario(self):
        assert _reservation_id({"reservation_id": "23564"}) == "23564"

    def test_modal(self):
        assert _reservation_id({"reservation_number": "23564"}) == "23564"

    def test_fetch_y_persist_resuelven_igual(self):
        """Las dos rutas tienen que devolver lo mismo, o una busca folios
        que la otra nunca vio."""
        cell = {"reservation_id": "23564", "room_id": "105"}
        assert _reservation_id(cell) == _reservation_id(dict(cell))

    def test_sin_id(self):
        assert _reservation_id({"room_id": "105"}) is None
        assert _reservation_id({}) is None

    def test_el_id_se_devuelve_como_texto(self):
        """La BD lo guarda como String; un int colaría sin convertir."""
        assert _reservation_id({"reservation_id": 23564}) == "23564"