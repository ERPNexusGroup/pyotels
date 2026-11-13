"""Extract room_number + room_type from a real folio."""
import re
import json
import requests
import urllib3
from html import unescape
from pathlib import Path

from otelms.config.settings import get_settings
from otelms.scraping.room_extract import extract_room_type

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"

# Login
http_client = requests.Session()
http_client.headers.update({"User-Agent": s.browser_user_agent})
http_client.verify = False
http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
http_client.post(f"{base}/login_c2/do_single_login",
    data={"hotel": "18330", "login": s.otelms_default_username, "password": s.otelms_default_password, "action": "login"},
    headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"})

# Get a folio
resp = http_client.get(f"{base}/reservation_c2/folio/23419", timeout=30)
print(f"Folio response: {resp.status_code}, {len(resp.text)} bytes")

html = resp.text
room_type = extract_room_type(html)
print(f"Room type: {room_type}")

# Search for room number patterns
patterns = [
    r'(?:Habitaci[oó]n|Room)[:\s]*(\d+)\s+(\w+)',
    r'data-title="([^"]*)"',
    r'Habitaci[oó]n[^<]*<[^>]*>(\d+)',
]

for pattern in patterns:
    matches = re.findall(pattern, html)
    if matches:
        print(f"\nPattern: {pattern}")
        print(f"Matches: {matches[:5]}")

# Look for room_number in the full HTML
room_nums = re.findall(r'(201|103|209)', html)
print(f"\nRoom numbers 201/103/209 in folio: {room_nums[:5]}")

# Check calendar tooltip for room info
tooltips = re.findall(r'data-title="([^"]*)"', html)
print(f"\nTooltips: {len(tooltips)}")
for t in tooltips[:2]:
    decoded = unescape(t)
    print(f"  {decoded[:100]}")

# Save folio
Path(__file__).parent.joinpath("folio_debug.html").write_text(html, encoding="utf-8")
print(f"\nSaved folio_debug.html: {len(html)} bytes")