"""Redescubrir URLs de cargos/pagos desde el calendar."""
import requests, urllib3, re
from otelms.config.settings import get_settings
from otelms.scraping.calendar_extract import extract_all_reservations

urllib3.disable_warnings()
s = get_settings()

session = requests.Session()
session.headers.update({"User-Agent": s.browser_user_agent, "Content-Type": "application/x-www-form-urlencoded"})
session.verify = False
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
r = session.post(
    "https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel":"18330","login":s.otelms_default_username,"password":s.otelms_default_password,"action":"login"},
    headers={"Referer":"https://desktop.otelms.com/login_c2/single_login?hmsid=18330"}, timeout=15)

print(f"Login: {'OK' if 'calendar' in r.text else 'FAIL'}")

cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
reservations = extract_all_reservations(cal.text)

# Encontrar todos los href únicos en el calendar
href_matches = re.findall(r'href="(/reservation_c2/[a-z_]+/\d+)"', cal.text)
print(f"Links de calendar: {list(set(href_matches))[:20]}")

res_id = reservations[0]["resid"] if reservations else "23419"
urls_to_test = [
    f"https://desktop.otelms.com/reservation_c2/folio/{res_id}",
    f"https://desktop.otelms.com/reservation_c2/invoice/{res_id}",
    f"https://desktop.otelms.com/reservation_c2/payments/{res_id}",
    f"https://desktop.otelms.com/reservation_c2/charges/{res_id}",
]

for url in urls_to_test:
    r = session.get(url, timeout=15)
    tables = len(re.findall(r"<table", r.text))
    title_match = re.search(r"<title>([^<]+)</title>", r.text)
    status = "✅" if "table" in r.text and len(r.text) > 10000 else "❌"
    print(f"  {status} {url.split('/')[-1]}: {r.status_code}, tables={tables}, size={len(r.text)}, title={title_match.group(1) if title_match else '?'}")