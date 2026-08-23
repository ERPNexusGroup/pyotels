"""Test: extrae servicios/pagos del folio real usando folio_extract.parse_folio."""
import requests
import urllib3
from otelms.config.settings import get_settings
from otelms.scraping.folio_extract import parse_folio
import json

urllib3.disable_warnings()
s = get_settings()

session = requests.Session()
session.headers.update({"User-Agent": s.browser_user_agent, "Content-Type": "application/x-www-form-urlencoded"})
session.verify = False
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
session.post("https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel":"18330","login":s.otelms_default_username,"password":s.otelms_default_password,"action":"login"},
    headers={"Referer":"https://desktop.otelms.com/login_c2/single_login?hmsid=18330"}, timeout=15)

# Folio de la primera reserva
fol = session.get("https://desktop.otelms.com/reservation_c2/folio/23229", timeout=30)
print(f"Folio: {fol.status_code}, {len(fol.text)} bytes")

result = parse_folio(fol.text, "23229")
print(json.dumps(result, indent=2, ensure_ascii=False, default=str))