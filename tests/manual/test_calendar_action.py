"""Interactuar con el calendar: close/open dates + drag-drop."""
import asyncio
import re
from otelms.scraping.browser import BrowserPool

async def test_calendar_action():
    pool = BrowserPool(pool_size=1, headless=True)
    await pool.initialize()

    # Acquire a page (already logged in via _create_instance)
    async with pool.acquire() as page:
        await page.goto("https://desktop.otelms.com/reservation_c2/calendar", wait_until="networkidle")
        print(f"Calendar title: {await page.title()}")
        print(f"Calendar URL: {page.url}")

        # Find reservation items con resid
        res_items = await page.eval_on_selector_all(
            "[resid]",
            "elements => elements.map(e => ({ resid: e.getAttribute('resid'), class: e.className }))",
        )
        print(f"\nReservation items: {len(res_items)}")
        for item in res_items[:3]:
            print(f"  {item}")

        # Find buttons
        buttons = await page.eval_on_selector_all(
            "button",
            "elements => Array.from(new Set(elements.map(e => e.textContent.trim()))).filter(t => t.length > 0 && t.length < 40)",
        )
        print(f"\nButtons ({len(buttons)}):")
        for btn in sorted(buttons)[:25]:
            print(f"  '{btn}'")

        # Look for room rows (room calendar view)
        room_rows = await page.eval_on_selector_all(
            "[class*='room'], .room-name, .room-item",
            "elements => elements.map(e => ({ class: e.className, id: e.id, text: e.textContent.trim().slice(0,30) }))",
        )
        print(f"\nRoom elements: {len(room_rows)}")
        for el in room_rows[:5]:
            print(f"  {el}")

    await pool.close()
    print("\n✅ Calendar UI explorada")

if __name__ == "__main__":
    asyncio.run(test_calendar_action())