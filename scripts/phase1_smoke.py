"""
Smoke test fase 1: disponibilidad / ocupación / salidas contra staging.

Requiere: staging levantado + seed + sync manual ya ejecutado (Fase 3).
Solo LEE endpoints; no modifica nada.

Uso:
  & ".venv/Scripts/python.exe" scripts/phase1_smoke.py [check_in] [check_out]
  Ej: & ".venv/Scripts/python.exe" scripts/phase1_smoke.py 2026-09-11 2026-09-14

Env (o .env en la raíz): BASE_URL (default http://localhost:8002),
  API_KEY, API_KEY_HEADER (default X-API-Key), HOTEL_ID (default 18330).

Sale con código 1 si alguna verificación falla.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    for raw in _env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value

try:
    import httpx
except ImportError:
    sys.exit("httpx no instalado en el venv (.venv/Scripts/python.exe -m pip install httpx)")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8002").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
HEADER = os.environ.get("API_KEY_HEADER", "X-API-Key")
HOTEL_ID = os.environ.get("HOTEL_ID", os.environ.get("OTELMS_DEFAULT_HOTEL_ID", "18330"))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not condition:
        failures.append(name)


def main() -> None:
    if not API_KEY:
        sys.exit("Falta API_KEY en entorno/.env")
    today = date.today()
    check_in = sys.argv[1] if len(sys.argv) > 1 else today.isoformat()
    check_out = sys.argv[2] if len(sys.argv) > 2 else (today + timedelta(days=3)).isoformat()
    headers = {HEADER: API_KEY}

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        r = client.get("/health")
        check("health 200", r.status_code == 200, f"-> {r.status_code}")

        r = client.get("/rooms/available", headers=headers,
                       params={"hotel_id": HOTEL_ID, "check_in": check_in, "check_out": check_out})
        check("available 200", r.status_code == 200, f"-> {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            consistent = d["available_count"] + d["occupied_count"] == d["total_rooms"]
            check("available: avail+occ==total", consistent,
                  f"(total={d['total_rooms']} avail={d['available_count']} occ={d['occupied_count']})")
            cats_ok = all(c["available"] + c["occupied"] == c["total"] for c in d["by_category"])
            check("available: categorías consistentes", cats_ok,
                  f"({len(d['by_category'])} categorías)")

        r = client.get("/rooms/occupied", headers=headers,
                       params={"hotel_id": HOTEL_ID, "target_date": check_in})
        check("occupied 200", r.status_code == 200, f"-> {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            check("occupied: count==len(items)", d["occupied_count"] == len(d["items"]),
                  f"(count={d['occupied_count']})")

        r = client.get("/rooms/checkouts", headers=headers,
                       params={"hotel_id": HOTEL_ID, "target_date": check_in})
        check("checkouts 200", r.status_code == 200, f"-> {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            check("checkouts: count==len(items)", d["count"] == len(d["items"]),
                  f"(count={d['count']})")

        # Casos de error
        r = client.get("/rooms/available", headers=headers,
                       params={"hotel_id": HOTEL_ID, "check_in": check_out, "check_out": check_in})
        check("rango inválido -> 400", r.status_code == 400, f"-> {r.status_code}")

        r = client.get("/rooms/available", headers=headers,
                       params={"check_in": check_in, "check_out": check_out})
        check("sin hotel_id -> 422", r.status_code == 422, f"-> {r.status_code}")

        r = client.get("/rooms/available",
                       params={"hotel_id": HOTEL_ID, "check_in": check_in, "check_out": check_out})
        check("sin API key -> 401/422", r.status_code in (401, 422), f"-> {r.status_code}")

    print()
    if failures:
        print(f"SMOKE FAIL: {len(failures)} verificación(es): {', '.join(failures)}")
        sys.exit(1)
    print("SMOKE OK: comparar estos números contra la UI de OtelMS antes de dar por buena la fase.")


if __name__ == "__main__":
    main()
