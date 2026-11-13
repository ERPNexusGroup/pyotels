"""Navegar calendar a marzo 2026 y extraer rooms 201, 103, 209."""
import asyncio
import re
import json
from pathlib import Path

from camoufox import AsyncCamoufox
from otelms.config.settings import get_settings
import httpx
import urllib3

urllib3.disable_warnings()
s = get_settings()
base = "https://desktop.otelms.com"

async def get_calendar_march():
    http_client = httpx.AsyncClient(base_url=base, verify=False, timeout=30, follow_redirects=True)
    http_client.headers.update({"User-Agent": s.browser_user_agent})
    await http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
    resp = await http_client.post(
        f"{base}/login_c2/do_single_login",
        data={"hotel": "18330", "login": s.otelms_default_username, "password": s.otelms_default_password, "action": "login"},
        headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"},
    )
    cookies = [{"name": c.name, "value": c.value, "domain": ".otelms.com", "path": "/"} for c in http_client.cookies.jar]
    await http_client.aclose()

    async with AsyncCamoufox(headless=True) as browser:
        ctx = await browser.new_context(user_agent=s.browser_user_agent, viewport={"width": 1920, "height": 1080})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.goto(f"{base}/reservation_c2/calendar", wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)

        print(f"Initial URL: {page.url}")
        print(f"Frames: {len(page.frames)}")

        # Check calendar HTML for month name
        html = await page.content()
        month_match = re.findall(r'(Janeiro|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|Enero|January|February|March)[^<]{0,20}', html)
        print(f"Months in HTML: {month_match[:5]}")

        # Navigate to March using setmonth
        # First check what month we're seeing
        # Find the month selector - try clicking month nav buttons
        for i in range(7):
            try:
                await page.evaluate("setmonth(-1)")
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"  setmonth error: {e}")
                break

        html = await page.content()
        month_match = re.findall(r'(Janeiro|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre|January|February|March)[^<]{0,20}', html)
        print(f"After nav - months: {month_match[:3]}")
        print(f"Has Marzo: {'Marzo' in html or 'March' in html}")

        # Search for rooms 201, 103, 209
        for room_num in ["201", "103", "209"]:
            count = html.count(room_num)
            print(f"  Room {room_num}: {count} refs in HTML")

        # Check for date 01/03 to 03/03
        marzo_refs = re.findall(r'(01/03/2026|03/03/2026|01/03.*03/03)', html)
        print(f"  March 1-3 refs: {len(marzo_refs)}")

        Path(__file__).parent.joinpath("calendar_march.html").write_text(html, encoding="utf-8")
        print(f"\nSaved calendar_march.html: {len(html)} bytes")

        await page.screenshot(path="calendar_march.png")
        await ctx.close()
        print("✅ Done")

asyncio.run(get_calendar_march())