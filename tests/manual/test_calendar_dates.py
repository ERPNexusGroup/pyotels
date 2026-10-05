"""Interactuar con el calendar para close/open dates (drag-drop)."""
import asyncio
import re
from otelms.config.settings import get_settings
from otelms.scraping.browser import BrowserInstance

async def test_calendar_interaction():
    settings = get_settings()
    browser = BrowserInstance(settings=settings, hotel_id=18330)
    await browser.initialize()
    page = await browser.get_page("https://desktop.otelms.com/reservation_c2/calendar")

    print(f"Calendar title: {await page.title()}")

    # Find reservation items con resid
    res_items = await page.eval_on_selector_all(
        "[resid]",
        "elements => elements.map(e => ({ resid: e.getAttribute('resid'), class: e.className }))",
    )
    print(f"\nReservation items: {len(res_items)}")
    for item in res_items[:3]:
        print(f"  {item}")

    # Find date cells (calendar grid)
    date_cells = await page.eval_on_selector_all(
        "td.fc-daygrid-day-cell, .calendar_cell, td.calendar_day",
        "elements => elements.map(e => ({ date: e.getAttribute('data-date') || '', class: e.className, text: e.textContent.trim().slice(0,10) }))",
    )
    print(f"\nDate cells: {len(date_cells)}")
    for cell in date_cells[:3]:
        print(f"  {cell}")

    # Find buttons
    buttons = await page.eval_on_selector_all(
        "button, .btn",
        "elements => Array.from(new Set(elements.map(e => e.textContent.trim()))).filter(t => t.length > 0 && t.length < 30)",
    )
    print(f"\nButtons ({len(buttons)}):")
    for btn in sorted(buttons)[:20]:
        print(f"  '{btn}'")

    # Look for "Bloquear" / "Close" / "Open" buttons
    block_keywords = ["bloquear", "bloquear", "close", "open", "ocupar", "desocupar", "bloquear", "desbloquear"]
    for btn_text in buttons:
        if any(kw in btn_text.lower() for kw in block_keywords):
            print(f"\n  🔍 Found block button: '{btn_text}'")

    # Save screenshot for analysis
    await page.screenshot(path="calendar_screenshot.png", full_page=True)
    print(f"\n📸 Screenshot saved: calendar_screenshot.png")

    await browser.close()
    print("\n✅ Calendar UI explorada")

if __name__ == "__main__":
    asyncio.run(test_calendar_interaction())