import json

from src.pyotels.logger import logger
from src.pyotels.scraper import OtelMSScraper
from src.pyotels.settings import config

# --- CONFIGURACIÓN DE PRUEBAS ---
# Lista de métodos a ejecutar:
# 1: get_categories
# 2: get_reservations (Grilla)
# 3: get_reservations_ids (Solo IDs visibles)
# 4: get_all_reservation_modals (Todos los modales visibles)
# 5: get_reservation_detail (Detalle de una reserva específica o iteración manual)
# 0: Ejecutar TODOS (en orden lógico)

TEST_METHODS = [1, 2, 3, 4, 5]  # Ejemplo: [1, 2] o [0] o [4]

# ID de reserva específico para probar el méto.do 5 (si se selecciona)
TEST_RESERVATION_ID = '22802'


def main():
    # Configuración manual para pruebas
    id_hotel = '118510'
    username = 'gerencia@harmonyhotelgroup.com'
    password = 'Majestic2'
    target_date = config.TARGET_DATE  # O '2026-01-16'

    logger.info(f"Iniciando prueba manual de scraper para Hotel ID: {id_hotel}")
    logger.info(f"Métodos seleccionados: {TEST_METHODS}")

    # Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        use_cache=False,
        return_dict=True,
        headless=False
    )

    try:
        # Siempre hacemos Login primero
        if not scraper.login():
            logger.critical("Fallo en el login. Verifica credenciales.")
            return

        # Determinar qué ejecutar
        run_all = 0 in TEST_METHODS

        # 1. Obtener Categorías
        if run_all or 1 in TEST_METHODS:
            logger.info("\n--- [1] Obteniendo Categorías ---")
            categories = scraper.get_categories(target_date)
            save_json(categories, 'categories.json')

        # 2. Obtener Reservas (Grilla)
        if run_all or 2 in TEST_METHODS:
            logger.info("\n--- [2] Obteniendo Grilla de Reservas ---")
            grid = scraper.get_reservations(target_date)
            save_json(grid, 'reservations.json')

        # 3. Obtener IDs de Reservas Visibles
        if run_all or 3 in TEST_METHODS:
            logger.info("\n--- [3] Obteniendo IDs de Reservas Visibles ---")
            ids = scraper.get_reservations_ids(target_date)
            logger.info(f"IDs encontrados: {ids}")
            save_json(ids, 'visible_ids.json')

        # 4. Obtener Todos los Modales Visibles
        if run_all or 4 in TEST_METHODS:
            logger.info("\n--- [4] Obteniendo Todos los Modales Visibles ---")
            # Nota: Este mét.odo ya navega y extrae
            modals_details = scraper.get_all_reservation_modals()

            # Convertir lista de objetos a lista de dicts para JSON
            details_data = [d for d in modals_details]
            save_json(details_data, 'all_modals_details.json')

            logger.info(f"Se extrajeron {len(details_data)} detalles de modales.")

        # 5. Obtener Detalle de Reserva Específica
        if 5 in TEST_METHODS:  # No incluido en run_all por defecto para no saturar si no hay ID
            logger.info(f"\n--- [5] Obteniendo Detalle para Reserva {TEST_RESERVATION_ID} ---")
            if TEST_RESERVATION_ID:
                detail = scraper.get_reservation_detail(TEST_RESERVATION_ID)
                if detail:
                    save_json(detail, f'detail_{TEST_RESERVATION_ID}.json')
                else:
                    logger.warning(f"No se encontró detalle para {TEST_RESERVATION_ID}")
            else:
                logger.warning("No se definió TEST_RESERVATION_ID para la prueba 5.")

    except Exception as e:
        logger.error(f"Error durante la ejecución manual: {e}", exc_info=True)
    finally:
        scraper.close()
        logger.info("Prueba manual finalizada.")


def save_json(data, filename):
    """Helper para guardar JSON en la carpeta data/"""
    if config.DEBUG:
        file_path = config.BASE_DIR / 'data' / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False, default=str)
        logger.info(f"Datos guardados en: {file_path}")


if __name__ == "__main__":
    main()
