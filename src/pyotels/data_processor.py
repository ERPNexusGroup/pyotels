# src/pyotels/data_processor.py
import html
import re
from datetime import datetime
from typing import List, Dict, Any, Union, Optional

from bs4 import BeautifulSoup

from .logger import get_logger
from .models import (
    RoomCategory, ReservationData, CalendarData, ReservationDetail,
    CalendarReservation, CalendarCategories, Guest, Service, PaymentTransaction,
    DailyTariff
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

        if self.soup and self.soup.text:
            self._build_date_mapping()

    def extract_categories(self, as_dict: bool = False) -> Union[CalendarCategories, Dict[str, Any]]:
        """Extrae solo las categorías y habitaciones."""
        self.logger.info("Extrayendo categorías...")
        self._extract_categories_internal()

        result = CalendarCategories(
            categories=self.categories,
            extracted_at=datetime.now().isoformat()
        )
        return result.model_dump() if as_dict else result

    def extract_reservations(self, as_dict: bool = False) -> Union[CalendarReservation, Dict[str, Any]]:
        """Extrae solo la grilla de reservaciones (celdas)."""
        self.logger.info("Extrayendo grilla de reservaciones...")

        if not self.categories:
            self._extract_categories_internal()

        self._extract_rooms_data()
        self._extract_date_range()

        result = CalendarReservation(
            reservation_data=self.rooms_data,
            date_range=self.date_range,
            extracted_at=datetime.now().isoformat(),
            day_id_to_date=self.day_id_to_date
        )
        return result.model_dump() if as_dict else result

    def extract_all_reservation_modals(self, as_dict: bool = False) -> Union[List[ReservationDetail], List[Dict[str, Any]]]:
        """
        Procesa todos los modales almacenados y retorna una lista de ReservationDetail o Dicts.
        """
        self.logger.info(f"Procesando {len(self.modals_data)} modales de reserva...")
        details = []
        
        for res_id, modal_html in self.modals_data.items():
            try:
                detail = self.extract_reservation_details(modal_html, res_id, as_dict=as_dict)
                details.append(detail)
            except Exception as e:
                self.logger.error(f"Error procesando modal para reserva {res_id}: {e}")
                continue
                
        self.logger.info(f"✅ Procesados {len(details)} detalles de reserva exitosamente.")
        return details
    
    def extract_calendar_data(self, as_dict: bool = False) -> Union[CalendarData, Dict[str, Any]]:
        """Extrae TODOS los datos del calendario (Legacy/Completo)."""
        self.logger.info("Inicio del proceso de extracción COMPLETA de datos del calendario.")
        try:
            self._extract_categories_internal()
            self._extract_rooms_data()
            self._extract_date_range()

            result = CalendarData(
                categories=self.categories,
                reservation_data=self.rooms_data,
                date_range=self.date_range,
                extracted_at=datetime.now().isoformat(),
                day_id_to_date=self.day_id_to_date
            )
            return result.model_dump() if as_dict else result
        except Exception as e:
            self.logger.error(f"❌ Error crítico extrayendo datos del calendario: {e}", exc_info=True)
            raise

    def extract_reservation_details(self, html_content: str, reservation_id: str,
                                    as_dict: bool = False) -> Union[ReservationDetail, Dict[str, Any]]:
        """
        Extrae los detalles de la reserva desde el HTML de un folio (Modal/Página).
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Recolectar datos en un diccionario
        data = {'reservation_number': reservation_id}
        
        # 1. Información General (Basic Info)
        basic_info = self._extract_basic_info_from_detail(soup, reservation_id)
        data.update(basic_info)
        
        # 2. Alojamiento (Accommodation)
        accommodation = self._extract_accommodation_info(soup)
        data.update(accommodation)
        
        # 3. Listas detalladas
        guests = self._extract_guests_list(soup)
        services = self._extract_services_list(soup)
        payments = self._extract_payments_list(soup)
        tariffs = self._extract_daily_tariffs_list(soup)

        # Construir objeto usando desempaquetado
        detail = ReservationDetail(
            **data,
            guests=guests,
            services=services,
            payments=payments,
            daily_tariffs=tariffs,
            # raw_html=html_content # Opcional, desactivado por defecto para ahorrar memoria
        )
        
        return detail.model_dump() if as_dict else detail

    # --- Métodos de Extracción de Detalles ---

    def _extract_basic_info_from_detail(self, soup: BeautifulSoup, default_id: str) -> Dict[str, Any]:
        info = {}
        
        # Panel de Información Básica
        basic_panel = None
        for panel in soup.find_all('div', class_='panel'):
            heading = panel.find('div', class_='panel-heading')
            if heading and 'Información básica' in heading.get_text():
                basic_panel = panel
                break
        
        if basic_panel:
            body = basic_panel.find('div', class_='panel-body')
            if body:
                # Cliente
                client_div = body.find('div', class_='col-md-3')
                if client_div:
                    a_tag = client_div.find('a')
                    if a_tag: info['guest_name'] = a_tag.get_text(strip=True)
                
                for col in body.find_all('div', class_='col-md-3'):
                    text = col.get_text(" ", strip=True)
                    if 'Teléfono:' in text:
                        info['phone'] = text.replace('Teléfono:', '').strip()
                    elif 'Email:' in text:
                        info['email'] = text.replace('Email:', '').strip()
                    elif 'Fuente:' in text:
                        info['source'] = text.replace('Fuente:', '').strip()
                    elif 'Usuario:' in text:
                        info['user'] = text.replace('Usuario:', '').strip()

        # Notas
        notes_panel = None
        for panel in soup.find_all('div', class_='panel'):
            heading = panel.find('div', class_='panel-heading')
            if heading and 'Notas' in heading.get_text():
                notes_panel = panel
                break
        
        if notes_panel:
            body = notes_panel.find('div', class_='panel-body')
            if body:
                col = body.find('div', class_='col-md-12')
                if col:
                    text = col.get_text(" ", strip=True)
                    if 'Notas:' in text:
                        info['comments'] = text.replace('Notas:', '').strip()

        # Balance
        header_title = soup.find('div', class_='blocktitle')
        if header_title:
            balance_span = header_title.find_next_sibling('span')
            if not balance_span:
                 text = header_title.get_text()
                 if 'Saldo:' in text:
                     match = re.search(r'Saldo:\s*([+-]?\d+\.?\d*)', text)
                     if match: info['balance'] = float(match.group(1))
            elif balance_span:
                text = balance_span.get_text()
                match = re.search(r'Saldo:\s*([+-]?\d+\.?\d*)', text)
                if match: info['balance'] = float(match.group(1))

        return info

    def _extract_accommodation_info(self, soup: BeautifulSoup) -> Dict[str, Any]:
        info = {}
        acc_panel = None
        for panel in soup.find_all('div', class_='panel'):
            heading = panel.find('div', class_='panel-heading')
            if heading and 'Alojamiento' in heading.get_text():
                acc_panel = panel
                break
        
        if acc_panel:
            body = acc_panel.find('div', class_='panel-body')
            if body:
                cols = body.find_all('div', class_='col-md-2')
                for col in cols:
                    text = col.get_text(" ", strip=True)
                    if 'Período de estancia:' in text:
                        dates = re.findall(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}', text)
                        if len(dates) >= 1: info['check_in'] = dates[0]
                        if len(dates) >= 2: info['check_out'] = dates[1]
                    elif 'Habitación:' in text:
                        clean_text = text.replace('Habitación:', '').strip()
                        parts = clean_text.split()
                        if parts:
                            info['room'] = parts[0]
                            if len(parts) > 1:
                                info['room_type'] = " ".join(parts[1:])
                    elif 'Huéspedes:' in text:
                        match = re.search(r'(\d+)', text.replace('Huéspedes:', ''))
                        if match: info['guest_count'] = int(match.group(1))
                    elif 'Tarifa:' in text:
                        info['rate'] = text.replace('Tarifa:', '').strip()
        return info

    def _extract_guests_list(self, soup: BeautifulSoup) -> List[Guest]:
        guests = []
        # Implementar si se requiere lista detallada
        return guests

    def _extract_services_list(self, soup: BeautifulSoup) -> List[Service]:
        services = []
        # Implementar si se requiere lista detallada
        return services

    def _extract_payments_list(self, soup: BeautifulSoup) -> List[PaymentTransaction]:
        payments = []
        # Implementar si se requiere lista detallada
        return payments

    def _extract_daily_tariffs_list(self, soup: BeautifulSoup) -> List[DailyTariff]:
        tariffs = []
        # Implementar si se requiere lista detallada
        return tariffs

    # --- Métodos Internos del Calendario (Legacy) ---

    def _extract_room_id_mapping(self) -> Dict[str, List[str]]:
        if not self.soup: return {}
        
        mapping = {}
        desk_table = self.soup.find('table', id='desk')
        if not desk_table:
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

                room_number = f"Unknown_{room_id}"
                
                if room_id in self.room_id_to_category:
                    info = self.room_id_to_category[room_id]
                    room_number = info['room_number']

                # Construir datos para ReservationData
                res_data = {
                    'room_id': room_id,
                    'day_id': day_id,
                    'date': self._convert_day_id_to_date(day_id),
                    'cell_status': cell_status,
                    'room': reservation.get('room') or room_number,
                }
                # Mezclar con datos extraídos de la celda
                res_data.update(reservation)

                self.rooms_data.append(ReservationData(**res_data))

            except Exception as e:
                self.logger.error(f"❌ Error procesando celda (room_id={room_id}, day_id={day_id}): {e}")
                continue

    @staticmethod
    def _extract_reservation_from_cell(cell) -> Dict[str, Any]:
        data = {}
        res_block = cell.find(lambda tag: tag.name == 'div' and tag.get('resid'))
        if res_block:
            data['reservation_number'] = res_block.get('resid')

            status_val = res_block.get('status')
            if status_val:
                try:
                    data['reservation_status'] = int(status_val)
                except (ValueError, TypeError):
                    data['reservation_status'] = None

            tooltip_html = res_block.get('data-title', '')
            if tooltip_html:
                decoded_html = html.unescape(tooltip_html)

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
        return {}
