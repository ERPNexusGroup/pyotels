"""
Test for wait strategies.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from otelms.scraping.wait_strategies import (
    wait_for_ajax_complete,
    wait_for_infinite_scroll,
    wait_for_element_stable,
    setup_ajax_monitoring,
    smart_wait,
)


class TestWaitStrategies:
    """Test wait strategy utilities."""

    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page."""
        page = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_function = AsyncMock()
        page.evaluate = AsyncMock()
        page.add_init_script = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_wait_for_ajax_complete(self, mock_page):
        """Test AJAX completion wait."""
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=[0, 0])  # jQuery.active, pending_requests
        
        result = await wait_for_ajax_complete(mock_page, timeout=5000)
        
        assert result is True
        mock_page.wait_for_load_state.assert_called_once_with("networkidle", timeout=5000)

    @pytest.mark.asyncio
    async def test_wait_for_ajax_with_jquery(self, mock_page):
        """Test AJAX wait with jQuery active."""
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=[3, 0, 0])  # jQuery.active=3, then 0, pending=0
        mock_page.wait_for_function = AsyncMock()
        
        result = await wait_for_ajax_complete(mock_page, timeout=5000)
        
        assert result is True
        mock_page.wait_for_function.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_for_infinite_scroll(self, mock_page):
        """Test infinite scroll waiting."""
        # The function makes these evaluate calls:
        # 1. document.body.scrollHeight (initial) -> 1000
        # 2. window.scrollTo(...) -> None
        # 3. document.body.scrollHeight (after scroll) -> 2000
        # 4. document.body.scrollHeight (2nd iteration) -> 2000
        # 5. window.scrollTo(...) -> None
        # 6. document.body.scrollHeight (after 2nd scroll) -> 2000 (stable)
        mock_page.evaluate = AsyncMock(side_effect=[1000, None, 2000, 2000, None, 2000])
        
        scrolls = await wait_for_infinite_scroll(mock_page, max_scrolls=10, wait_between=100)
        
        # Should scroll until height stabilizes (2 scrolls)
        assert scrolls >= 2

    @pytest.mark.asyncio
    async def test_wait_for_element_stable(self, mock_page):
        """Test element stabilization wait."""
        mock_locator = AsyncMock()
        mock_locator.inner_html = AsyncMock(side_effect=["<div>content</div>", "<div>content</div>"])
        mock_page.locator = MagicMock(return_value=mock_locator)
        
        result = await wait_for_element_stable(mock_page, ".test-selector", stable_duration=100, timeout=5000)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_setup_ajax_monitoring(self, mock_page):
        """Test AJAX monitoring injection."""
        await setup_ajax_monitoring(mock_page)
        
        mock_page.add_init_script.assert_called_once()
        # Check that script contains fetch/XHR tracking
        call_args = mock_page.add_init_script.call_args[0][0]
        assert "fetch" in call_args
        assert "_otelms_pending_requests" in call_args

    @pytest.mark.asyncio
    async def test_smart_wait(self, mock_page):
        """Test smart wait combination."""
        mock_page.wait_for_load_state = AsyncMock()
        
        with patch("otelms.scraping.wait_strategies.wait_for_ajax_complete", new_callable=AsyncMock) as mock_ajax:
            mock_ajax.return_value = True
            await smart_wait(mock_page, timeout=5000)
            
            mock_page.wait_for_load_state.assert_called_once_with("networkidle", timeout=5000)
            mock_ajax.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])