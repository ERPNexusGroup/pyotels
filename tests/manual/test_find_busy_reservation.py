"""Extrae reservas del calendario y prueba guestfolio de cada una."""
import requests
import urllib3
import json
import re
from bs4 import BeautifulSoup
from otelms.config.settings import get_settings

urllib3.disable_warnings()
settings = get_settings()

# Login
session = requests.Session()
session.headers.update({
    "User-Agent": settings.browser_user_agent,
    "Content-Type": "application/x-www-form-urlencoded",
})
session.verify = False
session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
r = session.post("https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel": "18330", "login": settings.otelms_default_username,
          "password": settings.otelms_default_password, "action": "login"},
    headers={"Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
             "Origin": "https://desktop.otelms.com"}, timeout=15)

if "reservation_c2/calendar" not in r.text:
    print("❌ Login fallido")
else:
    print("✅ Login OK")

    # Calendar
    cal = session.get("https://desktop.otelms.com/reservation_c2/calendar", timeout=30)
    print(f"Calendar: {len(cal.text)} bytes")

    # Extraer reservas
    from otelms.scraping.calendar_extract import extract_all_reservations
    reservations = extract_all_reservations(cal.text)
    print(f"Total reservas: {len(reservations)}")

    # Probar 5 reservas
    for res in reservations[:5]:
        res_id = res["resid"]
        url = f"https://desktop.otelms.com/reservation_c2/guestfolio/{res_id}"
        gf = session.get(url, timeout=20)

        soup = BeautifulSoup(gf.text, "html.parser")
        tables = soup.find_all("table")

        charges = 0
        services = 0
        if len(tables) >= 2:
            charges = len(tables[1].find_all("tr")) - 1
        if len(tables) >= 3:
            services = len(tables[2].find_all("tr")) - 1

        print(f"  🧾 {res_id} ({res['guest_name'][:20]}): tables={len(tables)}, charges={charges}, services={services}")

        if charges > 0 or services > 0:
            with open(f"guestfolio_{res_id}.html", "w", encoding="utf-8") as f:
                f.write(gf.text)
            print(f"     → Saved: guestfolio_{res_id}.html")