"""Tests para la construcción de URLs de OtelMS.

Regresión: el patrón `{hotel_id}.otelms.com` NO existe en DNS.
El portal real vive en `desktop.otelms.com` y el hotel se pasa como
`hmsid` en el login (`/login_c2/single_login?hmsid={id}`).
"""

from otelms.config.constants import OtelMSUrls


def test_base_url_uses_desktop_domain() -> None:
    """El host base SIEMPRE es desktop.otelms.com (no {hotel_id}.otelms.com)."""
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.base_url == "https://desktop.otelms.com"


def test_login_url_includes_hmsid() -> None:
    """Login page: desktop.otelms.com/login_c2/single_login?hmsid={hotel_id}."""
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.login_url == (
        "https://desktop.otelms.com/login_c2/single_login?hmsid=18330"
    )


def test_do_login_url_posts_to_c2_endpoint() -> None:
    """POST de login: /login_c2/do_single_login (el form action real)."""
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.do_login_url == "https://desktop.otelms.com/login_c2/do_single_login"


def test_calendar_url_on_desktop_domain() -> None:
    """Calendar vive en desktop.otelms.com/reservation_c2/calendar."""
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.calendar_url() == (
        "https://desktop.otelms.com/reservation_c2/calendar"
    )


def test_calendar_url_with_date() -> None:
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.calendar_url("2026-08-03") == (
        "https://desktop.otelms.com/reservation_c2/calendar?date=2026-08-03"
    )


def test_reservation_detail_url_on_desktop_domain() -> None:
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.reservation_detail_url("999") == (
        "https://desktop.otelms.com/reservation_c2/folio/999/1"
    )


def test_reservation_edit_url_on_desktop_domain() -> None:
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.reservation_edit_url("999") == (
        "https://desktop.otelms.com/reservation_c2/edit/999"
    )


def test_guest_detail_url_on_desktop_domain() -> None:
    urls = OtelMSUrls(base_domain="otelms.com", hotel_id="18330")
    assert urls.guest_detail_url("777") == (
        "https://desktop.otelms.com/reservation_c2/guestfolio/777"
    )
