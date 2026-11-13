"""
Unit tests para API Gateway por feature flags y cálculo de total_price en SyncService.
"""
from decimal import Decimal

from otelms.services.sync_service import SyncService, _compute_total_price


def test_compute_total_price_prefers_folio_services():
    folio = {
        "services": [
            {"amount": Decimal("40.00")},
            {"amount": Decimal("10.00")},
        ],
        "room_charges": [{"amount": Decimal("999.00")}],
    }
    assert _compute_total_price(folio, night_rates_data=[]) == Decimal("50.00")


def test_compute_total_price_falls_back_to_night_rates_then_room_charges():
    folio = {"services": [], "room_charges": [{"amount": Decimal("30.00")}, {"amount": Decimal("20.00")}]}
    assert _compute_total_price(folio, night_rates_data=[]) == Decimal("50.00")
    folio2 = {"services": [], "room_charges": []}
    night_rates = [{"amount": Decimal("15.00")}, {"amount": Decimal("25.00")}]
    assert _compute_total_price(folio2, night_rates_data=night_rates) == Decimal("40.00")


def test_service_rows_excludes_synthetic_night_rows():
    folio = {
        "services": [
            {"id": "49839", "date": "2026-11-10 14:00:00", "name": "Lavandería", "amount": Decimal("10.00"), "price": Decimal("10.00")},
        ],
        "room_charges": [
            {"date": "2026-11-10", "description": "Tarifa Estándar", "amount": Decimal("40.00")},
            {"date": "2026-11-11", "description": "Tarifa Estándar", "amount": Decimal("45.00")},
        ],
    }
    rows = SyncService._service_rows(folio, "23641")
    assert len(rows) == 1
    assert rows[0]["id"] == "23641-49839"
    assert all("-night-" not in r["id"] for r in rows)


def test_gateway_blocks_disabled_read_endpoint():
    from fastapi.testclient import TestClient
    from otelms.api.main import create_app
    from otelms.config.settings import settings

    old = settings.api_enable_read_public
    settings.api_enable_read_public = False
    try:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/hotels")
        assert resp.status_code == 503
        assert "disabled" in resp.json().get("detail", "").lower()
    finally:
        settings.api_enable_read_public = old


def test_gateway_blocks_disabled_write_endpoint():
    from fastapi.testclient import TestClient
    from otelms.api.main import create_app
    from otelms.config.settings import settings

    old = settings.api_enable_write_actions
    settings.api_enable_write_actions = False
    try:
        app = create_app()
        client = TestClient(app)
        resp = client.post("/guests?hotel_id=18330", json={"first_name": "A", "last_name": "B"})
        assert resp.status_code == 503
    finally:
        settings.api_enable_write_actions = old
