"""Sync completo con Playwright: extrae rooms desde HTML renderizado.

Root cause: folio HTTP requests no muestra room numbers (están en JS templates).
Solution: Use Camoufox (Playwright) para login + extraer folio renderizado.
"""
import asyncio
import re
import json
from pathlib import Path

from camoufox import AsyncCamoufox
from otelms.config.settings import get_settings
from otelms.scraping.room_extract import extract_room_number, extract_room_type
import httpx
import urllib3

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"


async def sync_rooms_with_playwright():
    # Login HTTP (sin proxy - funciona)
    http_client = httpx.AsyncClient(base_url=base, verify=False, timeout=30, follow_redirects=True)
    http_client.headers.update({"User-Agent": s.browser_user_agent})
    await http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
    resp = await http_client.post(
        f"{base}/login_c2/do_single_login",
        data={"hotel": "18330", "login": s.otelms_default_username,
              "password": s.otelms_default_password, "action": "login"},
        headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"},
    )
    cookies = [{"name": c.name, "value": c.value, "domain": ".otelms.com", "path": "/"} for c in http_client.cookies.jar]
    await http_client.aclose()

    # Get reservations from calendar to have list of resid
    http_client2 = httpx.AsyncClient(base_url=base, verify=False, timeout=30, follow_redirects=True)
    http_client2.headers.update({"User-Agent": s.browser_user_agent})
    http_client2.cookies = httpx.AsyncClient().cookies
    # Re-add cookies
    for c in cookies:
        http_client2.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])

    cal_resp = await http_client2.get(f"{base}/reservation_c2/calendar", timeout=30)
    await http_client2.aclose()

    # Extract reservation IDs from calendar
    resid_list = re.findall(r'resid="(\d+)"', cal_resp.text)
    print(f"Reservations in calendar: {len(resid_list)}")

    # Use Playwright to get rendered folio with room info
    async with AsyncCamoufox(headless=True) as browser:
        ctx = await browser.new_context(user_agent=s.browser_user_agent, viewport={"width": 1920, "height": 1080})
        await ctx.add_cookies(cookies)

        rooms_data = []
        for resid in resid_list[:10]:  # Test with first 10
            page = await ctx.new_page()
            await page.goto(f"{base}/reservation_c2/folio/{resid}", wait_until="networkidle")
            await page.wait_for_timeout(3000)

            html = await page.content()

            room_type = extract_room_type(html)
            room_number = extract_room_number(html)

            if room_number:
                print(f"  Reserva {resid}: Room #{room_number}, Type={room_type}")
                rooms_data.append({"resid": resid, "room_number": room_number, "room_type": room_type})
            else:
                print(f"  Reserva {resid}: No room_number found (type={room_type})")

            await page.close()

        # Save results
        Path(__file__).parent.joinpath("sync_rooms_results.json").write_text(
            json.dumps(rooms_data, indent=2)
        )
        print(f"\nSaved {len(rooms_data)} room extractions to sync_rooms_results.json")

        await ctx.close()


asyncio.run(sync_rooms_with_playwright())