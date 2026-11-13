"""Calendar interaction: Camoufox directo sin proxy + cookies HTTP."""
import asyncio
import re
import json
from playwright.async_api import async_playwright
from camoufox import AsyncCamoufox
from otelms.config.settings import get_settings

async def test_calendar_direct():
    settings = get_settings()

    # 1. Login HTTP
    import httpx
    import urllib3
    urllib3.disable_warnings()

    http_client = httpx.Client(verify=False, timeout=30)
    http_client.headers.update({"User-Agent": settings.browser_user_agent})

    base = "https://desktop.otelms.com"
    http_client.get(f"{base}/login_c2/single_login?hmsid=18330")
    resp = http_client.post(
        f"{base}/login_c2/do_single_login",
        data={"hotel": "18330", "login": settings.otelms_default_username,
              "password": settings.otelms_default_password, "action": "login"},
        headers={"Referer": f"{base}/login_c2/single_login?hmsid=18330"},
    )
    print(f"Login POST: {resp.status_code}")

    cookies = [{"name": c.name, "value": c.value, "domain": ".otelms.com", "path": "/"}
               for c in http_client.cookies.jar]
    print(f"Cookies: {len(cookies)}")

    # 2. Camoufox direct sin proxy
    async with AsyncCamoufox(headless=True) as browser:
        context = await browser.new_context(
            user_agent=settings.browser_user_agent,
            viewport={"width": 1280, "height": 800},
        )

        # Set cookies
        await context.add_cookies(cookies)

        page = await context.new_page()
        await page.goto("https://desktop.otelms.com/reservation_c2/calendar", wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)
        print(f"Calendar: {page.url}, title: {await page.title()}")

        # Check iframe
        iframes = page.frames
        print(f"Frames: {len(iframes)}")
        iframe = iframes[1] if len(iframes) > 1 else None

        if iframe:
            print(f"Iframe: {iframe.url}")
            await iframe.wait_for_timeout(4000)

            # Reservation items in iframe
            items = await iframe.eval_on_selector_all("[resid]",
                "e => e.map(i => ({resid: i.getAttribute('resid'), status: i.getAttribute('status'), class: i.className}))")
            print(f"📅 Reservation items: {len(items)}")
            for item in items[:5]:
                print(f"  {item}")

            # Buttons
            buttons = await iframe.eval_on_selector_all("button, .btn",
                "e => Array.from(new Set(e.map(i => i.textContent.trim()))).filter(t => t.length > 0 && t.length < 40)")
            print(f"\n📋 Buttons ({len(buttons)}):")
            for btn in sorted(buttons)[:30]:
                print(f"  '{btn}'")

            # Date cells
            cells = await iframe.eval_on_selector_all("td.fc-daygrid-day, .day, .calendar_cell",
                "e => e.slice(0,10).map(i => ({class: i.className, id: i.id || '', text: i.textContent.trim().slice(0,15)}))")
            print(f"\n📆 Date cells: {len(cells)}")

            # Room rows (room calendar)
            room_rows = await iframe.eval_on_selector_all(".room-name, .room-item, [class*='room'], tr.room-row",
                "e => e.slice(0,10).map(i => ({class: i.className, text: i.textContent.trim().slice(0,40)}))")
            print(f"\n🏨 Room rows: {len(room_rows)}")
            for r in room_rows[:5]:
                print(f"  {r}")

            # Click handlers for close/open
            click_elems = await iframe.eval_on_selector_all("[onclick]",
                "e => e.filter(i => { const o = i.getAttribute('onclick'); return o && /block|status|close|open|occupy/i.test(o) }).map(i => ({tag: i.tagName, onclick: i.getAttribute('onclick').slice(0,120)}))")
            print(f"\n🔧 Click handlers (close/open/block): {len(click_elems)}")
            for el in click_elems[:5]:
                print(f"  {el}")

        await page.screenshot(path="calendar_camoufox.png")
        await context.close()

    print(f"\n📸 Screenshot: calendar_camoufox.png")
    print("✅ Done")

if __name__ == "__main__":
    asyncio.run(test_calendar_direct())