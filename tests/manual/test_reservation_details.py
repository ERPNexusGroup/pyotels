"""Test: extraer detalles de una reserva específica (guestfolio/pagos/servicios)."""
import requests
import urllib3
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

r1 = session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", timeout=15)
r2 = session.post(
    "https://desktop.otelms.com/login_c2/do_single_login",
    data={"hotel": "18330", "login": settings.otelms_default_username,
          "password": settings.otelms_default_password, "action": "login"},
    headers={"Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330",
             "Origin": "https://desktop.otelms.com"},
    timeout=15,
)
print(f"Login: {r2.status_code}, redirect: {'reservation_c2' in r2.text}")

# Navegar a un guestfolio
res_id = 23229
guestfolio_url = f"https://desktop.otelms.com/reservation_c2/guestfolio/{res_id}"
gf = session.get(guestfolio_url, timeout=30)
print(f"\nGuestfolio {res_id}: {gf.status_code}, {len(gf.text)} bytes")

# Guardar HTML
with open("guestfolio_debug.html", "w", encoding="utf-8") as f:
    f.write(gf.text)

# Extraer secciones
from bs4 import BeautifulSoup
soup = BeautifulSoup(gf.text, "html.parser")

# Titulos de secciones
section_titles = soup.find_all(string=re.compile(r"Datos|Guest|Payment|Service|Pago|Cargo|Total|Reservation|Check"))
for t in section_titles[:10]:
    print(f"  Section hint: {t}")

# Links útiles (payments, services)
import re
payment_links = re.findall(r'href="([^"]*payment[^"]*)"', gf.text, re.I)
service_links = re.findall(r'href="([^"]*service[^"]*)"', gf.text, re.I)
invoice_links = re.findall(r'href="([^"]*invoice[^"]*)"', gf.text, re.I)
folio_links = re.findall(r'href="([^"]*folio[^"]*)"', gf.text, re.I)

print(f"\n🔗 Links:")
print(f"  Payments: {payment_links[:5]}")
print(f"  Services: {service_links[:5]}")
print(f"  Invoices: {invoice_links[:5]}")
print(f"  Folios: {folio_links[:5]}")

# Buscar tabs/paginas
tabs = re.findall(r'id="(tab[^"]*)"', gf.text, re.I)
print(f"\n🔢 Tabs: {tabs[:10]}")

# Buscar datos de huésped
guest_section = soup.find("div", string=re.compile(r"Guest", re.I))
if not guest_section:
    guest_sections = re.findall(r'(Guest[\s\S]{0,300})', gf.text, re.I)
    for g in guest_sections[:1]:
        print(f"  Guest section: {g[:200]}")

# Pagos - buscar tabla
payment_tables = soup.find_all("table")
print(f"\n📊 Tablas: {len(payment_tables)}")
if payment_tables:
    headers = [th.get_text(strip=True) for th in payment_tables[0].find_all("th")]
    print(f"  Table 1 headers: {headers[:10]}")