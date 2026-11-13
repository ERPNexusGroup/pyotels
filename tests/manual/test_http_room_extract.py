"""Test: extract room_number from calendar tooltips."""
import re
import requests
import urllib3
from html import unescape
from otelms.config.settings import get_settings
from otelms.scraping.room_extract import extract_room_number, extract_room_type

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"

session = requests.Session()
session.headers.update({"User-Agent": s.browser_user_agent})
session.verify = False
session.get(f"{base}/login_c2/single_login?hmsid=18330")
session.post(f"{base}/login_c2/do_single_login",
    data={"hotel": "18330", "login": s.otelms_default_username, "password": s.otelms_default_password, "action": "login"},
    headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"})

resp = session.get(f"{base}/reservation_c2/folio/23419")
html = resp.text
rt = extract_room_type(html)
rn = extract_room_number(html)
print(f"Folio HTML: {len(html)} bytes")
print(f"room_type: {rt}")
print(f"room_number: {rn}")

# Calendar tooltips
cal = session.get(f"{base}/reservation_c2/calendar")
items = re.findall(r'data-title="([^"]{0,300})"', cal.text)
print(f"Calendar tooltips: {len(items)}")
for t in items[:2]:
    decoded = unescape(t)
    rm = re.search(r'(?:Habitaci[oó]n|Room)[:\s]*(\d+)', decoded, re.I)
    rtm = re.search(r'(Matrimonial|king|std|Triple|Suite)', decoded, re.I)
    print(f"  Room: {rm.group(1) if rm else None}, Type: {rtm.group(1) if rtm else None}")
    print(f"  Full: {decoded[:100]}")