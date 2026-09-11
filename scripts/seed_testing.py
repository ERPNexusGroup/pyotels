"""
Seed idempotente para staging de fase 1 (DB efímera: se re-ejecuta en cada arranque).

Crea/actualiza:
  - Hotel OTELMS_DEFAULT_HOTEL_ID (default 18330) con credenciales reales
    (password cifrado con Fernet derivado de JWT_SECRET_KEY — el mismo .env
    que usan los contenedores api/worker, o el sync no podrá descifrar).
  - ApiKey "staging-key" con sha256(API_KEY), igual que verify_api_key.

Uso (BD staging en localhost:5433 según docker-compose.yml):
  $env:PYTHONPATH = $null; & ".venv/Scripts/python.exe" scripts/seed_testing.py

Variables (o .env en la raíz, que el script lee como fallback):
  DATABASE_URL, OTELMS_DEFAULT_HOTEL_ID, OTELMS_DEFAULT_USERNAME,
  OTELMS_DEFAULT_PASSWORD, API_KEY, JWT_SECRET_KEY
"""
import asyncio
import hashlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Fallback mínimo a .env (sin dependencias externas): solo KEY=VALUE, sin export.
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

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from otelms.domain.entities import ApiKey, Base, Hotel  # noqa: E402
from otelms.utils.crypto import credential_encryption  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://otelms:otelms_dev_password@localhost:5433/otelms"
)
HOTEL_ID = os.environ.get("OTELMS_DEFAULT_HOTEL_ID", "18330")
USERNAME = os.environ.get("OTELMS_DEFAULT_USERNAME", "")
PASSWORD = os.environ.get("OTELMS_DEFAULT_PASSWORD", "")
API_KEY = os.environ.get("API_KEY", "")


async def main() -> None:
    missing = [k for k, v in {
        "OTELMS_DEFAULT_USERNAME": USERNAME,
        "OTELMS_DEFAULT_PASSWORD": PASSWORD,
        "API_KEY": API_KEY,
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY", ""),
    }.items() if not v]
    if missing:
        raise SystemExit(f"Faltan variables en entorno/.env: {', '.join(missing)}")

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        hotel = await session.get(Hotel, HOTEL_ID)
        if hotel is None:
            hotel = Hotel(
                id=HOTEL_ID,
                name="Harmony Hotel (staging)",
                domain=os.environ.get("OTELMS_BASE_DOMAIN", "otelms.com"),
                username=USERNAME,
                password_hash=hashlib.sha256(b"rotated").hexdigest(),
                encrypted_password=credential_encryption.encrypt(PASSWORD),
                is_active=True,
            )
            session.add(hotel)
            print(f"hotel {HOTEL_ID}: creado")
        else:
            hotel.username = USERNAME
            hotel.encrypted_password = credential_encryption.encrypt(PASSWORD)
            hotel.is_active = True
            print(f"hotel {HOTEL_ID}: actualizado")

        api_key = await session.get(ApiKey, "staging-key")
        key_hash = hashlib.sha256(API_KEY.encode()).hexdigest()
        if api_key is None:
            session.add(ApiKey(id="staging-key", name="Phase 1 testing", key_hash=key_hash))
            print("api_key staging-key: creada")
        else:
            api_key.key_hash = key_hash
            api_key.is_active = True
            print("api_key staging-key: actualizada")

        await session.commit()

    await engine.dispose()
    print("seed OK")


if __name__ == "__main__":
    asyncio.run(main())
