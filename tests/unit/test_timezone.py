"""Tests de conversión de zona horaria (ejecución UTC, visualización Ecuador)."""
from datetime import UTC, datetime

from otelms.api.schemas import HealthResponse
from otelms.utils.timezone import ensure_utc, to_ecuador, to_ecuador_iso, utc_now


def test_utc_now_is_utc():
    now = utc_now()
    assert now.tzinfo == UTC


def test_to_ecuador_converts_utc_and_naive():
    dt_utc = datetime(2026, 11, 14, 18, 30, 0, tzinfo=UTC)
    dt_naive = datetime(2026, 11, 14, 18, 30, 0)

    assert ensure_utc(dt_naive) == dt_utc
    assert to_ecuador(dt_utc).isoformat() == "2026-11-14T13:30:00-05:00"
    assert to_ecuador_iso(dt_naive) == "2026-11-14T13:30:00-05:00"
    assert to_ecuador_iso(None) is None


def test_health_response_serializes_ecuador_time_in_json():
    dt_utc = datetime(2026, 11, 14, 18, 0, 0, tzinfo=UTC)
    resp = HealthResponse(timestamp=dt_utc)
    # En Python conserva UTC
    assert resp.timestamp == dt_utc
    # En JSON se muestra en hora de Ecuador (-05:00)
    assert '"timestamp":"2026-11-14T13:00:00-05:00"' in resp.model_dump_json()
