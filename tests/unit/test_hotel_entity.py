import pytest
import pytest_asyncio
from otelms.domain.entities import Hotel


def test_hotel_has_scraper_config_fields():
    hotel = Hotel(
        id="test_hotel",
        name="Test Hotel",
        username="user@test.com",
        password_hash="hash",
        scraper_rate_limit_rpm=60,
        scraper_burst=10,
        scraper_timeout_ms=60000,
        custom_domain="custom.otelms.com",
    )
    assert hotel.scraper_rate_limit_rpm == 60
    assert hotel.scraper_burst == 10
    assert hotel.scraper_timeout_ms == 60000
    assert hotel.custom_domain == "custom.otelms.com"