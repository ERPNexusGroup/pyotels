"""Explorar la página restrict_calendar (close/open dates UI)."""
import requests
import urllib3
import re
import json
from pathlib import Path

from bs4 import BeautifulSoup
from otelms.config.settings import get_settings

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"

# Login con requests (sin proxy)
http_client = requests.Session()
http_client.headers.update({"User-Agent": s.browser_user_agent})
http_client.verify = False

resp = http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
print(f"Login page: {resp.status_code}")

resp = http_client.post(
    f"{base}/login_c2/do_single_login",
    data={"hotel": "18330", "login": s.otelms_default_username, "password": s.otelms_default_password, "action": "login"},
    headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"},
)
print(f"Login POST: {resp.status_code}")

# Navigate to restrict_calendar
resp = http_client.get(f"{base}/reservation_c2/restrict_calendar", timeout=30)
print(f"restrict_calendar: {resp.status_code}, {len(resp.text)} bytes")

html = resp.text
soup = BeautifulSoup(html, "html.parser")

# Find forms
forms = soup.find_all("form")
print(f"\nForms: {len(forms)}")
for i, form in enumerate(forms):
    print(f"  Form {i}: method={form.get('method')}, action={form.get('action')}")
    inputs = form.find_all("input")
    for inp in inputs[:10]:
        print(f"    input: name={inp.get('name')}, type={inp.get('type')}, value={inp.get('value', '')[:30]}")
    selects = form.find_all("select")
    for sel in selects[:3]:
        print(f"    select: name={sel.get('name')}, options={len(sel.find_all('option'))}")

# Find AJAX calls
ajax_urls = re.findall(r"url:\s*['\"]([^'\"]+)", html)
print(f"\nAJAX URLs: {list(set(ajax_urls))}")

# Find room selectors
room_selects = soup.find_all("select", attrs={"name": re.compile(r"room", re.I)})
print(f"\nRoom selects: {len(room_selects)}")
for sel in room_selects:
    print(f"  name={sel.get('name')}, options: {[o.get_text()[:20] for o in sel.find_all('option')[:5]]}")

# Find date inputs for booking period
date_inputs = soup.find_all("input", attrs={"name": re.compile(r"date|start|end|check", re.I)})
print(f"\nDate inputs: {len(date_inputs)}")
for di in date_inputs:
    print(f"  name={di.get('name')}, type={di.get('type')}, placeholder={di.get('placeholder', '')}")

# Find close/open buttons
buttons = soup.find_all("button")
print(f"\nButtons: {len(buttons)}")
for btn in buttons:
    print(f"  '{btn.get_text(strip=True)[:30]}' onclick={btn.get('onclick', '')[:60]}")

# Find checkboxes for room selection
checkboxes = soup.find_all("input", type="checkbox")
print(f"\nCheckboxes: {len(checkboxes)}")
room_checkboxes = [cb for cb in checkboxes if "room" in (cb.get("name", "").lower() + cb.get("value", "").lower())]
print(f"Room checkboxes: {len(room_checkboxes)}")

# Find the booking period / date range inputs
period_inputs = re.findall(r'<input[^>]*name="([^"]*(?:date|period|booking|from|to|start|end)[^"]*)"[^>]*>', html, re.I)
print(f"\nPeriod inputs: {period_inputs[:5]}")

# Save HTML
Path(__file__).parent.joinpath("restrict_calendar.html").write_text(html, encoding="utf-8")
print(f"\n✅ Saved restrict_calendar.html")