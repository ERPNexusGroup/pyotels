"""Extraer calendar HTML renderizado con Playwright + cookies HTTP."""
import asyncio
import re
from pathlib import Path

from camoufox import AsyncCamoufox
from otelms.config.settings import get_settings
import httpx, urllib3

urllib3.disable_warnings()
settings = get_settings()

# Login HTTP
http_client = httpx.Client(verify=False, timeout=30)
http_client.headers.update({"User-Agent": settings.browser_user_agent})
base = "https://desktop.otelms.com"
http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
http_client.post(f"{base}/login_c2/do_single_login",
    data={"hotel":"18330","login":settings.otelms_default_username,"password":settings.otelms_default_password,"action":"login"},
    headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"})
cookies = [{"name": c.name, "value": c.value, "domain": ".otelms.com", "path": "/"} for c in http_client.cookies.jar]

async def get_rendered_calendar():
    async with AsyncCamoufox(headless=True) as browser:
        ctx = await browser.new_context(user_agent=settings.browser_user_agent, viewport={"width": 1920, "height": 1080})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.goto(base + "/reservation_c2/calendar", wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)

        html = await page.content()

        # Check iframe
        iframe_elems = re.findall(r'<iframe[^>]+src="([^"]+)"', html)
        print(f"iframe srcs: {iframe_elems}")

        # Check for resid/reservation content
        print(f"Has resid: {'resid' in html}")
        print(f"Has calendar_item: {'calendar_item' in html}")

        # Save HTML
        Path(__file__).parent.joinpath("calendar_rendered.html").write_text(html, encoding="utf-8")
        print(f"Saved: {len(html)} bytes")

        # Quick check for room buttons
        buttons = re.findall(r'<button[^>]*>([^<]+)</button>', html)
        interesting = [b for b in buttons if any(kw in b.lower() for kw in ["close", "open", "block", "room", "estado", "disponible", "status"])]
        print(f"Interesting buttons: {interesting[:10]}")

        # Check for room rows
        room_elems = re.findall(r'(room|habitacion|disponibilidad)', html, re.I)
        print(f"Room-related mentions: {len(room_elems)}")

        await ctx.close()

asyncio.run(get_rendered_calendar())