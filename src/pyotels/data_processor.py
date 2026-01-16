# src/pyotels/data_processor.py
import html
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

from .logger import get_logger
from .models import (
    RoomCategory, ReservationData, CalendarData, ReservationDetail,
    CalendarGrid, CalendarCategories,
    Guest, Service, PaymentTransaction,
    Note, Car, DailyTariff, ChangeLog, Card
)

class OtelsProcessadorData:
    """Procesa datos estructurados del calendario HTML de OtelMS."""

    def __init__(self, html_content: str, include_empty_cells: bool = False):
        self.logger = get_logger(classname="OtelsProcessadorData")
        self.logger.info("Inicializando OtelsProcessadorData...")
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.day_id_to_date = {}
        self.categories = []
        self.rooms_data = []
        self.date_range = {}
        self.include_empty_cells = include_empty_cells
        self.room_id_to_category = {}
        
        # Construir mapeo de fechas al inicializar, ya que es necesario para casi todo
        self._build_date_mapping()
        
        self.logger.debug(
            f"HTML cargado. Longitud: {len(html_content)} caracteres. Include empty cells: {include_empty_cells}")

    def extract_categories(self) -> CalendarCategories:
        """Extrae solo las categorías y habitaciones."""
        self.logger.info("Extrayendo categorías...")
        self._extract_categories_internal()
        
        return CalendarCategories(
            categories=self.categories,
            extracted_at=datetime.now().isoformat()
        )

    def extract_grid(self) -> CalendarGrid:
        """Extrae solo la grilla de reservaciones (celdas)."""
        self.logger.info("Extrayendo grilla de reservaciones...")
        
        # Necesitamos las categorías para mapear room_id -> category
        if not self.categories:
            self._extract_categories_internal()

        self._extract_rooms_data()
        self._extract_date_range()

        return CalendarGrid(
            reservation_data=self.rooms_data,
            date_range=self.date_range,
            extracted_at=datetime.now().isoformat(),
            day_id_to_date=self.day_id_to_date
        )

    def extract_calendar_data(self) -> CalendarData:
        """Extrae TODOS los datos del calendario (Legacy/Completo)."""
        self.logger.info("Inicio del proceso de extracción COMPLETA de datos del calendario.")
        try:
            self._extract_categories_internal()
            self._extract_rooms_data()
            self._extract_date_range()

            return CalendarData(
                categories=self.categories,
                reservation_data=self.rooms_data,
                date_range=self.date_range,
                extracted_at=datetime.now().isoformat(),
                day_id_to_date=self.day_id_to_date
            )
        except Exception as e:
            self.logger.error(f"❌ Error crítico extrayendo datos del calendario: {e}", exc_info=True)
            raise

    def extract_reservation_details(self, html_content: str, reservation_id: str,
                                    include_raw_html: bool = False) -> ReservationDetail:
        """
        Extrae los detalles de la reserva desde el HTML de un folio.
        """
        self.logger.info(f"Extrayendo detalles para la reserva ID: {reservation_id}")
        soup = BeautifulSoup(html_content, 'html.parser')

        # Extraer información general de la reserva
        general_info = self._extract_general_reservation_info(soup)

        # Extraer huéspedes
        residents = self._extract_residents(soup)

        # Extraer servicios
        services = self._extract_services(soup)

        # Extraer pagos
        payments = self._extract_payments(soup)

        # Extraer tarjetas (nuevo)
        cards = self._extract_cards(soup)

        # Extraer coches (nuevo)
        cars = self._extract_cars(soup)

        # Extraer notas (nuevo)
        notes = self._extract_notes(soup)

        # Extraer logs
        logs = self._extract_logs(soup)

        # Extraer tarifas diarias
        daily_tariffs = self._extract_daily_tariffs(soup)

        detail = ReservationDetail(
            reservation_id=general_info.get('id', reservation_id),
            guests=residents,
            services=services,
            payments=payments,
            cards=cards,
            cars=cars,
            notes=notes,
            logs=logs,
            daily_tariffs=daily_tariffs,
            balance=general_info.get('balance', 0.0),
            total_price=general_info.get('total_price', 0.0),
            channel_info=general_info.get('channel_info', {}),
            basic_info=general_info,
            raw_html=html_content if include_raw_html else None
        )
        self.logger.info(f"✅ Detalles de reserva {detail.reservation_id} extraídos.")
        return detail

    # --- Métodos Internos ---

    def _extract_room_id_mapping(self) -> Dict[str, List[str]]:
        """
        Extrae el mapeo de category_id a una lista de room_id's desde la tabla 'desk'
        iterando a través de los tbody.
        """
        self.logger.debug("Extrayendo mapeo de room_id desde la tabla 'desk'...")
        mapping = {}
        desk_table = self.soup.find('table', id='desk')
        if not desk_table:
            self.logger.warning("No se encontró la tabla 'desk'. No se pudo mapear room_id.")
            return mapping

        tbodies = desk_table.find_all('tbody')
        current_category_id = None

        for tbody in tbodies:
            is_category_header = 'my_category' in tbody.get('class', [])
            
            first_td = tbody.find('td')
            if not first_td:
                continue

            if is_category_header:
                category_id = first_td.get('category_id')
                if category_id:
                    current_category_id = category_id
                    if current_category_id not in mapping:
                        mapping[current_category_id] = []
            else:
                # This is a room row
                if current_category_id:
                    room_id = first_td.get('room_id')
                    if room_id and room_id != '0':
                        # Evitar duplicados si el mismo room_id aparece en varias celdas de la fila
                        if room_id not in mapping[current_category_id]:
                             mapping[current_category_id].append(room_id)

        # Ordenar los room_ids para asegurar consistencia
        for cat_id in mapping:
            mapping[cat_id].sort(key=int)

        self.logger.debug(f"Mapeo de room_id extraído: {mapping}")
        return mapping

    def _extract_categories_internal(self):
        """Lógica interna para extraer categorías."""
        if self.categories: return

        self.logger.debug("Procesando DOM para categorías...")
        
        room_id_map = self._extract_room_id_mapping()

        category_elements = self.soup.find_all('div', {'class': 'calendar_rooms',
                                                       'id': lambda x: x and x.startswith('btn_close')})

        for cat_elem in category_elements:
            category_id = cat_elem.get('catid')
            if not category_id: continue

            category_name_elem = cat_elem.find('div', class_='calendar_rooms_dott')
            category_name = category_name_elem.get_text(strip=True) if category_name_elem else f"Category_{category_id}"
            
            # Pasar el mapa de room_ids específico para esta categoría
            category_room_ids = room_id_map.get(category_id, [])
            rooms = self._extract_rooms_for_category(category_id, category_room_ids)

            self.categories.append(RoomCategory(id=category_id, name=category_name, rooms=rooms))
        self.logger.debug(f"Categorías encontradas: {len(self.categories)}")

    def _extract_rooms_for_category(self, category_id: str, room_ids: List[str]) -> List[Dict[str, Any]]:
        rooms = []
        selector = f'div.calendar_num_room.btn_close_box{category_id}'
        room_elements = self.soup.select(selector)

        for i, room_elem in enumerate(room_elements):
            room_text_elem = room_elem.find('div', class_='calendar_number_room')
            if room_text_elem:
                room_text = room_text_elem.get_text(strip=True)
                room_number = room_text.split()[0] if room_text else f"room_{category_id}"

                # Asignar room_id desde la lista ordenada
                current_room_id = room_ids[i] if i < len(room_ids) else None

                rooms.append({'room_number': room_number, 'room_id': current_room_id})

                if current_room_id:
                    self.room_id_to_category[current_room_id] = {'category_id': category_id, 'category_name': '',
                                                                 'room_number': room_number}
        return rooms


    def _extract_rooms_data(self):
        """Extrae los datos diarios de todas las habitaciones."""
        self.logger.info("Iniciando extracción de datos de celdas (habitaciones/días)...")
        
        # Mapa auxiliar para nombres de categorías
        category_map = {cat.id: cat.name for cat in self.categories}

        calendar_cells = self.soup.select('td.calendar_td[day_id][room_id]')
        all_cell = len(calendar_cells)
        self.logger.info(f"Total de celdas a procesar: {all_cell}")

        for i, cell in enumerate(calendar_cells):
            try:
                room_id = cell.get('room_id')
                day_id = cell.get('day_id')
                cell_category_id = cell.get('category_id')

                if room_id == '0' or not day_id:
                    continue

                reservation = self._extract_reservation_from_cell(cell)

                status = 'available'
                if 'bg_padlock' in cell.get('class', []):
                    status = 'locked'
                if reservation['id']:
                    status = 'occupied'

                if not self.include_empty_cells and status in ['available', 'locked']:
                    continue

                # Resolver info de habitación
                room_number = f"Unknown_{room_id}"
                real_category_id = cell_category_id

                if room_id in self.room_id_to_category:
                    info = self.room_id_to_category[room_id]
                    room_number = info['room_number']
                    real_category_id = info['category_id']

                category_name = category_map.get(real_category_id, f'Category_{real_category_id}') if real_category_id else None
                availability = 0 

                self.rooms_data.append(ReservationData(
                    date=self._convert_day_id_to_date(day_id),
                    room_id=room_id,
                    room_number=room_number,
                    category_id=real_category_id,
                    category_name=category_name,
                    status=status,
                    availability=availability,
                    day_id=day_id,
                    details_reservation={},
                    reservation_id=reservation['id'],
                    guest_name=reservation['guest_name'],
                    source=reservation['source'],
                    check_in=reservation['check_in'],
                    check_out=reservation['check_out'],
                    balance=reservation['balance']
                ))

            except Exception as e:
                self.logger.error(f"❌ Error procesando celda (room_id={room_id}, day_id={day_id}): {e}")
                continue

    @staticmethod
    def _extract_reservation_from_cell(cell):
        reservation_data = {
            'id': None, 'guest_name': None, 'source': None,
            'check_in': None, 'check_out': None, 'balance': None, 'reservation_type': None
        }
        res_block = cell.find(lambda tag: tag.name == 'div' and tag.get('resid'))
        if res_block:
            reservation_data['id'] = res_block.get('resid')
            tooltip_html = res_block.get('data-title', '')
            if tooltip_html:
                decoded_html = html.unescape(tooltip_html)
                guest_match = re.search(r'Huésped:\s*([^<]+)', decoded_html)
                if guest_match: reservation_data['guest_name'] = guest_match.group(1).strip()

                check_in_match = re.search(r'Lllegada:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                if check_in_match: reservation_data['check_in'] = check_in_match.group(1)

                check_out_match = re.search(r'Salida:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                if check_out_match: reservation_data['check_out'] = check_out_match.group(1)

                balance_match = re.search(r'Balance:\s*([+-]?\d+\.?\d*)', decoded_html)
                if balance_match: reservation_data['balance'] = balance_match.group(1)

                source_match = re.search(r'Reserva .+?,\s*([^<]+)', decoded_html)
                if source_match: reservation_data['source'] = source_match.group(1).strip()

        return reservation_data

    def _build_date_mapping(self):
        """Construye el mapeo day_id -> fecha ISO."""
        # Lógica simplificada o existente para mapear day_id a fecha
        # Si no hay lógica real, usar placeholder para evitar errores
        pass

    def _extract_date_range(self):
        if self.day_id_to_date:
            sorted_dates = sorted(self.day_id_to_date.values())
            self.date_range = {
                'start_date': sorted_dates[0] if sorted_dates else "Unknown",
                'end_date': sorted_dates[-1] if sorted_dates else "Unknown",
                'total_days': len(sorted_dates)
            }
        else:
            self.date_range = {'start_date': "Unknown", 'end_date': "Unknown", 'total_days': 0}

    def _convert_day_id_to_date(self, day_id: str) -> str:
        return self.day_id_to_date.get(day_id, f"unknown_date_{day_id}")

    @staticmethod
    def _find_section_by_title(soup: BeautifulSoup, title_keyword: str) -> Optional[Any]:
        panels = soup.find_all('div', class_='panel')
        for panel in panels:
            heading = panel.find('div', class_='panel-heading')
            if heading:
                h2 = heading.find('h2')
                if h2 and title_keyword.lower() in h2.get_text(strip=True).lower():
                    return panel
        return None

    @staticmethod
    def _extract_general_reservation_info(soup: BeautifulSoup) -> Dict[str, Any]:
        info = {}
        res_id = None
        h1_tag = soup.find('h1')
        if h1_tag:
            h1_text = h1_tag.get_text()
            match = re.search(r'№\s*(\d+)', h1_text)
            if match: res_id = match.group(1)

        if not res_id:
            id_input = soup.find('input', {'name': 'id_reservation'})
            if id_input: res_id = id_input.get('value')

        info['id'] = res_id
        
        # Balance
        for span in soup.find_all('span'):
            txt = span.get_text()
            if "Saldo:" in txt:
                try:
                    info['balance'] = float(txt.replace("Saldo:", "").strip())
                except:
                    info['balance'] = 0.0
                break
        if 'balance' not in info: info['balance'] = 0.0

        # Divs
        folio_divs = soup.find_all('div', class_='col-md-3')
        for div in folio_divs:
            b_tag = div.find('b')
            if not b_tag: continue
            label_text = b_tag.get_text(strip=True).replace(":", "").lower()
            value_container = b_tag.next_sibling
            if value_container and value_container.name == 'br':
                value_container = value_container.next_sibling
            
            value = ""
            if value_container:
                if hasattr(value_container, 'get_text'):
                    value = value_container.get_text(strip=True)
                else:
                    value = str(value_container).strip()

            if 'cliente' in label_text: info['client_name'] = value
            elif 'teléfono' in label_text: info['phone'] = value
            elif 'email' in label_text: info['email'] = value
            elif 'fuente' in label_text: info['source'] = value
            elif 'noches' in label_text: 
                try: info['nights'] = int(value)
                except Exception: pass
            elif 'habitación' in label_text: info['room'] = value

        return info

    @staticmethod
    def _extract_residents(soup: BeautifulSoup) -> List[Guest]:
        residents = []
        residents_section = soup.find('div', id='anchors_info_residents')
        if not residents_section: return residents
        
        rows = residents_section.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                # Evitar cabeceras
                if row.find('th'): continue
                
                name_link = cols[0].find('a')
                name = name_link.get_text(strip=True) if name_link else cols[0].get_text(strip=True)
                email = cols[2].get_text(strip=True)
                dob = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                residents.append(Guest(name=name, email=email, dob=dob))
        return residents

    def _extract_services(self, soup: BeautifulSoup) -> List[Service]:
        services = []
        services_section = self._find_section_by_title(soup, "Servicios")
        if not services_section: services_section = soup.find('div', id='anchors_services')
        if not services_section: return services

        rows = services_section.find_all('tr')
        # Simple parsing asumiendo estructura conocida si no hay headers claros
        # O usar la lógica de índices previa si se desea robustez
        for row in rows:
            if row.find('th'): continue # Skip header
            cols = row.find_all('td')
            if len(cols) > 5:
                try:
                    # Ajustar índices según observación visual del HTML
                    services.append(Service(
                        title=cols[2].get_text(strip=True),
                        price=float(cols[6].get_text(strip=True).replace(',', '') or 0),
                        quantity=float(cols[7].get_text(strip=True) or 1)
                    ))
                except: continue
        return services

    def _extract_payments(self, soup: BeautifulSoup) -> List[PaymentTransaction]:
        payments = []
        payments_section = self._find_section_by_title(soup, "Lista de pagos")
        if not payments_section: payments_section = soup.find('div', id='anchors_list_payments')
        if not payments_section: return payments

        rows = payments_section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 8:
                try:
                    payments.append(PaymentTransaction(
                        date=cols[0].get_text(strip=True),
                        created=cols[1].get_text(strip=True),
                        id=cols[2].get_text(strip=True),
                        amount=cols[6].get_text(strip=True),
                        method=cols[7].get_text(strip=True)
                    ))
                except: continue
        return payments

    def _extract_cards(self, soup: BeautifulSoup) -> List[Card]:
        cards = []
        cards_section = self._find_section_by_title(soup, "Lista de tarjetas de pago")
        if not cards_section: return cards
        rows = cards_section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 2:
                cards.append(Card(number=cols[1].get_text(strip=True), holder="", expiration=""))
        return cards

    def _extract_cars(self, soup: BeautifulSoup) -> List[Car]:
        cars = []
        cars_section = self._find_section_by_title(soup, "Coche")
        if not cars_section: return cars
        rows = cars_section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 3:
                cars.append(Car(brand=cols[0].get_text(strip=True), color=cols[1].get_text(strip=True), plate=cols[2].get_text(strip=True), model=""))
        return cars

    @staticmethod
    def _extract_notes(soup: BeautifulSoup) -> List[Note]:
        notes = []
        panels = soup.find_all('div', class_='panel')
        notes_section = None
        for panel in panels:
            heading = panel.find('div', class_='panel-heading')
            if heading and "Notas" in heading.get_text(strip=True) and panel.find('table'):
                notes_section = panel
                break
        if not notes_section: return notes
        
        rows = notes_section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 3:
                notes.append(Note(date=cols[0].get_text(strip=True), author=cols[1].get_text(strip=True), message=cols[2].get_text(strip=True)))
        return notes

    @staticmethod
    def _extract_logs(soup: BeautifulSoup) -> List[ChangeLog]:
        logs = []
        logs_section = soup.find('div', id='anchors_log')
        if not logs_section: return logs
        rows = logs_section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 6:
                logs.append(ChangeLog(
                    date=cols[0].get_text(strip=True),
                    log_id=cols[1].get_text(strip=True),
                    user=cols[2].get_text(strip=True),
                    type=cols[3].get_text(strip=True),
                    action=cols[4].get_text(strip=True),
                    amount=cols[5].get_text(strip=True),
                    description=cols[6].get_text(strip=True) if len(cols) > 6 else ""
                ))
        return logs

    @staticmethod
    def _extract_daily_tariffs(soup: BeautifulSoup) -> List[DailyTariff]:
        tariffs = []
        section = soup.find('div', id='anchors_billing_days')
        if not section: return tariffs
        rows = section.find_all('tr')
        for row in rows:
            if row.find('th'): continue
            cols = row.find_all('td')
            if len(cols) >= 3:
                try:
                    tariffs.append(DailyTariff(
                        date=cols[0].get_text(strip=True),
                        rate_type=cols[1].get_text(strip=True),
                        price=float(cols[2].get_text(strip=True).replace(',', ''))
                    ))
                except: pass
        return tariffs
