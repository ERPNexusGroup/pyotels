"""Test de login OtelMS via Scrape.do con requests + api_key en query param."""
import requests
from otelms.config.settings import get_settings


settings = get_settings()
api_key = settings.scraper_api_key
proxy_url = f"http://scraper:{api_key}@proxy.scrape.do:9000"

session = requests.Session()
session.proxies = {"http": proxy_url, "https": proxy_url}
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
session.verify = False

# GET login page (api_key como query param)
r1 = session.get(
    "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
    params={"api_key": api_key},
    timeout=30,
)
print(f"Login page: {r1.status_code}")

# POST login (api_key como query param)
resp = session.post(
    "https://desktop.otelms.com/login_c2/do_single_login",
    params={"api_key": api_key},
    data={
        "hotel": "18330",
        "login": "gerencia@harmonyhotelgroup.com",
        "password": "***",
        "action": "login",
    },
    headers={
        "Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
        "Origin": "https://desktop.otelms.com",
        "Content-Type": "application/x-www-form-urlencoded",
    },
    timeout=30,
)
print(f"POST: {resp.status_code}")
print(f"Redirect URL: {resp.url}")
print(f"Body[:200]: {resp.text[:200]}")

# Calendar
cal = session.get(
    "https://desktop.otelms.com/reservation_c2/calendar",
    params={"api_key": api_key},
    timeout=30,
)
print(f"Calendar: {len(cal.text)} bytes, URL: {cal.url}")
print(f"Login redirect: {'login' in str(cal.url).lower()}")
if len(cal.text) > 66:
    print("CONTIENE CALENDARIO")
else:
    print(f"Calendar HTML: {cal.text[:100]}")