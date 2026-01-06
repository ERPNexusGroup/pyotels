import scrapy
from urllib.parse import urlencode
from .config import Config
from .items import ReservationItem
from .extractor import CalendarExtractor, ReservationExtractor

class OtelMSSpider(scrapy.Spider):
    name = "otelms"
    allowed_domains = ["otelms.com"]
    
    # URLs
    LOGIN_URL = "https://118510.otelms.com/login/DoLogIn/"
    CALENDAR_URL = "https://118510.otelms.com/reservation_c2/calendar"

    def start_requests(self):
        self.logger.info(f"Iniciando scraping para la fecha: {Config.TARGET_DATE}")
        
        yield scrapy.FormRequest(
            url=self.LOGIN_URL,
            formdata={
                "login": Config.OTELMS_USER,
                "password": Config.OTELMS_PASS,
                "action": "login"
            },
            callback=self.parse_login
        )

    def parse_login(self, response):
        # Verificar login exitoso
        if "calendar" in response.url or "logout" in response.text.lower() or response.status == 200:
            self.logger.info("Login exitoso (aparente). Navegando al calendario...")
            yield scrapy.Request(
                url=self.CALENDAR_URL,
                callback=self.parse_calendar
            )
        else:
            self.logger.error("Login fallido.")

    def parse_calendar(self, response):
        html_content = response.text
        
        if Config.DEV_MODE:
            with open(Config.get_output_path("calendar_scrapy.html"), "w", encoding="utf-8") as f:
                f.write(html_content)

        extractor = CalendarExtractor(html_content)
        extractor.extract_calendar_data()
        
        processed_urls = set()
        reservations_found = 0
        
        self.logger.info(f"Analizando {len(extractor.rooms_data)} celdas para la fecha {Config.TARGET_DATE}...")
        
        for room in extractor.rooms_data:
            if room.date != Config.TARGET_DATE:
                continue

            if room.detail_url and room.detail_url not in processed_urls:
                processed_urls.add(room.detail_url)
                reservations_found += 1
                full_url = response.urljoin(room.detail_url)
                
                self.logger.info(f"Reserva encontrada para hoy ({room.date}): {full_url}")
                
                yield scrapy.Request(
                    url=full_url,
                    callback=self.parse_reservation,
                    cb_kwargs={'room_number': room.room_number}
                )
        
        if reservations_found == 0:
            self.logger.info(f"No se encontraron reservas para la fecha {Config.TARGET_DATE}")

    def parse_reservation(self, response, room_number):
        html = response.text
        
        if Config.DEV_MODE:
            res_id = response.url.split('/')[-1] or "unknown"
            res_id = res_id.replace('?', '_').replace('&', '_')
            with open(Config.get_output_path(f"reservation_{res_id}.html"), "w", encoding="utf-8") as f:
                f.write(html)

        extractor = ReservationExtractor(html)
        reservation = extractor.extract()

        if reservation:
            item = ReservationItem()
            item['id'] = reservation.id
            item['room_number'] = reservation.room_number if reservation.room_number != 'Unknown' else room_number
            item['check_in'] = reservation.check_in
            item['check_out'] = reservation.check_out
            item['status'] = reservation.status
            item['total_price'] = reservation.total_price
            item['currency'] = reservation.currency
            item['source'] = reservation.source
            
            if reservation.main_guest:
                item['main_guest_name'] = reservation.main_guest.name
                item['main_guest_email'] = reservation.main_guest.email
                item['main_guest_phone'] = reservation.main_guest.phone
            
            item['companions'] = []
            item['raw_data'] = reservation.raw_data
            item['raw_data']['url'] = response.url
            
            yield item
        else:
            self.logger.warning(f"No se pudo extraer información de reserva en {response.url}")
