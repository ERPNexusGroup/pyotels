"""
Pytest configuration and fixtures.
"""
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from otelms.domain.entities import Base
from otelms.config.settings import Settings


# Test database URL (SQLite file-based for test isolation)
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )
    
    print("DEBUG: Creating tables with full schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("DEBUG: Tables created with full schema")
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncSession:
    """Create test database session."""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session


@pytest.fixture
def test_settings():
    """Test settings override."""
    return Settings(
        app_env="testing",
        app_debug=True,
        database_url=TEST_DATABASE_URL,
        redis_url="redis://localhost:6379/0",
        cache_enabled=False,
        scraper_headless=True,
        otelms_default_hotel_id="test_hotel",
        otelms_default_username="test@test.com",
        otelms_default_password="testpass",
    )


@pytest.fixture
def sample_reservation_data():
    """Sample reservation data for testing."""
    return {
        "id": "12345",
        "hotel_id": "test_hotel",
        "room_id": "room_1",
        "guest_id": "guest_1",
        "check_in": "2026-01-15T14:00:00",
        "check_out": "2026-01-18T11:00:00",
        "status": 1,
        "adults": 2,
        "children": 1,
        "babies": 0,
        "total_price": "250.00",
        "currency": "USD",
        "source": "booking",
        "notes": "Test reservation",
    }


@pytest.fixture
def sample_guest_data():
    """Sample guest data for testing."""
    return {
        "id": "guest_1",
        "hotel_id": "test_hotel",
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "phone": "+1234567890",
        "document_type": "passport",
        "document_number": "AB123456",
        "country": "US",
    }


@pytest.fixture
def sample_category_data():
    """Sample category data for testing."""
    return {
        "id": "cat_1",
        "name": "Standard",
        "rooms": [
            {"id": "room_1", "name": "101", "category_id": "cat_1"},
            {"id": "room_2", "name": "102", "category_id": "cat_1"},
        ],
    }