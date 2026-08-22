"""Test login OtelMS con Playwright (formulario real, selectors flexibles)."""
import asyncio
from camoufox.async_api import AsyncCamoufox


async def login_via_browser():
    async with AsyncCamoufox(headless=True) as browser:
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        await page.goto("https://desktop.otelms.com/login_c2/single_login?hmsid=18330", wait_until="networkidle")

        # Ver disponible selectors
        content = await page.content()
        print(f"Page title: {await page.title()}")
        print(f"Has input[name=login]: {'input[name=login]' in content}")
        print(f"Has 'input[name=userLogin]': {'userLogin' in content}")

        # Try flexible selector
        try:
            await page.wait_for_selector("input[name='login'], input[name='userLogin'], #userLogin, #login", timeout=5000)
            await page.fill("input[name='login'], input[name='userLogin']", "gerencia@harmonyhotelgroup.com")
        except Exception as e:
            print(f"Login input not found: {e}")

        try:
            await page.fill("input[name='password'], #password, input[type='password']", "***")
        except Exception as e:
            print(f"Password input not found: {e}")

        # Click submit
        await page.click("input[type='submit'], button[type='submit'], #loginForm button")
        await page.wait_for_timeout(5000)

        print(f"After submit URL: {page.url}")

        # Calendar
        await page.goto("https://desktop.otelms.com/reservation_c2/calendar")
        await page.wait_for_timeout(3000)
        final_url = page.url
        cal_content = await page.content()
        print(f"Calendar URL: {final_url}")
        print(f"Calendar length: {len(cal_content)}")
        print(f"Has calendar_table: {'calendar_table' in cal_content}")
        print(f"Has session_id: {'session_id' in str(await context.cookies())}")

        await context.close()


asyncio.run(login_via_browser())