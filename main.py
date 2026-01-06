from src.scraper import OtelMSScraper
from src.extractor import OtelsExtractor
from src.config import Config


def main():
    # 1. Inicializar Scraper
    scraper = OtelMSScraper(
        username=Config.OTELMS_USER,
        password=Config.OTELMS_PASS,
        debug=Config.DEV_MODE
    )

    # 2. Login
    if not scraper.login():
        print("[!] No se pudo iniciar sesión. Abortando.")
        return

    # 3. Obtener Calendario
    try:
        html_content = scraper.get_reservation_calendar()
        
        # Guardar HTML para debug
        if Config.DEV_MODE:
            with open(Config.get_output_path("calendar_requests.html"), "w", encoding="utf-8") as f:
                f.write(html_content)
                
    except Exception as e:
        print(f"[!] Error obteniendo calendario: {e}")
        return

    # 4. Extraer Datos
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    print(f"\n[+] Extracción completada:")
    print(f"    - Categorías encontradas: {len(calendar_data.categories)}")
    print(f"    - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # 5. Buscar reservas para hoy (Lógica simple de ejemplo)
    target_date = Config.TARGET_DATE
    print(f"\n[+] Buscando reservas para la fecha: {target_date}")
    
    found = False
    for room in calendar_data.reservation_data:
        if room.date == target_date and room.status == 'occupied':
            found = True
            print(f"    - Habitación {room.room_number}: OCUPADA")
            if room.detail_url:
                print(f"      URL Detalle: {room.detail_url}")
                # Aquí podríamos llamar a scraper.get_page(room.detail_url)
            elif room.reservation_id:
                print(f"      ID Reserva: {room.reservation_id}")

    if not found:
        print(f"    - No se encontraron habitaciones ocupadas para {target_date}")

if __name__ == "__main__":
    main()
