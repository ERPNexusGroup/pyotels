"""Close/open dates via POST a save_restrict_close_open."""
import re
import requests
import urllib3
from bs4 import BeautifulSoup
from otelms.config.settings import get_settings

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"

# Login
http_client = requests.Session()
http_client.headers.update({"User-Agent": s.browser_user_agent})
http_client.verify = False
http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
http_client.post(
    f"{base}/login_c2/do_single_login",
    data={"hotel": "18330", "login": s.otelms_default_username, "password": s.otelms_default_password, "action": "login"},
    headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"},
)

# Get restrict_calendar
resp = http_client.get(f"{base}/reservation_c2/restrict_calendar", timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

# Extract categories
cat_select = soup.find("select", {"name": "categories[]"})
if cat_select:
    options = cat_select.find_all("option")
    print(f"📋 Categories ({len(options)}):")
    for opt in options:
        val = opt.get("value", "")
        text = opt.get_text(strip=True)
        print(f"  value={val}: {text}")

# Matrimonial category ID
matrimonial_id = None
if cat_select:
    for opt in cat_select.find_all("option"):
        if "Matrimonial" in opt.get_text():
            matrimonial_id = opt.get("value")
            break
print(f"\nMatrimonial category ID: {matrimonial_id}")

# POST close_save
print("\n--- Closing Matrimonial March 1-3 ---")
post_data = {
    "restrict_type": "0",  # close
    "date": "2026-03-01 - 2026-03-03",
    "categories[]": matrimonial_id,
}
resp = http_client.post(f"{base}/reservation_c2/save_restrict_close_open", data=post_data,
    headers={"Referer": f"{base}/reservation_c2/restrict_calendar", "X-Requested-With": "XMLHttpRequest"}, timeout=30)
print(f"close POST: {resp.status_code}")
print(f"Response: {resp.text[:300]}")

# POST open_save
print("\n--- Opening Matrimonial March 1-3 ---")
post_data["restrict_type"] = "1"  # open
resp = http_client.post(f"{base}/reservation_c2/save_restrict_close_open", data=post_data,
    headers={"Referer": f"{base}/reservation_c2/restrict_calendar", "X-Requested-With": "XMLHttpRequest"}, timeout=30)
print(f"open POST: {resp.status_code}")
print(f"Response: {resp.text[:300]}")

# Also test with Playwright for drag-drop
print("\n--- Testing with Playwright (drag-drop) ---")
print("Note: restrict_calendar uses category-based POST, not drag-drop")