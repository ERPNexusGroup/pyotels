# src/pyotels/data_processor.py

import html
import re
from datetime import datetime
from typing import List, Dict, Any, Union, Optional, Final

from bs4 import BeautifulSoup

from pyotels.core.enums import StatusReservation
from pyotels.core.models import (
    RoomCategory, ReservationData, CalendarData, ReservationModalDetail,
    CalendarReservation, CalendarCategories, Guest, Service, PaymentTransaction,
    DailyTariff, AccommodationInfo, CarInfo, NoteInfo, ChangeLog
)
from pyotels.utils.dev import save_html_debug
from pyotels.utils.logger import get_logger
from pyotels.utils.normalizations import normalize_float, normalize_date
from pyotels.exceptions import ParsingError


class OtelsProcessadorData:
    """Procesa datos estructurados del calendario HTML de OtelMS."""

    def __init__(self, html_content: Union[str, Dict[str, str], None] = None, include_empty_cells: bool = False):
        self.logger = get_logger(classname="OtelsProcessadorData")
        self.logger.info("Inicializando OtelsProcessadorData...")
        self.include_empty_cells = include_empty_cells
        self._load_content(html_content)

    @property
    def html_content(self) -> Union[BeautifulSoup, Dict[str, str]]:
        """
        Propiedad para obtener o actualizar el contenido HTML (o modales).
        Al setear un nuevo valor, se reinicia el estado del procesador.
        """
        return self.modals_data if self.modals_data else self.soup

    @html_content.setter
    def html_content(self, content: Union[str, Dict[str, str]]):
        self.logger.info("Actualizando contenido HTML vía propiedad...")
        self._load_content(content)

    def _load_content(self, content: Union[str, Dict[str, str], None]):
        """Carga el contenido HTML/dict y reinicia el estado del procesador."""
        self.modals_data = {}
        self.soup = None

        if content is None:
            pass
        elif isinstance(content, dict):
            self.modals_data = content
            self.soup = BeautifulSoup("", 'html.parser')
            self.logger.debug(f"Contenido actualizado con {len(self.modals_data)} modales.")
        else:
            self.soup = BeautifulSoup(content, 'html.parser')
            self.logger.debug(f"Contenido HTML actualizado. Longitud: {len(content)} caracteres.")

        # Reiniciar estado interno
        self.categories = []
        self.rooms_data = []
        self.date_range = {}
        self.room_id_to_category = {}
        self.day_id_to_date = {}

        # if self.soup and self.soup.text:
        #     self._build_date_mapping()

    def extract_categories(self, as_dict: bool = False) -> Union[CalendarCategories, Dict[str, Any]]:
        """Extrae solo las categorías y habitaciones."""
        self.logger.info("Extrayendo categorías...")
        try:
            self._extract_categories_internal()

            result = CalendarCategories(
                categories=self.categories
            )
            return result.model_dump() if as_dict else result
        except Exception as e:
            raise ParsingError(f"Error al extraer categorías: {e}")

    def extract_reservations(self, as_dict: bool = False) -> Union[CalendarReservation, Dict[str, Any]]:
        """Extrae solo la grilla de reservaciones (celdas)."""
        self.logger.info("Extrayendo grilla de reservaciones...")

        try:
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
        except Exception as e:
            raise ParsingError(f"Error al extraer reservaciones: {e}")

    def extract_all_reservation_modals(self, as_dict: bool = False) -> Union[
        List[ReservationModalDetail], List[Dict[str, Any]]]:
        """
        Procesa todos los modales almacenados y retorna una lista de ReservationDetail o Dicts.
        """
        self.logger.info(f"Procesando {len(self.modals_data)} modales de reserva...")

        details = []

        for res_id, modal_html in self.modals_data.items():
            # self.logger.debug(f"Procesando modal para reserva {res_id}-> {modal_html}")
            try:
                # Se pasa 'id' como keyword argument para evitar conflicto con 'as_dict'
                save_html_debug(modal_html, f'modal_{res_id}.html')
                detail = self._extract_reservation_modal(modal_html, as_dict=as_dict, id=res_id)
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
            raise ParsingError(f"Error crítico extrayendo datos del calendario: {e}")

    @staticmethod
    def normalize_balance(balance_raw: Optional[str], total_raw: Optional[str],
                          paid_raw: Optional[str]) -> Optional[float]:

        balance = normalize_float(balance_raw)
        if balance is not None:
            return balance

        total = normalize_float(total_raw)
        paid = normalize_float(paid_raw)

        if total is not None and paid is not None:
            return total - paid

        return None

    def _extract_reservation_modal(self, html_content: str, as_dict: bool = False, **kwargs) -> Union[
        ReservationModalDetail, Dict[str, Any]]:
        """
        Extrae información del modal de reserva (HTML parcial) y devuelve un ReservationModalDetail.
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            extracted = {}
            FIELDS_MAP: Final[dict] = {
                "Huésped": "guest_name",
                "Fuente": "source",
                "Llegada": "check_in",
                "Salida": "check_out",
                "Teléfono": "phone",
                "e-mail": "email",
                "Notas": "comments",
                "Usuario": "user",
                "Total": "total",
                "Pagado": "paid",
                "Importe de los servicios por el día actual": "balance",
                'Número de huéspedes': 'guest_count',
                'Tipo de habitación': 'room_type',
                'Habitación': 'room',
                'Tarifa': 'rate',
            }

            # 1. Reservation Number
            status = None
            reservation_number = None
            h2 = soup.find('h2', class_='nameofgroup') or soup.find('h2')
            if h2:
                text = h2.get_text(strip=True)
                # self.logger.debug(f"text: {text}")
                match = re.findall(r'(?:Reserva|Salida|Alojamiento)|\d+', text)
                # self.logger.debug(f"match: {match}")
                if match and len(match) > 1:
                    status = StatusReservation.from_text(match[0].strip())
                    # self.logger.debug(f"status: {status}")
                    reservation_number = str(match[1])
                    # self.logger.debug(f"reservation_number {type(reservation_number)}: {reservation_number}")

            # 2. Balance
            balance_div = soup.find('div', class_='balans')
            balance: Optional[float] = None
            if balance_div:
                balance_text = balance_div.get_text(strip=True).replace('Saldo:', '').strip()
                try:
                    balance = float(balance_text.replace(',', ''))
                except (ValueError, TypeError):
                    pass

            # 3. Mapeo de campos clave-valor
            data_map = {}

            for label in soup.find_all('span', class_='incolor'):
                key = label.get_text(strip=True)
                parent = label.find_parent('div')
                if not parent:
                    continue

                value_div = parent.find_next_sibling('div', class_='text-right')

                if value_div:
                    if value_div.find('img') and 'dc_logo/dc_logo_1.png' in value_div.find('img').get('src', ''):
                        # self.logger.debug(f"key: {key} \t source: {value_div.find('img')}")
                        data_map[key] = "booking"
                    else:
                        # self.logger.debug(f"key: {key} \t value: {" ".join(value_div.stripped_strings)}")
                        data_map[key] = " ".join(value_div.stripped_strings)

            extracted["fields"] = data_map
            # self.logger.debug(f"data_map: {data_map}")

            mapped = {}

            for label, value in data_map.items():
                field = FIELDS_MAP.get(label)
                if field:
                    # self.logger.debug(f"key: {field} \t value: {value}")
                    mapped[field] = value
                else:
                    # self.logger.debug(f"Exclude key: {label} \t value: {value}")
                    continue
            guest_list = []

            guest_label = soup.find('span', class_='incolor', string='Lista de huéspedes')
            if guest_label:
                parent = guest_label.find_parent('div')
                if parent:
                    guest_div = parent.find_next_sibling('div', class_='text-right')
                    if guest_div:
                        guest_list = list(guest_div.stripped_strings)

            # self.logger.debug(f"guest_list: {guest_list}")

            mapped["guest_name"] = data_map['Huésped'] if 'Huésped' in data_map else guest_list[0] if guest_list else None
            mapped["guest_count"] = data_map['Número de huéspedes'].split(' ')[
                0] if 'Número de huéspedes' in data_map else len(guest_list) or None

            balance_div = soup.find('div', class_='balans')
            if balance_div:
                mapped["balance"] = balance_div.get_text(strip=True)

            for key, value in data_map.items():
                if "habitación" in key.lower():
                    mapped["room"] = value

                if "tipo" in key.lower():
                    mapped["room_type"] = value

                if "cread" in key.lower():
                    mapped["created_at"] = value

            normalized = dict()

            normalized["balance"] = self.normalize_balance(
                mapped.get("balance") if mapped.get("balance") else balance,
                mapped.get("total"),
                mapped.get("paid")
            )

            normalized["total"] = normalize_float(mapped.get("total"))
            normalized["paid"] = normalize_float(mapped.get("paid"))
            normalized["rate"] = normalize_float(mapped.get("rate"))

            normalized["check_in"] = normalize_date(mapped.get("check_in"))
            normalized["check_out"] = normalize_date(mapped.get("check_out"))
            normalized["created_at"] = normalize_date(mapped.get("created_at"))

            # --- Construcción del objeto ---
            detail = ReservationModalDetail(
                reservation_number=reservation_number if reservation_number else kwargs.get('id'),
                status=status,
                guest_name=mapped.get("guest_name"),
                check_in=normalized.get("check_in"),
                check_out=normalized.get("check_out"),
                created_at=normalized.get("created_at"),
                guest_count=mapped.get("guest_count"),
                balance=normalized.get("balance"),
                total=normalized.get("total"),
                paid=normalized.get("paid"),
                rate=normalized.get("rate"),
                phone=mapped.get("phone"),
                email=mapped.get("email"),
                user=mapped.get("user"),
                comments=mapped.get("comments"),
                room_type=mapped.get("room_type"),
                room=mapped.get("room"),
                source=mapped.get("source"),
            )

            return detail.model_dump(exclude_none=True) if as_dict else detail
        except Exception as e:
            raise ParsingError(f"Error parseando modal de reserva: {e}")

    def extract_guest_id(self, html_content: Optional[str] = None) -> Optional[int]:
        """
        Extrae el ID del huésped desde el HTML de información básica.
        Busca un enlace del tipo /reservation_c2/foliogroup/0
        """
        self.logger.debug(f"Method: extract_guest_id")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug(f"soup: {soup}")
            link = soup.find('a', href=re.compile(r'/guestfolio/(\d+)'))
            # self.logger.debug(f"link: {link}")
            if link:
                match = re.search(r'/guestfolio/(\d+)', link.get('href'))
                if match:
                    return int(match.group(1))
            return None
        except Exception as e:
            self.logger.error(f"Error extrayendo ID de huésped: {e}")
            return None

    def extract_guest_details(self, html_content: Optional[str] = None, as_dict: bool = False) -> Guest:
        """
        Extrae los detalles completos del huésped desde el HTML de su tarjeta.
        """
        self.logger.debug(f"Method: extract_guest_details")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug(f"soup: {soup}")
            guest_data = {}

            # Extraer ID del header si existe
            header_time = soup.find('span', class_='header-time')
            if header_time:
                text = header_time.get_text(" ", strip=True)
                match = re.search(r'ID:\s*(\d+)', text)
                if match:
                    guest_data['id'] = match.group(1)

            # Buscar el panel de "Tarjeta de huésped"
            panel = None
            for p in soup.find_all('div', class_='panel'):
                heading = p.find('div', class_='panel-heading')
                if heading and 'Tarjeta de huésped' in heading.get_text():
                    panel = p
                    break

            if not panel:
                # Fallback: buscar por ID de widget si es consistente
                panel = soup.find('div', {'data-widget': lambda x: x and 'wiget1' in x})

            if panel:
                body = panel.find('div', class_='panel-body')
                if body:
                    # Buscar dentro de folio1 si existe, o directamente en body
                    container = body.find('div', class_='folio1') or body
                    cols = container.find_all('div', class_='col-md-2')

                    for col in cols:
                        b_tag = col.find('b')
                        if not b_tag:
                            continue

                        # Extraer la clave del tag <b>
                        key_text = b_tag.get_text(strip=True).rstrip(':')
                        key = key_text.lower()

                        # Extraer el valor: iterar sobre los hermanos siguientes al tag <b>
                        val = ""
                        curr = b_tag.next_sibling
                        while curr:
                            if isinstance(curr, str):
                                val += curr
                            elif curr.name == 'br':
                                pass
                            else:
                                val += curr.get_text(" ", strip=True)
                            curr = curr.next_sibling

                        val = val.strip()

                        if 'nombre' == key:
                            guest_data['first_name'] = val
                        elif 'apellido' == key:
                            guest_data['last_name'] = val
                        elif 'segundo nombre' == key:
                            guest_data['middle_name'] = val
                        elif 'género' == key:
                            guest_data['gender'] = val
                        elif 'fecha de nacimiento' == key:
                            guest_data['dob'] = val
                        elif 'teléfono' == key:
                            guest_data['phone'] = val
                        elif 'email' == key:
                            guest_data['email'] = val
                        elif 'lenguaje' in key:
                            guest_data['language'] = val
                        elif 'país' == key:
                            guest_data['country'] = val
                        elif 'ciudad' == key:
                            guest_data['city'] = val
                        elif 'calle' == key:
                            guest_data['street'] = val
                        elif 'casa' == key:
                            guest_data['house'] = val
                        elif 'código postal' == key:
                            guest_data['zip_code'] = val
                        elif 'tipo de documento' == key:
                            guest_data['document_type'] = val
                        elif 'documento número' == key:
                            guest_data['document_number'] = val
                        elif 'número de documento' == key:
                            guest_data['document_number'] = val
                        elif 'fecha de emisión' == key:
                            guest_data['issue_date'] = val
                        elif 'validez' == key:
                            guest_data['expiration_date'] = val
                        elif 'emitido por' == key:
                            guest_data['issued_by'] = val

            # Construir nombre completo si es posible
            parts = [guest_data.get('first_name'), guest_data.get('middle_name'), guest_data.get('last_name')]
            full_name = " ".join([p for p in parts if p])
            if full_name:
                guest_data['name'] = full_name

            return Guest(**guest_data).model_dump() if as_dict else Guest(**guest_data)
        except Exception as e:
            raise ParsingError(f"Error parseando detalles de huésped: {e}")

    # --- Métodos de Extracción de Detalles ---

    def extract_basic_info_from_detail(self, html_content: Optional[str] = None) -> Dict[str, Any]:
        self.logger.debug(f"Method: extract_basic_info_from_detail")
        try:
            info = {}

            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug(f"soup: {soup}")

            # Buscar el panel de Información básica
            panel = soup.find('div', id='anchors_main_information')
            if not panel:
                # Fallback si no tiene ID
                for p in soup.find_all('div', class_='panel'):
                    h2 = p.find('h2')
                    if h2 and 'Información básica' in h2.get_text():
                        panel = p
                        break

            if panel:
                body = panel.find('div', class_='panel-body')
                if body:
                    cols = body.find_all('div', class_='col-md-3')
                    for col in cols:
                        b_tag = col.find('b')
                        if not b_tag: continue

                        key = b_tag.get_text(strip=True).lower().replace(':', '')

                        # Extraer valor (texto después de <b>)
                        val = ""
                        curr = b_tag.next_sibling
                        while curr:
                            if isinstance(curr, str):
                                val += curr
                            elif curr.name == 'a':
                                val += curr.get_text(" ", strip=True)
                            elif curr.name == 'br':
                                pass
                            else:
                                # Ignorar iconos de edición
                                if 'fa-edit' not in str(curr):
                                    val += curr.get_text(" ", strip=True)
                            curr = curr.next_sibling

                        val = val.strip()

                        if 'cliente' in key:
                            info['guest_name'] = val
                        elif 'teléfono' in key:
                            info['phone'] = val
                        elif 'email' in key:
                            info['email'] = val
                        elif 'pagador' in key:
                            info['payer'] = val
                        elif 'entidad legal' in key:
                            info['legal_entity'] = val
                        elif 'fuente' in key:
                            info['source'] = val
                        elif 'usuario' in key:
                            info['user'] = val

            return info
        except Exception as e:
            self.logger.error(f"Error extrayendo info básica: {e}")
            return {}

    def _extract_accommodation_info(self, soup: BeautifulSoup) -> Optional[AccommodationInfo]:
        self.logger.debug(f"Method: _extract_accommodation_info")

        info = {}
        panel = soup.find('div', id='anchors_accommodation')

        if not panel:
            for p in soup.find_all('div', class_='panel'):
                h2 = p.find('h2')
                if h2 and 'Alojamiento' in h2.get_text():
                    panel = p
                    break

        if panel:
            body = panel.find('div', class_='panel-body')
            if body:
                cols = body.find_all('div', class_='col-md-2')
                for col in cols:
                    b_tag = col.find('b')
                    if not b_tag: continue

                    key = b_tag.get_text(strip=True).lower().replace(':', '')
                    self.logger.debug(f"Key: {key}")

                    # Extraer valor
                    val_parts = []
                    curr = b_tag.next_sibling
                    while curr:
                        if isinstance(curr, str):
                            txt = curr.strip()
                            if txt: val_parts.append(txt)
                        elif curr.name == 'br':
                            pass
                        elif curr.name == 'span':
                            # Caso especial Huéspedes con iconos
                            txt = curr.get_text(strip=True)
                            if txt: val_parts.append(txt)
                        else:
                            # Ignorar iconos de edición
                            if 'fa-edit' not in str(curr) and 'd0' not in curr.get('class', []):
                                txt = curr.get_text(" ", strip=True)
                                if txt: val_parts.append(txt)
                        curr = curr.next_sibling

                    val = " ".join(val_parts).strip()

                    if 'período de estancia' in key:
                        dates = re.findall(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}', val)
                        if len(dates) >= 1: info['check_in'], info['check_in_hour'] = dates[0].split(" ")
                        if len(dates) >= 2: info['check_out'], info['check_out_hour'] = dates[1].split(" ")
                    elif 'noches' in key:
                        try:
                            info['nights'] = int(val)
                        except:
                            pass
                    elif 'habitación' in key:
                        # Separar numero y tipo si es posible
                        # Ejemplo: "201 Matrimonial"
                        parts = val.split()
                        if parts:
                            info['room_number'] = parts[0]
                            if len(parts) > 1:
                                info['room_type'] = " ".join(parts[1:])
                    elif 'huéspedes' in key:
                        # Sumar números encontrados
                        nums = re.findall(r'\d+', val)
                        total = sum(int(n) for n in nums)
                        info['guest_count'] = total
                    elif 'tarificación por categoría' in key:
                        info['rate_category'] = val
                    elif 'tarifa' in key:
                        info['rate_name'] = val
                    elif 'precio por alojamiento' in key:
                        info['price_type'] = val
                    elif 'descuento' in key:
                        info['discount'] = val
                    elif 'razón para el descuento' in key:
                        info['discount_reason'] = val

        return AccommodationInfo(**info) if info else None

    # @staticmethod
    @staticmethod
    def extract_accommodation_details(html_content: str, as_dict: bool = False) -> Union[
        AccommodationInfo, Dict[str, Any], None]:
        """
        Extrae información detallada del alojamiento desde el modal de edición (HTML con inputs).
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            info = {}

            def get_val(selector: str) -> Optional[str]:
                el = soup.select_one(selector)
                return el.get('value') if el else None

            def get_sel_val(selector: str) -> Optional[str]:
                el = soup.select_one(f"{selector} option[selected]")
                return el.get('value') if el else None

            def get_sel_text(selector: str) -> Optional[str]:
                el = soup.select_one(f"{selector} option[selected]")
                return el.get_text(strip=True) if el else None

            # Fechas
            info['check_in'] = get_val('#datein')
            info['check_in_hour'] = get_sel_val('#checkintime')
            info['check_out'] = get_val('#dateout')
            info['check_out_hour'] = get_sel_val('#checkouttime')

            # Duración
            try:
                info['nights'] = int(get_val('#duration') or 0)
            except ValueError:
                pass

            # Habitación
            info['room_number'] = get_sel_text('#room_id')
            info['room_type'] = get_sel_text('#category')

            # Huéspedes
            try:
                adults = int(get_sel_val('#adults') or 0)
                baby1 = int(get_sel_val('#baby_places') or 0)
                baby2 = int(get_sel_val('#babyplace2') or 0)
                info['adults_count'] = adults
                info['children_count'] = baby1
                info['babies_count'] = baby2
            except ValueError:
                pass

            # Tarifa y Categoría
            info['rate_name'] = get_sel_text('#price_type').split(' ')[0]

            rate_cat = get_sel_text('#ud_price_category')
            if rate_cat and rate_cat != '---':
                info['rate_category'] = rate_cat

            # Tipo de precio (Por tarifa, Fijo, Diario)
            price_mode = get_sel_val('#ny_ismanual')
            price_modes = {'0': 'Por tarifa', '1': 'Fijo', '2': 'Diario'}
            if price_mode in price_modes:
                info['price_type'] = price_modes[price_mode]

            # Descuento
            info['discount'] = get_val('#discount')

            # Total e Impuestos
            el_total = soup.select_one('#FO_total')
            if el_total:
                info['total_price'] = el_total.get_text(strip=True)

            el_taxes = soup.select_one('#TF_total')
            if el_taxes:
                info['taxes_surcharges'] = el_taxes.get_text(strip=True)

            # Filtrar None
            info = {k: v for k, v in info.items() if v is not None}

            if as_dict:
                return info

            return AccommodationInfo(**info)
        except Exception as e:
            raise ParsingError(f"Error parseando detalles de alojamiento: {e}")

    def extract_guests_list(self, html_content: Optional[str] = None) -> List[Guest]:
        self.logger.debug(f"Method: extract_guests_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            guests = []

            # Intentar encontrar la tabla en varios contenedores posibles
            table = None

            # 1. Panel de residentes (común en la vista de detalles)
            panel = soup.find('div', id='anchors_info_residents')
            if panel:
                table = panel.find('table')

            # 2. Formulario de impresión (guest_template_print) - Caso del HTML proporcionado
            if not table:
                form = soup.find('form', id='guest_template_print')
                if form:
                    table = form.find('table', class_='add-line-table')

            # 3. Búsqueda genérica por clase
            if not table:
                table = soup.find('table', class_='add-line-table')

            if table:
                rows = []
                # IMPORTANTE: La tabla puede tener múltiples <tbody> (uno por huésped).
                # Usamos find_all('tbody') para obtener todos, ya que find() solo devuelve el primero.
                tbodies = table.find_all('tbody')
                if tbodies:
                    for tbody in tbodies:
                        rows.extend(tbody.find_all('tr'))
                else:
                    # Fallback si no hay tbodies
                    rows = table.find_all('tr')

                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) < 4: continue

                    g = {}
                    # Nombre (Link)
                    name_link = cols[0].find('a')
                    if name_link:
                        g['name'] = name_link.get_text(strip=True)
                        href = name_link.get('href')
                        match = re.search(r'/guestfolio/(\d+)', href)
                        if match: g['id'] = match.group(1)
                    else:
                        g['name'] = cols[0].get_text(strip=True)

                    # Email
                    g['email'] = cols[2].get_text(strip=True)

                    # Fecha nacimiento
                    g['dob'] = cols[3].get_text(strip=True)

                    guests.append(Guest(**g))
            return guests
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de huéspedes: {e}")
            return []

    def extract_services_list(self, html_content: Optional[str] = None) -> List[Service]:
        self.logger.debug(f"Method: extract_services_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')

            services = []

            # Estrategia 1: Buscar panel por título
            target_panel = None
            for p in soup.find_all('div', class_='panel'):
                h2 = p.find('h2')
                if h2 and 'Servicios' in h2.get_text():
                    target_panel = p
                    break

            table = None
            if target_panel:
                table = target_panel.find('table', class_='add-line-table') or target_panel.find('table')

            # Estrategia 2: Si no hay panel o tabla en panel, buscar tabla por encabezado característico
            if not table:
                for t in soup.find_all('table', class_='add-line-table'):
                    if t.find('th', string=re.compile(r'Fecha y hora')):
                        table = t
                        break

            if table:
                rows = []
                tbodies = table.find_all('tbody')
                if tbodies:
                    for tbody in tbodies:
                        rows.extend(tbody.find_all('tr'))
                else:
                    rows = table.find_all('tr')

                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) < 8: continue

                    # Evitar filas de totales o vacías
                    # La columna 1 es el ID (№), si está vacía suele ser fila de totales o separador
                    if not cols[1].get_text(strip=True):
                        continue

                    s = {}
                    s['date'] = cols[0].get_text(strip=True)
                    s['id'] = cols[1].get_text(strip=True)
                    s['title'] = cols[2].get_text(strip=True)
                    s['legal_entity'] = cols[3].get_text(strip=True)
                    s['description'] = cols[4].get_text(strip=True)
                    s['number'] = cols[5].get_text(strip=True)

                    try:
                        s['price'] = float(cols[6].get_text(strip=True).replace(',', ''))
                    except:
                        s['price'] = 0.0

                    try:
                        s['quantity'] = float(cols[7].get_text(strip=True).replace(',', ''))
                    except:
                        s['quantity'] = 0.0

                    services.append(Service(**s))
            return services
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de servicios: {e}")
            return []

    def extract_payments_list(self, html_content: Optional[str] = None) -> List[PaymentTransaction]:
        self.logger.debug(f"Method: extract_payments_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug(f"soup: {soup}")

            payments = []

            panel = soup.find('div', id='anchors_list_payments')
            # Nota: En el HTML proporcionado hay dos paneles con id="anchors_list_payments".
            # El primero es "Lista de pagos", el segundo "Lista de tarjetas de pago".
            # BeautifulSoup find encontrará el primero.

            if panel:
                h2 = panel.find('h2')
                if h2 and 'Lista de pagos' in h2.get_text():
                    table = panel.find('table')
                    if table:
                        tbody = table.find('tbody')
                        if tbody:
                            rows = tbody.find_all('tr')
                            for row in rows:
                                cols = row.find_all('td')
                                if len(cols) < 8: continue

                                p = {}
                                p['date'] = cols[0].get_text(strip=True)
                                p['created_at'] = cols[1].get_text(strip=True)
                                p['number'] = cols[2].get_text(strip=True)
                                p['legal_entity'] = cols[3].get_text(strip=True)
                                p['description'] = cols[4].get_text(strip=True)
                                p['type'] = cols[5].get_text(strip=True)

                                try:
                                    p['amount'] = float(cols[6].get_text(strip=True).replace(',', ''))
                                except:
                                    p['amount'] = 0.0

                                p['method'] = cols[7].get_text(strip=True)

                                if len(cols) > 8: p['vpos_card_number'] = cols[8].get_text(strip=True)
                                if len(cols) > 9: p['vpos_status'] = cols[9].get_text(strip=True)
                                if len(cols) > 10: p['fiscal_check'] = cols[10].get_text(strip=True)

                                payments.append(PaymentTransaction(**p))

            return payments
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de pagos: {e}")
            return []

    def extract_cars_list(self, html_content: Optional[str] = None) -> List[CarInfo]:
        self.logger.debug(f"Method: extract_cars_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug(f"soup: {soup}")

            cars = []
            # Buscar panel Coche
            panels = soup.find_all('div', class_='panel')
            target_panel = None
            for p in panels:
                h2 = p.find('h2')
                if h2 and 'Coche' in h2.get_text():
                    target_panel = p
                    break

            if target_panel:
                table = target_panel.find('table')
                if table:
                    tbody = table.find('tbody')
                    if tbody:
                        rows = tbody.find_all('tr')
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) < 3: continue

                            c = {}
                            c['brand'] = cols[0].get_text(strip=True)
                            c['color'] = cols[1].get_text(strip=True)
                            c['plate'] = cols[2].get_text(strip=True)
                            cars.append(CarInfo(**c))
            return cars
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de coches: {e}")
            return []

    def extract_notes_list(self, html_content: Optional[str] = None) -> List[NoteInfo]:
        self.logger.debug("Method: _extract_notes_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug("soup: {soup}")

            notes = []
            # Buscar panel Notas
            panels = soup.find_all('div', class_='panel')
            target_panel = None
            for p in panels:
                h2 = p.find('h2')
                if h2 and 'Notas' in h2.get_text():
                    target_panel = p
                    break

            if target_panel:
                table = target_panel.find('table')
                if table:
                    tbody = table.find('tbody')
                    if tbody:
                        rows = tbody.find_all('tr')
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) < 3: continue

                            n = {}
                            n['date'] = cols[0].get_text(strip=True)
                            n['user'] = cols[1].get_text(strip=True)
                            n['note'] = cols[2].get_text(strip=True)
                            notes.append(NoteInfo(**n))
            return notes
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de notas: {e}")
            return []

    def extract_daily_tariffs_list(self, html_content: Optional[str] = None) -> List[DailyTariff]:
        self.logger.debug("Method: _extract_notes_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug("soup: {soup}")

            tariffs = []
            panel = soup.find('div', id='anchors_billing_days')

            if panel:
                table = panel.find('table')
                if table:
                    tbody = table.find('tbody')
                    if tbody:
                        rows = tbody.find_all('tr')
                        for row in rows:
                            # Ignorar encabezados
                            if row.find('th'): continue

                            cols = row.find_all('td')
                            if len(cols) < 3: continue

                            t = {}
                            t['date'] = cols[0].get_text(strip=True)
                            t['description'] = cols[1].get_text(strip=True)
                            try:
                                t['price'] = float(cols[2].get_text(strip=True).replace(',', ''))
                            except:
                                t['price'] = 0.0

                            tariffs.append(DailyTariff(**t))
            return tariffs
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de tarifas: {e}")
            return []

    def extract_change_log_list(self, html_content: Optional[str] = None) -> List[ChangeLog]:
        self.logger.debug("Method: _extract_notes_list")
        try:
            soup = self.soup if not html_content else BeautifulSoup(html_content, 'html.parser')
            # self.logger.debug("soup: {soup}")

            logs = []
            panel = soup.find('div', id='anchors_log')

            if panel:
                table = panel.find('table')
                if table:
                    tbody = table.find('tbody')
                    if tbody:
                        rows = tbody.find_all('tr')
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) < 7: continue

                            l = {}
                            l['date'] = cols[0].get_text(strip=True)
                            l['number'] = cols[1].get_text(strip=True)
                            l['user'] = cols[2].get_text(strip=True)
                            l['type'] = cols[3].get_text(strip=True)
                            l['action'] = cols[4].get_text(strip=True)
                            l['quantity'] = cols[5].get_text(strip=True)
                            l['description'] = cols[6].get_text(strip=True)

                            logs.append(ChangeLog(**l))
            return logs
        except Exception as e:
            self.logger.error(f"Error extrayendo lista de logs: {e}")
            return []

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
                    'cell_status': cell_status,
                    'room': reservation.get('room') or room_number,
                    'reservation_number': reservation.get('reservation_number'),
                    'guest_name': reservation.get('guest_name'),
                    'check_in': reservation.get('check_in'),
                    'check_out': reservation.get('check_out'),
                    'created_at': reservation.get('created_at'),
                    'guest_count': reservation.get('guest_count'),
                    'balance': reservation.get('balance'),
                    'phone': reservation.get('phone'),
                    'email': reservation.get('email'),
                    'user': reservation.get('user'),
                    'comments': reservation.get('comments'),
                    'reservation_status': reservation.get('reservation_status'),
                }

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

    # def _build_date_mapping(self):
    #     pass

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

    @staticmethod
    def _convert_day_id_to_date(day_id: str) -> str:
        try:
            return datetime.fromtimestamp(int(day_id) * 60 * 60 * 24)
        except Exception as e:
            return f"unknown_date_{day_id}"

    @staticmethod
    def _extract_general_reservation_info(soup: BeautifulSoup) -> Dict[str, Any]:
        return {}
