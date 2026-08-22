import asyncio
import requests
import os

from otelms.scraping.tor_proxy import TorProxyManager


async def test_scrape_do_httpx():
    """Test direct with requests."""
    api_key = "***"
    proxy_url = f"http://scraper:{api_key}@proxy.scrape.do:9000"
    
    resp = requests.get(
        "https://httpbin.org/ip",
        proxies={"http": proxy_url, "https": proxy_url},
        timeout=30,
    )
    print(f"HTTP {resp.status_code}: {resp.json()}")


async def test_otelms_login():
    """Test OtelMS login via proxy."""
    api_key = "***"
    proxy_url = f"http://scraper:{api_key}@proxy.scrape.do:9000"
    
    session = requests.Session()
    session.proxies = {"http": proxy_url, "https": proxy_url}
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
    
    # GET login page
    r1 = session.get("https://desktop.otelms.com/login_c2/single_login?hmsid=18330")
    print(f"Login page: {r1.status_code}")
    
    # POST
    resp = session.post(
        "https://desktop.otelms.com/login_c2/do_single_login",
        data={"hotel": "18330", "login": "gerencia@harmonyhotelgroup.com", "password": "***", "action": "login"},
        headers={"Referer": "https://desktop.otelms.com/login_c2/single_login?hmsid=18330", "Origin": "https://desktop.otelms.com", "Content-Type": "application/x-www-form-urlencoded"},
    )
    print(f"POST status: {resp.status_code}")
    print(f"Cookies: {list(session.cookies.keys())}")
    
    # Calendar
    cal = session.get("https://desktop.otelms.com/reservation_c2/calendar")
    print(f"Calendar len: {len(cal.text)}")
    print(f"Has user_data: {'user_data' in cal.text or 'session_id' in str(session.cookies)}")

asyncio.run(test_scrape_do_httpx())