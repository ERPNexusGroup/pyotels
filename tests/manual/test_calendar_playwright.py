"""Calendar interaction: login con requests, navegar con Playwright."""
import asyncio
import re
import json
from playwright.sync_api import sync_playwright
from otelms.config.settings import get_settings

def test_calendar_sync():
    settings = get_settings()

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            user_agent=settings.browser_user_agent,
            viewport={"width": 1280, "height": 800},
        )

        # Login
        page = context.new_page()
        page.goto("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", wait_until="domcontentloaded")

        # Fill login form
        username_input = page.wait_for_selector("input[name='login']")
        username_input.fill(settings.otelms_default_username)

        password_input = page.wait_for_selector("input[name='password']")
        password_input.fill(settings.otelms_default_password)

        submit_btn = page.wait_for_selector("input[type='submit'], button[type='submit']")
        submit_btn.click()

        # Wait for redirect to calendar
        page.wait_for_url("**/reservation_c2/calendar", timeout=15000)
        print(f"✅ Logged in, URL: {page.url}")

        # Wait for calendar JS render
        page.wait_for_timeout(5000)

        # Check for iframe
        iframe = page.frame(name="calendar_iframe") or (page.frames[1] if len(page.frames) > 1 else None)

        if iframe:
            print(f"📋 Found iframe: {iframe.url}")
            iframe.wait_for_timeout(3000)

            # Get reservation items inside iframe
            items = iframe.eval_on_selector_all("[resid]", "e => e.map(i => ({resid: i.getAttribute('resid'), class: i.className, title: i.getAttribute('data-title') || ''}))")
            print(f"📅 Reservation items in iframe: {len(items)}")
            for item in items[:5]:
                print(f"  {item['resid']}: {item['title'][:60]}")

            # Find action buttons
            buttons = iframe.eval_on_selector_all("button", "e => Array.from(new Set(e.map(i => i.textContent.trim()))).filter(t => t.length > 0 && t.length < 40)")
            print(f"\n📋 Buttons inside iframe ({len(buttons)}):")
            for btn in sorted(buttons)[:20]:
                print(f"  '{btn}'")

            # Find room rows
            room_rows = iframe.query_selector_all(".room-name, .room-item, .room-row")
            print(f"\n🏨 Room rows: {len(room_rows)}")
            for row in room_rows[:5]:
                print(f"  {row.get_attribute('class')}: {row.text_content()[:50]}")

            # Check for availability/cell elements
            cells = iframe.query_selector_all(".calendar_cell, .day-cell, td.fc-daygrid-day-cell")
            print(f"\n📆 Date cells: {len(cells)}")
        else:
            print("❌ No iframe found")
            # Get page HTML
            html = page.content()
            has_resid = html.count("resid")
            has_cal = html.count("calendar")
            print(f"Page HTML: {len(html)} bytes, resid count: {has_resid}")

        # Screenshot
        page.screenshot(path="calendar_full.png")
        print(f"\n📸 Screenshot saved: calendar_full.png")

        browser.close()
        print("\n✅ Calendar interaction completed")

if __name__ == "__main__":
    test_calendar_sync()