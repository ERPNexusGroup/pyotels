import argparse
import json
import time

from .scraper import OtelMSScraper
from .settings import config
from pyotels.utils.logger import logger, log_execution

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
    
    if args.verbose:
        config.VERBOSE = True
        logger.setLevel("DEBUG")

    username = args.user if args.user else None
    password = args.password if args.password else None
    id_hotel = args.id_hotel if args.id_hotel else None
    target_date = args.date if args.date else config.TARGET_DATE

    if not username or not password:
        logger.error("Se requieren usuario y contraseña.")
        return

    logger.info(f"Iniciando scraper para Hotel ID: {id_hotel}")
    
    # 2. Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        debug=config.DEBUG
    )

    # 3. Login
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
        scraper.set_room_checkout_playwright(args.reservation_id)
        return

    elif args.command == "checkin":
        if not args.reservation_id:
            logger.error("Debe especificar --reservation_id para checkin.")
            return
        scraper.set_room_checkin_playwright(args.reservation_id)
        return

    elif args.command == "close_room":
        if not args.room_id or not args.dates:
            logger.error("Debe especificar --room_id y --dates para cerrar habitación.")
            return
        scraper.update_room_availability_playwright(args.room_id, args.dates, "close")
        return

    # Default: scrape
    if args.command != "scrape":
        logger.error(f"Comando desconocido: {args.command}")
        return

    # 4. Obtener Datos (Modular)
    try:
        # --- Categorías ---
        logger.info("Obteniendo categorías...")
        categories = scraper.get_categories(target_date)
        
        # --- Grilla / Reservaciones ---
        logger.info("Obteniendo grilla de reservas...")
        grid = scraper.get_grid(target_date)
        
        # --- Detalles ---
        # Identificar reservas únicas para detalle
        unique_ids = set()
        for r in grid.reservation_data:
            if r.reservation_id:
                unique_ids.add(r.reservation_id)
        
        logger.info(f"Encontradas {len(unique_ids)} reservas únicas. Obteniendo detalles...")
        
        details = []
        for res_id in unique_ids:
            det = scraper.get_reservation_detail(res_id)
            if det:
                details.append(det)
                time.sleep(0.2) # Pausa leve
        
        # 5. Guardar resultados separados (Solo debug o si se requiere)
        if config.DEBUG:
            # Guardar Categorías
            cat_file = config.BASE_DIR / 'categories.json'
            with open(cat_file, 'w', encoding='utf-8') as f:
                json.dump(categories.model_dump(), f, indent=4, ensure_ascii=False, default=str)
            logger.info(f"Categorías guardadas en: {cat_file}")

            # Guardar Reservaciones (Grid)
            res_file = config.BASE_DIR / 'reservations.json'
            with open(res_file, 'w', encoding='utf-8') as f:
                json.dump(grid.model_dump(), f, indent=4, ensure_ascii=False, default=str)
            logger.info(f"Reservaciones guardadas en: {res_file}")

            # Guardar Detalles Individuales
            for det in details:
                det_file = config.BASE_DIR / f'details_{det.reservation_id}.json'
                with open(det_file, 'w', encoding='utf-8') as f:
                    json.dump(det.model_dump(), f, indent=4, ensure_ascii=False, default=str)
            
            logger.info(f"Detalles guardados ({len(details)} archivos).")

    except Exception as e:
        logger.error(f"Error en proceso de scraping: {e}", exc_info=True)
    finally:
        scraper.close()

    logger.info("Proceso finalizado exitosamente.")
