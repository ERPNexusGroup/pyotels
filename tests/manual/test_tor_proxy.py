import asyncio

from otelms.scraping.tor_proxy import TorProxyManager


async def test():
    """Test full Tor proxy flow."""
    async with TorProxyManager() as tor:
        ip1 = await tor.verify_proxy()
        print(f"IP 1: {ip1}")

        await asyncio.sleep(3)
        await tor.rotate_circuit()
        ip2 = await tor.verify_proxy()
        print(f"IP 2: {ip2}")

        print(f"Different: {ip1 != ip2}")

asyncio.run(test())