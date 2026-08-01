"""
Integration tests for sync service.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from otelms.services.sync_service import SyncService
from otelms.scraping.orchestrator import ScrapingResult


@pytest_asyncio.fixture
async def mock_orchestrator():
    """Mock scraping orchestrator."""
    with patch("otelms.services.sync_service.ScrapingOrchestrator") as mock:
        orchestrator = AsyncMock()
        orchestrator.initialize = AsyncMock()
        orchestrator.close = AsyncMock()
        orchestrator.scrape_calendar = AsyncMock()
        orchestrator.scrape_categories = AsyncMock()
        orchestrator.scrape_reservation_details = AsyncMock()
        mock.return_value = orchestrator
        yield orchestrator


@pytest_asyncio.fixture
async def sync_service(mock_orchestrator):
    """Create sync service with mocked orchestrator."""
    service = SyncService(
        hotel_id="test_hotel",
        username="test@test.com",
        password="testpass",
        headless=True,
    )
    service._orchestrator = mock_orchestrator
    service._initialized = True
    return service


class TestSyncService:
    """Integration tests for SyncService."""

    @pytest.mark.asyncio
    async def test_sync_calendar_success(self, sync_service, mock_orchestrator, test_session):
        """Test successful calendar sync."""
        # Mock scrape result
        mock_orchestrator.scrape_calendar.return_value = ScrapingResult(
            success=True,
            data={
                "cells": [
                    {
                        "room_id": "room_1",
                        "room_name": "101",
                        "category_id": "cat_1",
                        "category_name": "Standard",
                        "date": "2026-01-15",
                        "day_id": "day_1",
                        "cell_status": "occupied",
                        "reservation_id": "res_1",
                        "guest_name": "John Doe",
                        "check_in": "2026-01-15",
                        "check_out": "2026-01-18",
                        "reservation_status": 1,
                        "guest_count": 2,
                        "balance": 150.0,
                    }
                ],
                "categories": [
                    {"id": "cat_1", "name": "Standard", "rooms": [{"id": "room_1", "name": "101", "category_id": "cat_1"}]}
                ],
            },
            operation="calendar",
        )

        # Note: This test would need a real database session
        # For now, we verify the service calls are correct
        with patch("otelms.services.sync_service.get_db_session") as mock_db:
            mock_session = AsyncMock()
            mock_db.return_value.__aenter__.return_value = mock_session

            with patch("otelms.services.sync_service.SyncLogRepository") as mock_log_repo:
                mock_log = MagicMock()
                mock_log.id = 1
                mock_log_repo.return_value.create_log = AsyncMock(return_value=mock_log)
                mock_log_repo.return_value.complete_log = AsyncMock()

                with patch("otelms.services.sync_service.CategoryRepository") as mock_cat_repo:
                    mock_cat_repo.return_value.upsert_with_rooms = AsyncMock(return_value=(MagicMock(), True))
                    
                    with patch("otelms.services.sync_service.RoomRepository") as mock_room_repo:
                        mock_room_repo.return_value.upsert = AsyncMock(return_value=(MagicMock(), True))
                        
                        with patch("otelms.services.sync_service.GuestRepository") as mock_guest_repo:
                            mock_guest_repo.return_value.get_or_create_by_name = AsyncMock(return_value=(MagicMock(id="guest_1"), True))
                            
                            with patch("otelms.services.sync_service.ReservationRepository") as mock_res_repo:
                                mock_res = MagicMock()
                                mock_res_repo.return_value.upsert_from_scraper = AsyncMock(return_value=(mock_res, True, False))

                                result = await sync_service.sync_calendar("2026-01-15")

                                assert result.success is True
                                assert result.records_processed > 0

    @pytest.mark.asyncio
    async def test_sync_calendar_failure(self, sync_service, mock_orchestrator):
        """Test calendar sync with scraping failure."""
        mock_orchestrator.scrape_calendar.return_value = ScrapingResult(
            success=False,
            error="Authentication failed",
            operation="calendar",
        )

        result = await sync_service.sync_calendar("2026-01-15")

        assert result.success is False
        assert "Authentication failed" in result.errors

    @pytest.mark.asyncio
    async def test_sync_categories_success(self, sync_service, mock_orchestrator):
        """Test successful categories sync."""
        mock_orchestrator.scrape_categories.return_value = ScrapingResult(
            success=True,
            data=[
                {"id": "cat_1", "name": "Standard", "rooms": [{"id": "room_1", "name": "101", "category_id": "cat_1"}]}
            ],
            operation="categories",
        )

        with patch("otelms.services.sync_service.get_db_session"):
            with patch("otelms.services.sync_service.SyncLogRepository"):
                with patch("otelms.services.sync_service.CategoryRepository") as mock_cat_repo:
                    mock_cat_repo.return_value.upsert_with_rooms = AsyncMock(return_value=(MagicMock(), True))
                    mock_cat_repo.return_value.upsert_with_rooms = AsyncMock(return_value=(MagicMock(), True))

                    result = await sync_service.sync_categories("2026-01-15")

                    assert result.success is True

    @pytest.mark.asyncio
    async def test_full_sync_calls_all_methods(self, sync_service, mock_orchestrator):
        """Test full sync calls calendar, categories, and details."""
        mock_orchestrator.scrape_calendar.return_value = ScrapingResult(
            success=True,
            data={"cells": [], "categories": []},
            operation="calendar",
        )
        mock_orchestrator.scrape_categories.return_value = ScrapingResult(
            success=True,
            data=[],
            operation="categories",
        )
        mock_orchestrator.scrape_reservation_details.return_value = ScrapingResult(
            success=True,
            data=[],
            operation="reservation_details",
        )

        with patch.object(sync_service, "sync_calendar", new=AsyncMock(return_value=SyncResult(
            operation="calendar_sync", hotel_id="test_hotel", success=True, records_processed=10
        ))) as mock_cal:
            with patch.object(sync_service, "sync_categories", new=AsyncMock(return_value=SyncResult(
                operation="categories_sync", hotel_id="test_hotel", success=True, records_processed=5
            ))) as mock_cat:
                with patch.object(sync_service, "sync_reservation_details", new=AsyncMock(return_value=SyncResult(
                    operation="details_sync", hotel_id="test_hotel", success=True, records_processed=3
                ))) as mock_det:

                    result = await sync_service.full_sync("2026-01-15")

                    mock_cal.assert_called_once()
                    mock_cat.assert_called_once()
                    mock_det.assert_called_once()
                    assert result.records_processed == 18  # 10 + 5 + 3