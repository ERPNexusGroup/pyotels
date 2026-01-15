import argparse
import json
import time

from .scraper import OtelMSScraper
from .extractor import OtelsExtractor
from .settings import config
from .logger import logger, log_execution

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scraper para OtelMS")
    parser.add_argument("command", nargs="?", default="scrape", choices=["scrape", "checkout", "checkin", "close_room"], help="Acción a realizar")
    parser.add_argument("--user", type=str, help="Usuario de OtelMS")
    parser.add_argument("--password", type=str, help="Contraseña de OtelMS")
    parser.add_argument("--date", type=str, help="Fecha objetivo (YYYY-MM-DD)")
    parser.add_argument("--id_hotel", type=str, help="ID del Hotel")
    parser.add_argument("--reservation_id", type=str, help="ID de reserva para acciones")
    parser.add_argument("--room_id", type=str, help="ID de habitación para acciones")
    parser.add_argument("--dates", nargs="+", help="Fechas (YYYY-MM-DD) para acciones de disponibilidad")
    parser.add_argument("--verbose", action="store_true", help="Activar logs detallados")
    return parser.parse_args()

@log_execution
def main():
    # 1. Procesar argumentos
    args = parse_arguments()
    
    # Sobreescribir configuración si se pasa por argumento
    if args.verbose:
        config.VERBOSE = True
        # Reconfigurar nivel de log si es necesario
        logger.setLevel("DEBUG")

    username = args.user if args.user else 'gerencia@harmonyhotelgroup.com'
    password = args.password if args.password else 'Majestic2'
    id_hotel = args.id_hotel if args.id_hotel else '118510'
    target_date = args.date if args.date else config.TARGET_DATE

    if not username or not password:
        logger.error("Se requieren usuario y contraseña.")
        return

    logger.info(f"Iniciando scraper para Hotel ID: {id_hotel}")
    logger.info(f"Usuario: {username}")
    logger.info(f"Fecha objetivo: {target_date}")

    # 2. Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        debug=config.DEBUG
    )

    # 3. Login
    logger.info("Intentando iniciar sesión...")
    if not scraper.login():
        logger.critical("No se pudo iniciar sesión. Abortando.")
        return

    # -----------------------
    # Manejo de Comandos
    # -----------------------
    if args.command == "checkout":
        if not args.reservation_id:
            logger.error("Debe especificar --reservation_id para checkout.")
            return
        scraper.set_room_checkout(args.reservation_id)
        return

    elif args.command == "checkin":
        if not args.reservation_id:
            logger.error("Debe especificar --reservation_id para checkin.")
            return
        scraper.set_room_checkin(args.reservation_id)
        return

    elif args.command == "close_room":
        if not args.room_id or not args.dates:
            logger.error("Debe especificar --room_id y --dates para cerrar habitación.")
            return
        params = {"room_id": args.room_id, "dates": args.dates}
        scraper.update_room_availability("close", params)
        return

    # Si no es nunguno de los anteriores, asumimos "scrape" (default)
    if args.command != "scrape":
        logger.error(f"Comando desconocido: {args.command}")
        return

    # 4. Obtener Calendario
    try:
        logger.info("Obteniendo calendario de reservas...")
        html_content = scraper.get_reservation_calendar()
        logger.debug(f"Calendario obtenido. Tamaño HTML: {len(html_content)} caracteres")
                
    except Exception as e:
        logger.error(f"Error obteniendo calendario: {e}", exc_info=True)
        return

    # 5. Extraer Datos del Calendario
    logger.info("Procesando datos del calendario...")
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    logger.info(f"Extracción inicial completada:")
    logger.info(f"  - Categorías encontradas: {len(calendar_data.categories)}")
    logger.info(f"  - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # 6. Extraer Detalles de Reservas
    # Identificar IDs de reservas únicos para no hacer peticiones repetidas
    unique_reservation_ids = set()
    for r in calendar_data.reservation_data:
        if r.reservation_id:
            unique_reservation_ids.add(r.reservation_id)
    
    logger.info(f"Se encontraron {len(unique_reservation_ids)} reservas únicas para extraer detalles.")
    
    # Diccionario temporal para almacenar detalles y evitar múltiples peticiones
    details_cache = {}
    
    # Procesar cada reserva única
    for i, res_id in enumerate(unique_reservation_ids):
        try:
            logger.info(f"[{i+1}/{len(unique_reservation_ids)}] Obteniendo detalles para reserva {res_id}...")
            
            # Obtener HTML de detalles
            details_html = scraper.get_reservation_details(res_id)
            
            if details_html:
                # Extraer objeto ReservationDetail
                details_obj = extractor.extract_reservation_details(details_html, res_id, include_raw_html=False)
                
                # Convertir a diccionario para almacenar en el JSON final
                from dataclasses import asdict
                details_dict = asdict(details_obj)
                
                # Limpiar raw_html si no es debug para ahorrar espacio
                if not config.DEBUG and 'raw_html' in details_dict:
                    details_dict['raw_html'] = None
                
                details_cache[res_id] = details_dict
                
                # Pequeña pausa para no saturar el servidor
                time.sleep(0.5)
            else:
                logger.warning(f"No se pudo obtener HTML para reserva {res_id}")
                
        except Exception as e:
            logger.error(f"Error procesando detalles de reserva {res_id}: {e}")
            continue

    # 7. Asignar detalles a los datos del calendario
    logger.info("Asignando detalles a las reservas en el calendario...")
    count_assigned = 0
    for r in calendar_data.reservation_data:
        if r.reservation_id and r.reservation_id in details_cache:
            r.details_reservation = details_cache[r.reservation_id]
            count_assigned += 1
            
    logger.info(f"Detalles asignados a {count_assigned} celdas de reserva.")

    # Análisis de datos extraídos
    occupied_count = sum(1 for r in calendar_data.reservation_data if r.status == 'occupied')
    with_id_count = sum(1 for r in calendar_data.reservation_data if r.reservation_id)
    available_count = sum(1 for r in calendar_data.reservation_data if r.status == 'available')
    locked_count = sum(1 for r in calendar_data.reservation_data if r.status == 'locked')
    
    logger.info(f"Resumen final:")
    logger.info(f"  - Ocupadas: {occupied_count}")
    logger.info(f"  - Con ID: {with_id_count}")
    logger.info(f"  - Disponibles: {available_count}")
    logger.info(f"  - Bloqueadas: {locked_count}")

    # 8. Imprimir datos capturados
    logger.info("Guardando datos capturados...")
    
    output_file = config.BASE_DIR / 'calendar_data.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(calendar_data, f, indent=4, ensure_ascii=False, default=lambda o: o.__dict__)
        logger.info(f"Datos guardados en: {output_file}")
    except Exception as e:
        logger.error(f"Error guardando datos: {e}")

    logger.info("Proceso finalizado exitosamente.")


