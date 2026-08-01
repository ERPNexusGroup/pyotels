"""
Unit tests for repositories.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from decimal import Decimal

from otelms.domain.entities import (
    Hotel, Category, Room, Guest, Reservation, Service, Payment, SyncLog
)
from otelms.domain.repositories import (
    HotelRepository,
    CategoryRepository,
    RoomRepository,
    GuestRepository,
    ReservationRepository,
    ServiceRepository,
    PaymentRepository,
    SyncLogRepository,
)
from otelms.domain.repositories.database import get_db_session


@pytest_asyncio.fixture
async def session(test_engine):
    """Create test session."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def hotel_repo(session):
    return HotelRepository(session)


@pytest_asyncio.fixture
async def category_repo(session):
    return CategoryRepository(session)


@pytest_asyncio.fixture
async def room_repo(session):
    return RoomRepository(session)


@pytest_asyncio.fixture
async def guest_repo(session):
    return GuestRepository(session)


@pytest_asyncio.fixture
async def reservation_repo(session):
    return ReservationRepository(session)


@pytest_asyncio.fixture
async def service_repo(session):
    return ServiceRepository(session)


@pytest_asyncio.fixture
async def payment_repo(session):
    return PaymentRepository(session)


class TestHotelRepository:
    """Tests for HotelRepository."""

    async def test_create_and_get(self, hotel_repo):
        hotel = await hotel_repo.create(
            id="hotel_1",
            name="Test Hotel",
            domain="otelms.com",
            username="test@test.com",
            password_hash="hashed_password",
            is_active=True,
        )
        assert hotel.id == "hotel_1"
        assert hotel.name == "Test Hotel"

        retrieved = await hotel_repo.get_by_id("hotel_1")
        assert retrieved is not None
        assert retrieved.id == "hotel_1"
        assert retrieved.name == "Test Hotel"

    async def test_get_active(self, hotel_repo):
        await hotel_repo.create(id="hotel_1", name="Active Hotel", domain="otelms.com", username="a@a.com", password_hash="h", is_active=True)
        await hotel_repo.create(id="hotel_2", name="Inactive Hotel", domain="otelms.com", username="b@b.com", password_hash="h", is_active=False)

        active = await hotel_repo.get_active()
        assert len(active) == 1
        assert active[0].id == "hotel_1"

    async def test_upsert(self, hotel_repo):
        # Create
        hotel, is_new = await hotel_repo.upsert(id="hotel_1", name="Hotel 1", domain="otelms.com", username="u@u.com", password_hash="h")
        assert is_new is True

        # Update
        hotel, is_new = await hotel_repo.upsert(id="hotel_1", name="Hotel 1 Updated")
        assert is_new is False
        assert hotel.name == "Hotel 1 Updated"


class TestCategoryRepository:
    """Tests for CategoryRepository."""

    async def test_create_and_get(self, category_repo, hotel_repo):
        # Need hotel first
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")

        cat = await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")
        assert cat.id == "cat_1"
        assert cat.name == "Standard"

        retrieved = await category_repo.get_by_id("cat_1")
        assert retrieved is not None

    async def test_upsert_with_rooms(self, category_repo, hotel_repo):
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")

        cat_data = {
            "id": "cat_1",
            "name": "Standard",
            "rooms": [
                {"id": "room_1", "name": "101", "category_id": "cat_1"},
            ],
        }

        cat, is_new = await category_repo.upsert_with_rooms("hotel_1", cat_data)
        assert is_new is True
        assert cat.name == "Standard"

        # Update
        cat_data["name"] = "Standard Updated"
        cat, is_new = await category_repo.upsert_with_rooms("hotel_1", cat_data)
        assert is_new is False
        assert cat.name == "Standard Updated"


class TestRoomRepository:
    """Tests for RoomRepository."""

    async def test_create_and_get(self, room_repo, hotel_repo, category_repo):
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")
        await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")

        room = await room_repo.create(id="room_1", hotel_id="hotel_1", category_id="cat_1", name="101")
        assert room.id == "room_1"
        assert room.name == "101"

        retrieved = await room_repo.get_by_id("room_1")
        assert retrieved is not None


class TestGuestRepository:
    """Tests for GuestRepository."""

    async def test_create_and_get(self, guest_repo, hotel_repo):
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")

        guest = await guest_repo.create(
            id="guest_1",
            hotel_id="hotel_1",
            first_name="John",
            last_name="Doe",
            email="john@test.com",
        )
        assert guest.id == "guest_1"
        assert guest.first_name == "John"

        retrieved = await guest_repo.get_by_id("guest_1")
        assert retrieved is not None

    async def test_get_or_create_by_name(self, guest_repo, hotel_repo):
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")

        guest, is_new = await guest_repo.get_or_create_by_name("hotel_1", "John Doe")
        assert is_new is True
        assert guest.first_name == "John"
        assert guest.last_name == "Doe"

        # Second call should return existing
        guest2, is_new2 = await guest_repo.get_or_create_by_name("hotel_1", "John Doe")
        assert is_new2 is False
        assert guest2.id == guest.id

    async def test_upsert_from_scraper(self, guest_repo, hotel_repo):
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")

        guest_data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@test.com",
        }

        guest, is_new = await guest_repo.upsert_from_scraper("hotel_1", guest_data)
        assert is_new is True
        assert guest.first_name == "Jane"


class TestReservationRepository:
    """Tests for ReservationRepository."""

    async def test_create_and_get(self, reservation_repo, hotel_repo, room_repo, guest_repo, category_repo):
        # Setup dependencies
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")
        await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")
        await room_repo.create(id="room_1", hotel_id="hotel_1", category_id="cat_1", name="101")
        await guest_repo.create(id="guest_1", hotel_id="hotel_1", first_name="John", last_name="Doe")

        res = await reservation_repo.create(
            id="res_1",
            hotel_id="hotel_1",
            room_id="room_1",
            guest_id="guest_1",
            check_in=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
            check_out=datetime(2026, 1, 18, 11, 0, tzinfo=timezone.utc),
            status=1,
        )
        assert res.id == "res_1"

        retrieved = await reservation_repo.get_by_id("res_1")
        assert retrieved is not None

    async def test_upsert_from_scraper(self, reservation_repo, hotel_repo, room_repo, guest_repo, category_repo):
        # Setup
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")
        await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")
        await room_repo.create(id="room_1", hotel_id="hotel_1", category_id="cat_1", name="101")
        await guest_repo.create(id="guest_1", hotel_id="hotel_1", first_name="John", last_name="Doe")

        # Create new
        res_data = {
            "id": "res_1",
            "hotel_id": "hotel_1",
            "room_id": "room_1",
            "guest_id": "guest_1",
            "check_in": "2026-01-15T14:00:00",
            "check_out": "2026-01-18T11:00:00",
            "status": 1,
        }

        res, is_new, updated = await reservation_repo.upsert_from_scraper("hotel_1", res_data)
        assert is_new is True
        assert updated is False

        # Update same data (should not update due to hash)
        res, is_new, updated = await reservation_repo.upsert_from_scraper("hotel_1", res_data)
        assert is_new is False
        assert updated is False

        # Update with different data
        res_data["status"] = 2
        res, is_new, updated = await reservation_repo.upsert_from_scraper("hotel_1", res_data)
        assert is_new is False
        assert updated is True
        assert res.status == 2


class TestServiceRepository:
    """Tests for ServiceRepository."""

    async def test_bulk_upsert(self, service_repo, hotel_repo, room_repo, guest_repo, category_repo, reservation_repo):
        # Setup
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")
        await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")
        await room_repo.create(id="room_1", hotel_id="hotel_1", category_id="cat_1", name="101")
        await guest_repo.create(id="guest_1", hotel_id="hotel_1", first_name="John", last_name="Doe")
        await reservation_repo.create(
            id="res_1",
            hotel_id="hotel_1",
            room_id="room_1",
            guest_id="guest_1",
            check_in=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
            check_out=datetime(2026, 1, 18, 11, 0, tzinfo=timezone.utc),
            status=1,
        )

        services = [
            {"id": "svc_1", "date": "2026-01-15T10:00:00", "title": "Breakfast", "quantity": 2, "price": 10.00, "total": 20.00},
            {"id": "svc_2", "date": "2026-01-16T10:00:00", "title": "Lunch", "quantity": 1, "price": 25.00, "total": 25.00},
        ]

        count = await service_repo.bulk_upsert("res_1", services)
        assert count == 2

        # Verify
        retrieved = await service_repo.get_by_reservation("res_1")
        assert len(retrieved) == 2


class TestPaymentRepository:
    """Tests for PaymentRepository."""

    async def test_bulk_upsert(self, payment_repo, hotel_repo, room_repo, guest_repo, category_repo, reservation_repo):
        # Setup
        await hotel_repo.create(id="hotel_1", name="Test Hotel", domain="otelms.com", username="t@t.com", password_hash="h")
        await category_repo.create(id="cat_1", hotel_id="hotel_1", name="Standard")
        await room_repo.create(id="room_1", hotel_id="hotel_1", category_id="cat_1", name="101")
        await guest_repo.create(id="guest_1", hotel_id="hotel_1", first_name="John", last_name="Doe")
        await reservation_repo.create(
            id="res_1",
            hotel_id="hotel_1",
            room_id="room_1",
            guest_id="guest_1",
            check_in=datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
            check_out=datetime(2026, 1, 18, 11, 0, tzinfo=timezone.utc),
            status=1,
        )

        payments = [
            {"id": "pmt_1", "date": "2026-01-15T10:00:00", "amount": 100.00, "method": "cash"},
            {"id": "pmt_2", "date": "2026-01-16T10:00:00", "amount": 150.00, "method": "card"},
        ]

        count = await payment_repo.bulk_upsert("res_1", payments)
        assert count == 2

        total = await payment_repo.get_total_paid("res_1")
        assert total == 250.00