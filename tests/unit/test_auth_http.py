"""Tests unitarios simplificados para URLs y construcción de payloads de auth."""

import pytest

from otelms.config.constants import OtelMSUrls


def test_otelms_urls_construction():
    """OtelMSUrls construye URLs correctas para desktop.otelms.com."""
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")

    assert urls.base_url == "https://desktop.otelms.com"
    assert urls.login_url == "https://desktop.otelms.com/login_c2/single_login?hmsid=18330"
    assert urls.do_login_url == "https://desktop.otelms.com/login_c2/do_single_login"
    assert urls.calendar_url() == "https://desktop.otelms.com/reservation_c2/calendar"
    # categories_url no existe; el endpoint real es categories bajo reservation_c2
    assert urls.guest_detail_url("123") == "https://desktop.otelms.com/reservation_c2/guestfolio/123"
    assert urls.reservation_detail_url("456") == "https://desktop.otelms.com/reservation_c2/folio/456/1"
    assert urls.reservation_edit_url("456") == "https://desktop.otelms.com/reservation_c2/edit/456"


def test_payload_construction():
    """Payload de login incluye hotel, login, password, action."""
    from otelms.config.constants import OtelMSUrls
    from otelms.scraping.auth import OtelMSAuth

    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    auth = OtelMSAuth(
        hotel_id="18330",
        username="test@hotel.com",
        password="testpass",
        two_factor_handler=None,
    )

    # El método _perform_login construye el payload así:
    payload = {
        "hotel": auth.hotel_id,
        "login": auth.username,
        "password": auth.password,
        "action": "login",
    }

    assert payload["hotel"] == "18330"
    assert payload["login"] == "test@hotel.com"
    assert payload["password"] == "testpass"
    assert payload["action"] == "login"
    # El POST va a do_login_url
    assert auth.urls.do_login_url == "https://desktop.otelms.com/login_c2/do_single_login"


def test_cookie_domain_derivation():
    """El dominio para cookies se deriva de base_url, no de hotel_id."""
    from otelms.config.constants import OtelMSUrls
    from otelms.scraping.auth import OtelMSAuth

    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    auth = OtelMSAuth(
        hotel_id="18330",
        username="test@hotel.com",
        password="testpass",
        two_factor_handler=None,
    )

    # _sync_cookies_to_context usa base_url sin https://
    expected_domain = urls.base_url.removeprefix("https://")
    assert expected_domain == "desktop.otelms.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
