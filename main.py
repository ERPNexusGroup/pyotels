import argparse
import os
from tortoise import Tortoise, run_async
from src.scraper import OtelMSScraper
from src.extractor import OtelsExtractor
from src.config import config
from src.models import Reservation
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
async def init_db():
    """Inicializa la base de datos Tortoise ORM."""
    logger.info("Inicializando base de datos...")
    await Tortoise.init(
        db_url=config.DATABASE_URL,
        modules={'models': ['src.models.db_models']}
    )
    await Tortoise.generate_schemas()
    logger.info("Base de datos inicializada correctamente.")

@log_execution
async def main():
    # 1. Inicializar DB
    await init_db()

    # 2. Procesar argumentos
    args = parse_arguments()
    
    # Sobreescribir configuración si se pasa por argumento
    if args.verbose:
        config.VERBOSE = True
        # Reconfigurar nivel de log si es necesario (aunque setup_logger ya se ejecutó, 
        # podemos ajustar el nivel dinámicamente si fuera crítico, pero por ahora confiamos en config)
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

    # 1. Inicializar DB
    await init_db()

    # 3. Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        debug=config.DEBUG
    )

    # 4. Login
    logger.info("Intentando iniciar sesión...")
    if not await scraper.login():
        logger.critical("No se pudo iniciar sesión. Abortando.")
        return

    # 5. Obtener Calendario
    try:
        logger.info("Obteniendo calendario de reservas...")
        html_content = await scraper.get_reservation_calendar()
        logger.debug(f"Calendario obtenido. Tamaño HTML: {len(html_content)} caracteres")
                
    except Exception as e:
        logger.error(f"Error obteniendo calendario: {e}", exc_info=True)
        return

    # 6. Extraer Datos
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

    # 7. Guardar en Base de Datos
    logger.info("Guardando/actualizando reservas en la base de datos...")
    saved_count = 0
    skipped_no_id = 0
    skipped_status = 0
    error_count = 0
    
    for room in calendar_data.reservation_data:
        should_save = False
        if room.reservation_id:
            should_save = True
        elif room.status == 'occupied':
            skipped_no_id += 1
            # Generate FAKE ID to force save and debug
            room.reservation_id = f"DEBUG_NO_ID_{room.room_number}_{room.date}"
            should_save = True
            if skipped_no_id <= 10:
                logger.warning(f"Room {room.room_number} ({room.date}) marcada 'occupied' pero SIN ID. Generado: {room.reservation_id}")
        else:
            skipped_status += 1

        if should_save:
            if not room.guest_name:
                room.guest_name = "Unknown Guest (Debug)"

            try:
                reservation, created = await Reservation.update_or_create(
                    reservation_id=room.reservation_id,
                    defaults={
                        'room_number': room.room_number,
                        'guest_name': room.guest_name,
                        'check_in': room.check_in,
                        'check_out': room.check_out,
                        'status': room.status,
                        'source': room.source,
                    }
                )
                saved_count += 1
                if config.VERBOSE:
                    logger.debug(f"Reserva {'creada' if created else 'actualizada'}: {room.reservation_id}")
            except Exception as e:
                error_count += 1
                if error_count <= 10:
                    logger.error(f"Error guardando {room.reservation_id}: {e}")
            
    logger.info(f"Resumen de persistencia:")
    logger.info(f"  - Guardadas/Actualizadas: {saved_count}")
    logger.info(f"  - IDs temporales generados: {skipped_no_id}")
    logger.info(f"  - Omitidas (no ocupadas): {skipped_status}")
    logger.info(f"  - Errores: {error_count}")

    # 8. Buscar reservas para la fecha objetivo
    logger.info(f"Buscando reservas activas para la fecha: {target_date} en DB")
    
    try:
        reservations_on_date = await Reservation.filter(check_in__lte=target_date, check_out__gte=target_date)
        
        if reservations_on_date:
            logger.info(f"Encontradas {len(reservations_on_date)} reservas activas para {target_date}:")
            for res in reservations_on_date:
                logger.info(f"  * Habitación {res.room_number}: {res.guest_name} (ID: {res.reservation_id}, Status: {res.status})")
        else:
            logger.info(f"No se encontraron habitaciones ocupadas para {target_date}")
            
            if config.VERBOSE:
                all_res = await Reservation.all().limit(5)
                if all_res:
                    logger.debug("Muestra de reservas en DB (cualquier fecha):")
                    for res in all_res:
                        logger.debug(f"  * {res.reservation_id}: {res.check_in} - {res.check_out}")
    except Exception as e:
        logger.error(f"Error consultando DB: {e}", exc_info=True)

if __name__ == "__main__":
    run_async(main())
