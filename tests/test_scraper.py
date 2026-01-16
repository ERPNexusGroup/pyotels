import unittest
from unittest.mock import patch, MagicMock
from src.pyotels.scraper import OtelMSScraper
from src.pyotels.exceptions import AuthenticationError, NetworkError, ParsingError, DataNotFoundError

class TestOtelMSScraper(unittest.TestCase):

    @patch('src.pyotels.scraper.OtelsExtractor')
    def setUp(self, MockOtelsExtractor):
        self.mock_extractor_instance = MockOtelsExtractor.return_value
        self.scraper = OtelMSScraper(id_hotel='test_hotel', username='user', password='pass')
        self.scraper.extractor = self.mock_extractor_instance

    def test_login_success(self):
        self.mock_extractor_instance.login.return_value = True
        result = self.scraper.login()
        self.assertTrue(result)
        self.mock_extractor_instance.login.assert_called_once_with(username='user', password='pass')

    def test_login_failure(self):
        self.mock_extractor_instance.login.side_effect = AuthenticationError("Login failed")
        with self.assertRaises(AuthenticationError):
            self.scraper.login()

    def test_login_network_error(self):
        self.mock_extractor_instance.login.side_effect = Exception("Network issue")
        with self.assertRaises(NetworkError):
            self.scraper.login()

    @patch('src.pyotels.scraper.OtelsProcessadorData')
    def test_get_categories(self, MockOtelsProcessadorData):
        mock_processor_instance = MockOtelsProcessadorData.return_value
        self.mock_extractor_instance.get_calendar_html.return_value = "<html></html>"
        
        self.scraper.get_categories()

        self.mock_extractor_instance.get_calendar_html.assert_called_once()
        MockOtelsProcessadorData.assert_called_once_with("<html></html>")
        mock_processor_instance.extract_categories.assert_called_once()

    @patch('src.pyotels.scraper.OtelsProcessadorData')
    def test_get_reservations(self, MockOtelsProcessadorData):
        mock_processor_instance = MockOtelsProcessadorData.return_value
        self.mock_extractor_instance.get_calendar_html.return_value = "<html></html>"

        self.scraper.get_reservations("2023-01-01")

        self.mock_extractor_instance.get_calendar_html.assert_called_once_with("2023-01-01")
        MockOtelsProcessadorData.assert_called_once_with("<html></html>")
        mock_processor_instance.extract_grid.assert_called_once()

    @patch('src.pyotels.scraper.OtelsProcessadorData')
    def test_get_reservation_detail(self, MockOtelsProcessadorData):
        mock_processor_instance = MockOtelsProcessadorData.return_value
        self.mock_extractor_instance.get_reservation_detail_html.return_value = "<html></html>"

        self.scraper.get_reservation_detail("12345")

        self.mock_extractor_instance.get_reservation_detail_html.assert_called_once_with("12345")
        MockOtelsProcessadorData.assert_called_once_with("<html></html>")
        mock_processor_instance.extract_reservation_details.assert_called_once()

    def test_get_reservation_detail_not_found(self):
        self.mock_extractor_instance.get_reservation_detail_html.side_effect = DataNotFoundError("Not found")
        
        result = self.scraper.get_reservation_detail("12345")

        self.assertIsNone(result)

    def test_close(self):
        self.scraper.close()
        self.mock_extractor_instance.close.assert_called_once()

if __name__ == '__main__':
    unittest.main()
