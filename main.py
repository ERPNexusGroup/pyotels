import argparse
import pprint
from src.scraper import OtelMSScraper
from src.extractor import OtelsExtractor
from src.config import config
from src.logger import logger, log_execution

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scraper para OtelMS")
    parser.add_argument("--user", type=str, help="Usuario de OtelMS")
    parser.add_argument("--password", type=str, help="Contraseña de OtelMS")
    parser.add_argument("--date", type=str, help="Fecha objetivo (YYYY-MM-DD)")
    parser.add_argument("--id_hotel", type=str, help="ID del Hotel")
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

    # 4. Obtener Calendario
    try:
        logger.info("Obteniendo calendario de reservas...")
        html_content = scraper.get_reservation_calendar()
        logger.debug(f"Calendario obtenido. Tamaño HTML: {len(html_content)} caracteres")
                
    except Exception as e:
        logger.error(f"Error obteniendo calendario: {e}", exc_info=True)
        return

    # 5. Extraer Datos
    logger.info("Procesando datos del calendario...")
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    logger.info(f"Extracción completada:")
    logger.info(f"  - Categorías encontradas: {len(calendar_data.categories)}")
    logger.info(f"  - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # Análisis de datos extraídos
    occupied_count = sum(1 for r in calendar_data.reservation_data if r.status == 'occupied')
    with_id_count = sum(1 for r in calendar_data.reservation_data if r.reservation_id)
    available_count = sum(1 for r in calendar_data.reservation_data if r.status == 'available')
    locked_count = sum(1 for r in calendar_data.reservation_data if r.status == 'locked')
    
    logger.info(f"  - Ocupadas: {occupied_count}")
    logger.info(f"  - Con ID: {with_id_count}")
    logger.info(f"  - Disponibles: {available_count}")
    logger.info(f"  - Bloqueadas: {locked_count}")

    # 6. Imprimir datos capturados
    logger.info("Imprimiendo datos capturados...")
    pprint.pprint(calendar_data)

    logger.info("Proceso finalizado exitosamente.")

if __name__ == "__main__":
    main()
