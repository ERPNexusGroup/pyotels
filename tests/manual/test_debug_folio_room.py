"""Debug extract_room_number/room_type from folio."""
import re
import requests
import urllib3
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
print(f"Folio size: {len(html)} bytes")

rt = extract_room_type(html)
rn = extract_room_number(html)
print(f"room_type: {rt}")
print(f"room_number: {rn}")

# Search patterns
hab = re.findall(r"Habitaci[oó]n[^<]{0,30}", html)[:3]
print(f"Habitacion refs: {hab}")

for num in ["201", "103", "209"]:
    count = html.count(num)
    print(f"Room {num}: {count} refs")

# JS room_type patterns
js_room = re.findall(r'room_type["\s:=]{0,20}([\w\s]+)', html)[:3]
print(f"JS room_type patterns: {js_room}")

# Look for room number in JS template
js_room_num = re.findall(r'room_number["\s:=]{0,20}([\d]+)', html)[:3]
print(f"JS room_number patterns: {js_room_num}")

# Check data-title (escaped JS)
dt = re.findall(r'data-title=\\\\"([^\\\\"]+)', html)
print(f"data-title refs: {len(dt)}")

# Try finding room info in calendar item JS
cal_items = re.findall(r'calendar_item[^}]{0,200}', html)
print(f"calendar_item refs: {len(cal_items)}")