"""Tests manuales para validación E2E del sync de OtelMS.

Estos tests requieren conexión a internet y credenciales válidas.
Ejecutar: env -u PYTHONPATH .venv/Scripts/python.exe tests/manual/test_full_sync_e2e.py
"""
# Test principal: test_full_sync_e2e.py — Sync completo (27 reservas + guests + services + payments)
# Test secundario: test_login_browser.py — Test de login con Playwright
# Test de proxy: test_tor_proxy.py — Test de rotación de IPs Tor (deprecated, usar Scrape.do)

# NOTA: Los tests con prefijo test_*.py en tests/manual/ NO corren con pytest.
# Están diseñados para ejecución manual con python.