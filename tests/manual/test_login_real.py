"""Test completo: login OtelMS + calendar via requests (sin proxy, IP local real)."""
import requests
import urllib3
from otelms.config.settings import get_settings
from otelms.utils.crypto import credential_encryption as ce
from otelms.scraping.auth import OtelMSAuth
from otelms.scraping.browser import BrowserPool

urllib3.disable_warnings()

settings = get_settings()
print(f"Hotel: {settings.otelms_default_hotel_id}")
print(f"Username: {settings.otelms_default_username}")
print(f"Password: {settings.otelms_default_password}")

# Test 1: Login directo con requests
session = requests.Session()
session.headers.update({
    "User-Agent": settings.browser_user_agent,
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
})
session.verify = False

r1 = session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
print(f"\n1. GET login page: {r1.status_code}")

resp = session.post(
    "https://desktop.otelms.com/login_c2/do_single_login",
    data={
        "hotel": "18330",
        "login": settings.otelms_default_username,
        "password": settings.otelms_default_password,
        "action": "login",
    },
    headers={
        "Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
        "Origin": "https://desktop.otelms.com",
    },
    timeout=15,
)
print(f"2. POST login: {resp.status_code}")
print(f"   Response: {resp.text[:100]}")

cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
print(f"3. Calendar page: {cal.status_code}")
print(f"   Content length: {len(cal.text)}")
print(f"   Has calendar_table: {'calendar_table' in cal.text}")

if "calendar_table" in cal.text:
    print("\n✅ LOGIN + CALENDARIO EXITOSO — el sync funciona!")
else:
    print("\n❌ Login fallido — redirect a login")