"""Test: Scrape.do POST vía API directa con body como data param."""
import requests
import urllib3
import json
from urllib.parse import quote, urlencode

urllib3.disable_warnings()

api_key = "d7216f23e25d4673b36ba79aa37f20af035b33dcdca"

# Scrape.do API: POST con el target como query param, body como data
target = "https://desktop.otelms.com/login_c2/do_single_login"
wrapped_url = f"https://scrape.do?api_key={api_key}&url={quote(target, safe='')}"

# POST con el body del login como data (Scrape.do reenvía el body)
resp = requests.post(
    wrapped_url,
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    },
    timeout=30,
    verify=False,
)
print(f"POST status: {resp.status_code}")
print(f"Final URL: {resp.url}")
print(f"Body[:200]: {resp.text[:200]}")

# Si login OK, GET calendar
if resp.status_code == 200:
    cal_target = "https://desktop.otelms.com/reservation_c2/calendar"
    cal_wrapped = f"https://scrape.do?api_key={api_key}&url={quote(cal_target, safe='')}"
    cal = requests.get(cal_wrapped, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, verify=False)
    print(f"Calendar: {len(cal.text)} bytes, redirect: {'login' in str(cal.url).lower()}")
    if len(cal.text) > 66:
        print("CONTIENE CALENDARIO")
    else:
        print(f"Calendar HTML: {cal.text[:100]}")