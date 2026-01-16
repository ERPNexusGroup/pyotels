# src/pyotels/data_processor.py
import html
import re
from datetime import datetime
from typing import List, Dict, Any, Union

from bs4 import BeautifulSoup

from .logger import get_logger
from .models import (
    RoomCategory, ReservationData, CalendarData, ReservationDetail,
    CalendarReservation, CalendarCategories
)


class OtelsProcessadorData:
    """Procesa datos estructurados del calendario HTML de OtelMS."""

    def __init__(self, html_content: Union[str, Dict[str, str]], include_empty_cells: bool = False):
        self.logger = get_logger(classname="OtelsProcessadorData")
        self.logger.info("Inicializando OtelsProcessadorData...")
        
        self.modals_data = {}
        self.soup = None
        
        if isinstance(html_content, dict):
            self.modals_data = html_content
            # Inicializar soup con vacío para evitar errores si se llaman otros métodos
            self.soup = BeautifulSoup("", 'html.parser')
            self.logger.debug(f"Inicializado con {len(self.modals_data)} modales.")
        else:
            self.soup = BeautifulSoup(html_content, 'html.parser')
            self.logger.debug(f"HTML cargado. Longitud: {len(html_content)} caracteres.")

        self.day_id_to_date = {}
        self.categories = []
        self.rooms_data = []
        self.date_range = {}
        self.include_empty_cells = include_empty_cells
        self.room_id_to_category = {}

        # Construir mapeo de fechas al inicializar (solo si hay soup válido)
        if self.soup and self.soup.text:
            self._build_date_mapping()

    def extract_categories(self) -> CalendarCategories:
        """Extrae solo las categorías y habitaciones."""
        self.logger.info("Extrayendo categorías...")
        self._extract_categories_internal()

        return CalendarCategories(
            categories=self.categories,
            extracted_at=datetime.now().isoformat()
        )

    def extract_reservations(self) -> CalendarReservation:
        """Extrae solo la grilla de reservaciones (celdas)."""
        self.logger.info("Extrayendo grilla de reservaciones...")

        if not self.categories:
            self._extract_categories_internal()

        self._extract_rooms_data()
        self._extract_date_range()

        return CalendarReservation(
            reservation_data=self.rooms_data,
            date_range=self.date_range,
            extracted_at=datetime.now().isoformat(),
            day_id_to_date=self.day_id_to_date
        )

    def extract_all_reservation_modals(self) -> List[ReservationDetail]:
        """
        Procesa todos los modales almacenados y retorna una lista de ReservationDetail.
        """
        self.logger.info(f"Procesando {len(self.modals_data)} modales de reserva...")
        details = []
        
        for res_id, modal_html in self.modals_data.items():
            try:
                # Reutilizamos la lógica de extracción de detalles
                # Pasamos el HTML del modal directamente
                detail = self.extract_reservation_details(modal_html, res_id)
                details.append(detail)
            except Exception as e:
                self.logger.error(f"Error procesando modal para reserva {res_id}: {e}")
                continue
                
        self.logger.info(f"✅ Procesados {len(details)} detalles de reserva exitosamente.")
        return details
    
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
        Extrae los detalles de la reserva desde el HTML de un folio (Modal).
        """
        # self.logger.debug(f"Extrayendo detalles para la reserva ID: {reservation_id}")
        soup = BeautifulSoup(html_content, 'html.parser')

        # Extraer información general de la reserva
        info = self._extract_general_reservation_info(soup)

        detail = ReservationDetail(
            reservation_number=info.get('reservation_number', reservation_id),
            guest_name=info.get('guest_name'),
            check_in=info.get('check_in'),
            check_out=info.get('check_out'),
            created_at=info.get('created_at'),  # No siempre disponible en el modal
            guest_count=info.get('guest_count'),
            balance=info.get('balance'),
            total=info.get('total'),
            paid=info.get('paid'),
            phone=info.get('phone'),
            email=info.get('email'),
            user=info.get('user'),
            comments=info.get('comments'),
            room_type=info.get('room_type'),
            room=info.get('room'),
            rate=info.get('rate'),
            source=info.get('source'),
            reservation_status=info.get('reservation_status'),
            raw_html=html_content if include_raw_html else None
        )
        return detail

    # --- Métodos Internos ---

    def _extract_room_id_mapping(self) -> Dict[str, List[str]]:
        """
        Extrae el mapeo de category_id a una lista de room_id's desde la tabla 'desk'
        """
        if not self.soup: return {}
        
        self.logger.debug("Extrayendo mapeo de room_id desde la tabla 'desk'...")
        mapping = {}
        desk_table = self.soup.find('table', id='desk')
        if not desk_table:
            # self.logger.warning("No se encontró la tabla 'desk'. No se pudo mapear room_id.")
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
                if current_category_id:
                    room_id = first_td.get('room_id')
                    if room_id and room_id != '0':
                        if room_id not in mapping[current_category_id]:
                            mapping[current_category_id].append(room_id)

        for cat_id in mapping:
            mapping[cat_id].sort(key=int)

        return mapping

    def _extract_categories_internal(self):
        """Lógica interna para extraer categorías."""
        if self.categories or not self.soup: return

        self.logger.debug("Procesando DOM para categorías...")

        room_id_map = self._extract_room_id_mapping()

        category_elements = self.soup.find_all('div', {'class': 'calendar_rooms',
                                                       'id': lambda x: x and x.startswith('btn_close')})

        for cat_elem in category_elements:
            category_id = cat_elem.get('catid')
            if not category_id: continue

            category_name_elem = cat_elem.find('div', class_='calendar_rooms_dott')
            category_name = category_name_elem.get_text(strip=True) if category_name_elem else f"Category_{category_id}"

            category_room_ids = room_id_map.get(category_id, [])
            rooms = self._extract_rooms_for_category(category_id, category_room_ids)

            self.categories.append(RoomCategory(id=category_id, name=category_name, rooms=rooms))

    def _extract_rooms_for_category(self, category_id: str, room_ids: List[str]) -> List[Dict[str, Any]]:
        rooms = []
        if not self.soup: return rooms
        
        selector = f'div.calendar_num_room.btn_close_box{category_id}'
        room_elements = self.soup.select(selector)

        for i, room_elem in enumerate(room_elements):
            room_text_elem = room_elem.find('div', class_='calendar_number_room')
            if room_text_elem:
                room_text = room_text_elem.get_text(strip=True)
                room_number = room_text.split()[0] if room_text else f"room_{category_id}"

                current_room_id = room_ids[i] if i < len(room_ids) else None

                rooms.append({'room_number': room_number, 'room_id': current_room_id})

                if current_room_id:
                    self.room_id_to_category[current_room_id] = {'category_id': category_id, 'category_name': '',
                                                                 'room_number': room_number}
        return rooms

    def _extract_rooms_data(self):
        """Extrae los datos diarios de todas las habitaciones."""
        if not self.soup: return
        
        self.logger.info("Iniciando extracción de datos de celdas (habitaciones/días)...")

        calendar_cells = self.soup.select('td.calendar_td[day_id][room_id]')

        for cell in calendar_cells:
            try:
                room_id = cell.get('room_id')
                day_id = cell.get('day_id')

                if room_id == '0' or not day_id:
                    continue

                reservation = self._extract_reservation_from_cell(cell)

                cell_status = 'available'
                if 'bg_padlock' in cell.get('class', []):
                    cell_status = 'locked'
                if reservation.get('reservation_number'):
                    cell_status = 'occupied'

                if not self.include_empty_cells and cell_status in ['available', 'locked']:
                    continue

                # Resolver info de habitación si no viene en la reserva
                room_number = f"Unknown_{room_id}"
                room_type = None

                if room_id in self.room_id_to_category:
                    info = self.room_id_to_category[room_id]
                    room_number = info['room_number']
                    # room_type podría venir de la categoría si se mapeara

                self.rooms_data.append(ReservationData(
                    reservation_number=reservation.get('reservation_number'),
                    guest_name=reservation.get('guest_name'),
                    check_in=reservation.get('check_in'),
                    check_out=reservation.get('check_out'),
                    created_at=reservation.get('created_at'),
                    guest_count=reservation.get('guest_count'),
                    balance=reservation.get('balance'),
                    total=reservation.get('total'),
                    paid=reservation.get('paid'),
                    phone=reservation.get('phone'),
                    email=reservation.get('email'),
                    user=reservation.get('user'),
                    comments=reservation.get('comments'),
                    room_type=reservation.get('room_type'),  # Si está en el tooltip
                    room=reservation.get('room') or room_number,
                    rate=reservation.get('rate'),
                    reservation_status=reservation.get('reservation_status'),

                    room_id=room_id,
                    day_id=day_id,
                    date=self._convert_day_id_to_date(day_id),
                    cell_status=cell_status
                ))

            except Exception as e:
                self.logger.error(f"❌ Error procesando celda (room_id={room_id}, day_id={day_id}): {e}")
                continue

    @staticmethod
    def _extract_reservation_from_cell(cell) -> Dict[str, Any]:
        data = {}
        res_block = cell.find(lambda tag: tag.name == 'div' and tag.get('resid'))
        if res_block:
            data['reservation_number'] = res_block.get('resid')

            # Extraer status de la reserva
            status_val = res_block.get('status')
            if status_val:
                try:
                    data['reservation_status'] = int(status_val)
                except (ValueError, TypeError):
                    data['reservation_status'] = None

            tooltip_html = res_block.get('data-title', '')
            if tooltip_html:
                decoded_html = html.unescape(tooltip_html)

                # Extracciones
                guest_match = re.search(r'Huésped:\s*([^<]+)', decoded_html)
                if guest_match: data['guest_name'] = guest_match.group(1).strip()

                check_in_match = re.search(r'Llegada:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                if check_in_match: data['check_in'] = check_in_match.group(1)

                check_out_match = re.search(r'Salida:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                if check_out_match: data['check_out'] = check_out_match.group(1)

                created_match = re.search(r'fecha de creación:\s*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', decoded_html,
                                          re.IGNORECASE)
                if created_match: data['created_at'] = created_match.group(1)

                guest_count_match = re.search(r'Cantidad de huéspedes:\s*(\d+)', decoded_html)
                if guest_count_match:
                    try:
                        data['guest_count'] = int(guest_count_match.group(1))
                    except:
                        data['guest_count'] = 0

                balance_match = re.search(r'Balance:\s*([+-]?\d+\.?\d*)', decoded_html)
                if balance_match:
                    try:
                        data['balance'] = float(balance_match.group(1))
                    except:
                        data['balance'] = 0.0

                phone_match = re.search(r'Teléfono:\s*([^<]*)', decoded_html)
                if phone_match: data['phone'] = phone_match.group(1).strip()

                email_match = re.search(r'Email:\s*([^<]*)', decoded_html)
                if email_match: data['email'] = email_match.group(1).strip()

                user_match = re.search(r'Usuario:\s*([^<]*)', decoded_html)
                if user_match: data['user'] = user_match.group(1).strip()

                comments_match = re.search(r'Comentarios:\s*(.*?)<', decoded_html)
                if comments_match: data['comments'] = comments_match.group(1).strip()

        return data

    def _build_date_mapping(self):
        """Construye el mapeo day_id -> fecha ISO."""
        # Implementación placeholder si no hay lógica específica de mapeo en el snippet
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
    def _extract_general_reservation_info(soup: BeautifulSoup) -> Dict[str, Any]:
        info = {}

        # 1. Reservation ID
        h2 = soup.find('h2', class_='nameofgroup')
        if h2:
            text = h2.get_text(strip=True)
            match = re.search(r'#(\d+)', text)
            if match:
                info['reservation_number'] = match.group(1)

        # 2. Balance (Top header)
        header_div = soup.find('div', class_='text-right vertical_wrapper')
        if header_div:
            text = header_div.get_text(strip=True)
            match = re.search(r'Saldo:\s*([+-]?\d+\.?\d*)', text)
            if match:
                try:
                    info['balance'] = float(match.group(1))
                except:
                    info['balance'] = 0.0

        # 3. Key-Value pairs in panel-body
        panel_body = soup.find('div', class_='panel-body')
        if panel_body:
            labels = panel_body.find_all('span', class_='incolor')
            for label_span in labels:
                key = label_span.get_text(strip=True).lower().replace(':', '')

                key_div = label_span.parent
                value_div = key_div.find_next_sibling('div')

                if not value_div: continue

                value_text = value_div.get_text(strip=True)

                if 'fuente' in key:
                    info['source'] = value_text
                elif 'llegada' in key:
                    match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})', value_text)
                    if match: info['check_in'] = match.group(1)
                elif 'salida' in key:
                    match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})', value_text)
                    if match: info['check_out'] = match.group(1)
                elif 'huésped' in key and 'número' not in key:
                    info['guest_name'] = value_text
                elif 'número de huéspedes' in key:
                    try:
                        numbers = re.findall(r'\d+', value_text)
                        if numbers:
                            info['guest_count'] = int(numbers[0])
                    except:
                        info['guest_count'] = 1
                elif 'teléfono' in key:
                    info['phone'] = value_text
                elif 'e-mail' in key or 'email' in key:
                    info['email'] = value_text
                elif 'tipo de habitación' in key:
                    info['room_type'] = value_text
                elif 'habitación' in key and 'tipo' not in key:
                    info['room'] = value_text
                elif 'tarifa' in key:
                    info['rate'] = value_text
                elif 'total' in key:
                    try:
                        info['total'] = float(value_text.replace(',', ''))
                    except:
                        info['total'] = 0.0
                elif 'pagado' in key:
                    try:
                        info['paid'] = float(value_text.replace(',', ''))
                    except:
                        info['paid'] = 0.0
                elif 'notas' in key:
                    info['comments'] = value_text
                elif 'usuario' in key:
                    info['user'] = value_text

        return info
