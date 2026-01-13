import html
from src.pyotels.logger import logger
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

from .models import RoomCategory, ReservationData, CalendarData, ReservationDetail, Guest, Service, Payment, Note, \
    DailyTariff, ChangeLog
from .settings import config


class OtelsExtractor:
    """Extrae datos estructurados del calendario HTML de OtelMS."""

    def __init__(self, html_content: str, include_empty_cells: bool = False):
        logger.info("Inicializando OtelsExtractor...")
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.day_id_to_date = {}
        self.categories = []
        self.rooms_data = []
        self.date_range = {}
        self.include_empty_cells = include_empty_cells
        self.room_id_to_category = {}
        logger.debug(f"HTML cargado. Longitud: {len(html_content)} caracteres. Include empty cells: {include_empty_cells}")

    def extract_calendar_data(self) -> CalendarData:
        """Extrae todos los datos del calendario en el orden correcto."""
        logger.info("Inicio del proceso de extracción de datos del calendario.")
        try:
            # 1. Primero construir el mapeo day_id → fecha
            self._build_date_mapping()

            # 2. Extraer categorías y habitaciones
            self._extract_categories()
            logger.info(f"✅ Categorías extraídas: {len(self.categories)}")
            logger.debug(f"Detalle de categorías: {[c.name for c in self.categories]}")

            # 3. Extraer datos de habitaciones con fechas correctas
            self._extract_rooms_data()
            logger.info(f"✅ Datos de habitaciones extraídos: {len(self.rooms_data)} celdas procesadas.")

            # 4. Extraer rango de fechas
            self._extract_date_range()
            logger.info(f"✅ Rango de fechas extraído: {self.date_range}")

            return CalendarData(
                categories=self.categories,
                reservation_data=self.rooms_data,
                date_range=self.date_range,
                extracted_at=datetime.now().isoformat()
            )
        except Exception as e:
            logger.error(f"❌ Error crítico extrayendo datos del calendario: {e}", exc_info=True)
            raise

    def extract_reservation_details(self, html_content: str, reservation_id: str, include_raw_html: bool = False) -> ReservationDetail:
        """
        Extrae los detalles de la reserva desde el HTML.
        :param html_content: Contenido HTML de la página de detalles.
        :param reservation_id: ID de la reserva.
        :param include_raw_html: Si es True, incluye el HTML crudo en el objeto de retorno.
        """
        logger.info(f"Extrayendo detalles para la reserva ID: {reservation_id}")
        logger.debug(f"Longitud del HTML de detalles: {len(html_content)}")
        
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Extract Guests
        guests = []
        guest_rows = soup.select('#anchors_info_residents table tbody tr')
        for row in guest_rows:
            cols = row.find_all('td')
            if len(cols) > 2:
                name = cols[0].get_text(strip=True)
                email = cols[2].get_text(strip=True)
                guests.append(Guest(
                    name=name,
                    email=email if "@" in email else None
                ))
        logger.info(f"Huéspedes encontrados: {len(guests)}")
        logger.debug(f"Lista de huéspedes: {guests}")

        # 2. Extract Services
        services = []
        total_price = 0.0
        services_panel = soup.find('div', id='anchors_services')
        if services_panel and "Servicios" in services_panel.get_text():
            service_rows = services_panel.select('table tbody tr')
            for row in service_rows:
                cols = row.find_all('td')
                if len(cols) >= 8:
                    try:
                        date = cols[0].get_text(strip=True)
                        title = cols[2].get_text(strip=True)
                        desc = cols[4].get_text(strip=True)
                        qty = int(cols[5].get_text(strip=True) or 0)
                        price_str = cols[6].get_text(strip=True).replace(',', '.')
                        total_str = cols[7].get_text(strip=True).replace(',', '.')
                        price = float(price_str) if price_str else 0.0
                        total_item = float(total_str) if total_str else 0.0

                        services.append(Service(
                            date=date,
                            title=title,
                            description=desc,
                            quantity=qty,
                            price=price,
                            total=total_item
                        ))
                    except Exception as e:
                        logger.warning(f"Error parsing service row: {e}")

            # Extract Footer Total
            footer_total = services_panel.select_one('tfoot th:nth-last-child(2)')
            if footer_total:
                try:
                    total_price = float(footer_total.get_text(strip=True).replace(',', '.'))
                except:
                    pass
        logger.info(f"Servicios encontrados: {len(services)}. Precio total calculado: {total_price}")

        # 3. Extract Payments
        payments = []
        payments_panel = soup.find('div', id='anchors_list_payments')
        if payments_panel:
            payment_rows = payments_panel.select('table tbody tr')
            for row in payment_rows:
                cols = row.find_all('td')
                if len(cols) >= 7:
                    try:
                        date = cols[0].get_text(strip=True)
                        amount_str = cols[6].get_text(strip=True).replace(',', '.')
                        amount = float(amount_str) if amount_str else 0.0
                        pay_type = cols[5].get_text(strip=True)
                        method = cols[7].get_text(strip=True) if len(cols) > 7 else ""

                        payments.append(Payment(
                            date=date,
                            amount=amount,
                            type=pay_type,
                            method=method
                        ))
                    except Exception as e:
                        logger.warning(f"Error parsing payment row: {e}")
        logger.info(f"Pagos encontrados: {len(payments)}")

        # 4. Extract Channel Info / Meta
        channel_info = {}
        channel_div = soup.find('div', id='anchors_info_dc_channel')
        if channel_div:
            for b_tag in channel_div.find_all('b'):
                label = b_tag.get_text(strip=True).lower()
                value = ""
                curr = b_tag.next_sibling
                while curr:
                    if isinstance(curr, str) and curr.strip():
                        value += curr.strip()
                    elif curr.name == 'br':
                        pass
                    elif curr.name == 'a':
                        value += curr.get_text(strip=True)
                    else:
                        value += curr.get_text(strip=True)
                    curr = curr.next_sibling

                channel_info[label] = value.strip()
        logger.debug(f"Channel Info extraído: {channel_info}")

        # Update balance calc
        total_payments = sum(p.amount for p in payments)
        balance = total_price - total_payments

        # 0. Basic Info
        basic_info = {}
        main_panels = soup.select('.panel-default')
        basic_panel = None
        for p in main_panels:
            h2 = p.find('h2')
            if h2 and "Información básica" in h2.get_text():
                basic_panel = p
                break

        # 5. Cards
        cards = []
        card_panel = None
        for p in main_panels:
            h2 = p.find('h2')
            if h2 and "Lista de tarjetas de pago" in h2.get_text():
                card_panel = p
                break

        # 6. Cars
        cars = []
        car_panel = None
        for p in main_panels:
            h2 = p.find('h2')
            if h2 and "Coche" in h2.get_text():
                car_panel = p
                break

        # 7. Notes
        notes = []
        note_panel = None
        for p in main_panels:
            h2 = p.find('h2')
            if h2 and "Notas" in h2.get_text() and p.find('table'):
                note_panel = p
                break

        if note_panel:
            note_rows = note_panel.select('table tbody tr')
            for row in note_rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    n_date = cols[0].get_text(strip=True)
                    n_user = cols[1].get_text(strip=True)
                    n_msg = cols[2].get_text(strip=True)
                    notes.append(Note(date=n_date, author=n_user, message=n_msg))
        logger.debug(f"Notas encontradas: {len(notes)}")

        # 8. Daily Tariffs
        daily_tariffs = []
        tariff_panel = soup.find('div', id='anchors_billing_days')
        if tariff_panel:
            t_rows = tariff_panel.select('table tr')  # Headers + data
            for row in t_rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    t_date = cols[0].get_text(strip=True)
                    t_type = cols[1].get_text(strip=True)
                    t_price_str = cols[2].get_text(strip=True).replace(',', '.')
                    try:
                        t_price = float(t_price_str)
                        daily_tariffs.append(DailyTariff(date=t_date, rate_type=t_type, price=t_price))
                    except:
                        pass

        # 9. Change Log / History
        logs = []
        log_panel = soup.find('div', id='anchors_log')
        if log_panel:
            l_rows = log_panel.select('table tbody tr')
            for row in l_rows:
                cols = row.find_all('td')
                if len(cols) >= 7:
                    l_date = cols[0].get_text(strip=True)
                    l_id = cols[1].get_text(strip=True)
                    l_user = cols[2].get_text(strip=True)
                    l_type = cols[3].get_text(strip=True)
                    l_action = cols[4].get_text(strip=True)
                    l_amount = cols[5].get_text(strip=True)
                    l_desc = cols[6].get_text(strip=True)

                    logs.append(ChangeLog(
                        date=l_date,
                        log_id=l_id,
                        user=l_user,
                        type=l_type,
                        action=l_action,
                        amount=l_amount,
                        description=l_desc
                    ))
        logger.debug(f"Logs de cambios encontrados: {len(logs)}")

        # Determine if we should include raw_html
        # Default behavior was: if config.DEBUG else None
        # New behavior: if include_raw_html is True, include it.
        # If include_raw_html is False, check config.DEBUG as fallback or just None?
        # The request says "optional parameter", implying explicit control.
        # Let's use the parameter as the primary control, defaulting to False.
        # But we can keep the old behavior as a default if not specified?
        # The user asked for "optional parameter", so let's respect the parameter.
        
        final_raw_html = html_content if (include_raw_html or config.DEBUG) else None

        return ReservationDetail(
            reservation_id=reservation_id,
            guests=guests,
            services=services,
            payments=payments,
            cars=cars,
            notes=notes,
            daily_tariffs=daily_tariffs,
            logs=logs,
            cards=cards,
            balance=balance,
            total_price=total_price,
            channel_info=channel_info,
            basic_info=basic_info,
            raw_html=final_raw_html
        )

    def _build_date_mapping(self):
        """Construye el mapeo day_id → fecha ISO analizando la estructura del calendario."""
        logger.info("Construyendo mapeo de fechas (day_id -> fecha)...")
        self.day_id_to_date = {}
        current_date_index = 0

        # Recorrer cada bloque de mes en el calendario
        month_blocks = self.soup.select('.calendar_month')
        logger.debug(f"Bloques de mes encontrados: {len(month_blocks)}")
        
        for block in month_blocks:
            # Extraer mes y año del título
            month_title_elem = block.select_one('.calendar_month_title')
            if not month_title_elem:
                continue

            try:
                month_title = month_title_elem.get_text(strip=True)
                # Ejemplo: "Enero 2026"
                month_name, year_str = month_title.rsplit(' ', 1)
                year = int(year_str)

                # Mapeo de nombres de meses en español a números
                spanish_months = {
                    'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
                    'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
                }

                month = spanish_months.get(month_name.strip())
                logger.debug(f"Procesando mes: {month_name} ({month}) {year}")

                # Procesar cada día en este bloque de mes
                date_cells = block.select('.calendar_dates')
                for cell in date_cells:
                    day_elem = cell.select_one('.calendar_date')
                    if day_elem:
                        try:
                            day = int(day_elem.get_text(strip=True))
                            # Crear fecha ISO
                            date_str = f"{year}-{month:02d}-{day:02d}"

                            # Encontrar el day_id correspondiente (usando posición)
                            # Buscar celdas reales en la primera fila de datos
                            real_rows = self.soup.select('tbody.calendar_tbody:not(.my_category) tr')
                            if real_rows:
                                first_row = real_rows[0]
                                td_cells = first_row.select('td[day_id]')
                                if current_date_index < len(td_cells):
                                    day_id_elem = td_cells[current_date_index]
                                    day_id = day_id_elem.get('day_id')
                                    if day_id:
                                        self.day_id_to_date[day_id] = date_str
                            current_date_index += 1
                        except (ValueError, TypeError) as e:
                            logger.warning(f"⚠️ Error parseando día: {e}")
                            continue
            except Exception as e:
                logger.warning(f"⚠️ Error procesando bloque de mes '{month_title}': {e}")
                continue
        logger.info(f"Mapeo de fechas completado. Total días mapeados: {len(self.day_id_to_date)}")

    def _extract_categories(self):
        """Extrae las categorías de habitaciones."""
        logger.info("Extrayendo categorías de habitaciones...")
        category_elements = self.soup.find_all('div', {'class': 'calendar_rooms',
                                                       'id': lambda x: x and x.startswith('btn_close')})

        for cat_elem in category_elements:
            category_id = cat_elem.get('catid')
            if not category_id: continue

            category_name_elem = cat_elem.find('div', class_='calendar_rooms_dott')
            category_name = category_name_elem.get_text(strip=True) if category_name_elem else f"Category_{category_id}"
            rooms = self._extract_rooms_for_category(category_id)

            self.categories.append(RoomCategory(id=category_id, name=category_name, rooms=rooms))
        logger.debug(f"Categorías encontradas: {len(self.categories)}")

    def _extract_rooms_for_category(self, category_id: str) -> List[Dict[str, Any]]:
        rooms = []
        selector = f'div.calendar_num_room.btn_close_box{category_id}'
        room_elements = self.soup.select(selector)

        for room_elem in room_elements:
            room_text_elem = room_elem.find('div', class_='calendar_number_room')
            if room_text_elem:
                # Extraer solo el número de habitación (ignorar otros textos)
                room_text = room_text_elem.get_text(strip=True)
                room_number = room_text.split()[0] if room_text else f"room_{category_id}"
                
                # Obtener el room_id del atributo 'room_id' del elemento padre si existe
                current_room_id = room_elem.get('room_id')
                
                rooms.append({'room_number': room_number, 'room_id': current_room_id})
                
                # Guardar mapeo para uso posterior si tenemos room_id
                if current_room_id:
                    self.room_id_to_category[current_room_id] = {'category_id': category_id, 'category_name': '', 'room_number': room_number}
        
        logger.debug(f"Categoría {category_id}: {len(rooms)} habitaciones encontradas.")
        return rooms

    def _extract_rooms_data(self):
        """
        Extrae los datos diarios de todas las habitaciones, incluyendo reservas activas.
        """
        logger.info("Iniciando extracción de datos de celdas (habitaciones/días)...")
        
        # Reconstruir el mapa de categorías para búsqueda rápida
        category_map = {cat.id: cat.name for cat in self.categories}
        
        # Mapa inverso: room_number -> category_id
        room_number_to_cat = {}
        for cat in self.categories:
            for room in cat.rooms:
                room_number_to_cat[room['room_number']] = cat.id

        calendar_cells = self.soup.select('td.calendar_td[day_id][room_id]')
        all_cell = len(calendar_cells)
        logger.info(f"Total de celdas a procesar: {all_cell}")

        for i, cell in enumerate(calendar_cells):
            try:
                # Log de progreso cada 10%
                if all_cell > 0 and i % (all_cell // 10 + 1) == 0:
                    logger.debug(f"Procesando celdas... {round(i * 100 / all_cell, 1)}%")

                room_id = cell.get('room_id')
                day_id = cell.get('day_id')
                # category_id en la celda a veces no está o es incorrecto, mejor deducirlo
                cell_category_id = cell.get('category_id')

                # Saltar celdas de resumen de categoría
                if room_id == '0' or not day_id:
                    continue

                # Inicializar variables de reserva
                reservation = self._extract_reservation_from_cell(cell)

                # Determinar status
                status = 'available'
                reservation_status = None
                
                classes = cell.get('class', [])

                if 'bg_padlock' in classes:
                    status = 'locked'
                    reservation_status = 'locked'
                
                # Check-in / Check-out logic based on classes or content
                if 'calendar_td_start' in classes:
                     reservation_status = 'check-in'
                elif 'calendar_td_end' in classes:
                     reservation_status = 'check-out'

                if reservation['id']:
                    status = 'occupied'
                    # Si ya tenemos un estado de reserva (check-in/out), lo mantenemos.
                    # Si no, intentamos extraerlo del tooltip o usar 'reservation' por defecto.
                    if not reservation_status:
                        # Intentar extraer del tooltip si está disponible
                        if reservation.get('reservation_type'):
                             reservation_status = reservation.get('reservation_type')
                        else:
                             reservation_status = 'reservation'
                    
                    logger.debug(f"Reserva detectada en celda (Room: {room_id}, Day: {day_id}): ID={reservation['id']}, Status={reservation_status}")

                # Si no se deben incluir celdas vacías, saltar las disponibles y bloqueadas
                if not self.include_empty_cells and status in ['available', 'locked']:
                    continue

                # Extraer disponibilidad
                availability = 0
                # Intentar obtener category_id si no vino en la celda
                category_id = cell_category_id
                
                # Lógica para vincular room_id con room_number y category
                room_number = f"Unknown_{room_id}"
                real_category_id = category_id
                
                found_room = False
                # Buscar en el cache primero
                if room_id in self.room_id_to_category:
                    info = self.room_id_to_category[room_id]
                    room_number = info['room_number']
                    real_category_id = info['category_id']
                    found_room = True
                else:
                    # Buscar en el DOM
                    room_div = self.soup.find('div', attrs={'room_id': room_id})
                    if room_div:
                        classes = room_div.get('class', [])
                        for cls in classes:
                            if cls.startswith('btn_close_box'):
                                real_category_id = cls.replace('btn_close_box', '')
                                break
                        
                        room_text_div = room_div.find('div', class_='calendar_number_room')
                        if room_text_div:
                            room_number = room_text_div.get_text(strip=True).split()[0]
                            
                        # Guardar en cache
                        self.room_id_to_category[room_id] = {
                            'category_id': real_category_id,
                            'room_number': room_number,
                            'category_name': ''
                        }
                        found_room = True
                
                if not found_room:
                    room_number = self._extract_room_number(room_id, category_id)
                    if not real_category_id and room_number in room_number_to_cat:
                        real_category_id = room_number_to_cat[room_number]

                category_name = category_map.get(real_category_id, f'Category_{real_category_id}')

                # Availability logic
                if real_category_id:
                    availability_elem = self.soup.find('div', id=f'availability_{real_category_id}_{day_id}')
                    if availability_elem:
                        try:
                            availability = int(availability_elem.get_text(strip=True))
                        except (ValueError, TypeError):
                            availability = 0

                room_data = ReservationData(
                    date=self._convert_day_id_to_date(day_id),
                    room_id=room_id,
                    room_number=room_number,
                    category_id=real_category_id,
                    category_name=category_name,
                    status=status,
                    availability=availability,
                    day_id=day_id,
                    reservation_status=reservation_status,
                    details_reservation={}, # Empty for now as requested
                    reservation_id=reservation['id'],
                    guest_name=reservation['guest_name'],
                    source=reservation['source'],
                    check_in=reservation['check_in'],
                    check_out=reservation['check_out'],
                    balance=reservation['balance']
                )
                self.rooms_data.append(room_data)

            except Exception as e:
                logger.error(f"❌ Error procesando celda (room_id={room_id}, day_id={day_id}): {e}")
                continue
        logger.info("Extracción de datos de celdas finalizada.")

    def _extract_reservation_from_cell(self, cell):
        """
        Estrategia mejorada para extraer datos de reserva desde una celda:
        1. Buscar elementos con atributo resid (identificador de reserva real)
        2. Procesar el tooltip HTML correctamente
        3. Extraer información relevante
        """
        reservation_data = {
            'id': None,
            'guest_name': None,
            'source': None,
            'check_in': None,
            'check_out': None,
            'balance': None,
            'reservation_type': None
        }

        # Estrategia 1: Buscar elementos con atributo resid
        res_block = cell.find(lambda tag: tag.name == 'div' and tag.get('resid'))
        if res_block:
            reservation_data['id'] = res_block.get('resid')

            # Procesar el tooltip (data-title) si existe
            tooltip_html = res_block.get('data-title', '')
            if tooltip_html:
                # Decodificar entidades HTML primero
                decoded_html = html.unescape(tooltip_html)
                
                # Log del tooltip solo en debug si es necesario (puede ser verboso)
                # logger.debug(f"Tooltip encontrado para reserva {reservation_data['id']}: {decoded_html[:50]}...")

                try:
                    # Buscar tipo de reserva en el título (ej: Reserva №22781 (Reservación))
                    type_match = re.search(r'Reserva №\d+\s*\(([^)]+)\)', decoded_html)
                    if type_match:
                        # Mapear el texto encontrado a los estados deseados
                        raw_type = type_match.group(1).lower()
                        if 'reservación' in raw_type or 'reserva' in raw_type:
                            reservation_data['reservation_type'] = 'reservation'
                        # Se pueden agregar más mapeos aquí si aparecen otros textos como 'bloqueo', etc.
                    
                    # Buscar nombre del huésped
                    guest_match = re.search(r'Huésped:\s*([^<]+)</div>', decoded_html)
                    if guest_match:
                        reservation_data['guest_name'] = guest_match.group(1).strip()

                    # Buscar fechas
                    check_in_match = re.search(r'Llegada:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                    if check_in_match:
                        reservation_data['check_in'] = check_in_match.group(1)

                    check_out_match = re.search(r'Salida:\s*(\d{4}-\d{2}-\d{2})', decoded_html)
                    if check_out_match:
                        reservation_data['check_out'] = check_out_match.group(1)

                    # Buscar balance
                    balance_match = re.search(r'Balance:\s*([+-]?\d+\.?\d*)', decoded_html)
                    if balance_match:
                        reservation_data['balance'] = balance_match.group(1)

                    # Buscar fuente (Booking, Venta directa, etc.)
                    source_match = re.search(r'Reserva .+?,\s*([^<]+)</div>', decoded_html)
                    if source_match:
                        reservation_data['source'] = source_match.group(1).strip()
                except Exception as e:
                    logger.warning(f"⚠️ Error extrayendo datos del tooltip: {e}")

        # Estrategia 2: Si no hay tooltip, intentar obtener información directamente del elemento
        if not reservation_data['guest_name'] and res_block:
            booking_name_div = res_block.find('div', class_='calendar_booking_nam')
            if booking_name_div:
                text_content = booking_name_div.get_text(strip=True)
                # Ejemplo: "R:22765, BALON ALBERTO,"
                parts = text_content.split(',')
                if len(parts) > 1:
                    reservation_data['guest_name'] = parts[1].strip()

            booking_info_div = res_block.find('div', class_='calendar_booking_info')
            if booking_info_div and not reservation_data['source']:
                reservation_data['source'] = booking_info_div.get_text(strip=True).rstrip(',')

        return reservation_data

    def _extract_room_number(self, room_id: str, category_id: str) -> str:
        """Obtiene número de habitación desde categorías almacenadas"""
        for category in self.categories:
            if category.id == category_id:
                for room in category.rooms:
                    if room.get('room_id') == room_id:
                        return room['room_number']
                    # Fallback to old check if room_id was not captured in categories
                    if room['room_number'] == room_id:
                        return room_id
        return room_id

    def _extract_date_range(self):
        """Extrae el rango de fechas real basado en el mapeo generado"""
        logger.info("Calculando rango de fechas...")
        if self.day_id_to_date:
            sorted_dates = sorted(self.day_id_to_date.values())
            self.date_range = {
                'start_date': sorted_dates[0] if sorted_dates else "Unknown",
                'end_date': sorted_dates[-1] if sorted_dates else "Unknown",
                'total_days': len(sorted_dates)
            }
        else:
            # Fallback básico
            date_elements = self.soup.find_all('div', class_='calendar_dates')
            self.date_range = {
                'start_date': "Unknown",
                'end_date': "Unknown",
                'total_days': len(date_elements) if date_elements else 0
            }
        logger.debug(f"Rango calculado: {self.date_range}")

    def _convert_day_id_to_date(self, day_id: str) -> str:
        """Método robusto para convertir day_id a fecha"""
        return self.day_id_to_date.get(day_id, f"unknown_date_{day_id}")
