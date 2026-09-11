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

# .env como fallback (sin sobreescribir variables ya exportadas).
# IMPORTANTE: DATABASE_URL del .env local apunta a SQLite de desarrollo;
# el seed SIEMPRE va contra el Postgres de staging salvo que DATABASE_URL
# esté exportada explícitamente en el shell (el .env se ignora para esta var).
from dotenv import load_dotenv  # noqa: E402

_explicit_env = set(os.environ)
load_dotenv(REPO_ROOT / ".env")

STAGING_DATABASE_URL = (
    "postgresql+asyncpg://otelms:otelms_dev_password@localhost:5435/otelms"
)
if "DATABASE_URL" in _explicit_env:
    DATABASE_URL = os.environ["DATABASE_URL"]
else:
    DATABASE_URL = STAGING_DATABASE_URL
    os.environ.pop("DATABASE_URL", None)  # evita que settings lea el SQLite del .env

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from otelms.domain.entities import ApiKey, Base, Hotel  # noqa: E402
from otelms.utils.crypto import credential_encryption  # noqa: E402

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

    _u = make_url(DATABASE_URL)
    print(f"target: {_u.drivername} @ {_u.host}:{_u.port}/{_u.database}")

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
