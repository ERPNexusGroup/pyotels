import json
import time
from src.pyotels.scraper import OtelMSScraper
from src.pyotels.settings import config
from src.pyotels.logger import logger

def main():
    # Configuración manual para pruebas
    # Puedes modificar estos valores directamente aquí o asegurarte de que config.py los tenga
    id_hotel = '118510'
    username = 'gerencia@harmonyhotelgroup.com'
    password = 'Majestic2'
    target_date = config.TARGET_DATE  # O una fecha específica '2026-01-15'

    logger.info(f"Iniciando prueba manual de scraper para Hotel ID: {id_hotel}")

    # Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password
    )

    try:
        # 1. Login
        if not scraper.login():
            logger.critical("Fallo en el login. Verifica credenciales.")
            return

        # 2. Obtener Categorías
        logger.info("--- Obteniendo Categorías ---")
        categories = scraper.get_categories(target_date)
        
        # Guardar categories.json
        if config.DEBUG:
            cat_file = config.BASE_DIR / 'categories.json'
            with open(cat_file, 'w', encoding='utf-8') as f:
                json.dump(categories.model_dump(), f, indent=4, ensure_ascii=False, default=str)
            logger.info(f"Categorías guardadas en: {cat_file}")

        # 3. Obtener Grilla de Reservas
        logger.info("--- Obteniendo Grilla de Reservas ---")
        grid = scraper.get_reservations(target_date)
        
        # Guardar reservations.json
        res_file = config.BASE_DIR / 'reservations.json'
        with open(res_file, 'w', encoding='utf-8') as f:
            json.dump(grid.model_dump(), f, indent=4, ensure_ascii=False, default=str)
        logger.info(f"Grilla guardada en: {res_file}")

        # 4. Obtener Detalles de Reservas Únicas
        logger.info("--- Obteniendo Detalles de Reservas ---")
        
        # Identificar IDs únicos
        unique_ids = set()
        for r in grid.reservation_data:
            if r.reservation_id:
                unique_ids.add(r.reservation_id)
        
        logger.info(f"Reservas únicas encontradas: {len(unique_ids)}")

        for res_id in unique_ids:
            logger.info(f"Procesando reserva: {res_id}")
            detail = scraper.get_reservation_detail(res_id)
            
            if detail:
                # Guardar details_[ID].json
                det_file = config.BASE_DIR / f'details_{res_id}.json'
                with open(det_file, 'w', encoding='utf-8') as f:
                    json.dump(detail.model_dump(), f, indent=4, ensure_ascii=False, default=str)
                logger.info(f"Detalle guardado: {det_file}")
                
                # Pausa para ser amable con el servidor
                time.sleep(0.5)
            else:
                logger.warning(f"No se pudo obtener detalle para {res_id}")

    except Exception as e:
        logger.error(f"Error durante la ejecución manual: {e}", exc_info=True)
    finally:
        scraper.close()
        logger.info("Prueba manual finalizada.")

if __name__ == "__main__":
    main()
