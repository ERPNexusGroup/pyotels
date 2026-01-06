import argparse
from src.scraper import OtelMSScraper
from src.extractor import OtelsExtractor
from src.config import config

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scraper para OtelMS")
    parser.add_argument("--user", type=str, help="Usuario de OtelMS")
    parser.add_argument("--password", type=str, help="Contraseña de OtelMS")
    parser.add_argument("--date", type=str, help="Fecha objetivo (YYYY-MM-DD)")
    return parser.parse_args()

def main():
    # 1. Procesar argumentos
    args = parse_arguments()
    
    # Determinar credenciales: Argumento > Config (Env/Default)
    # TODO: Eliminar Credenciales
    username = args.user if args.user else 'gerencia@harmonyhotelgroup.com'
    password = args.password if args.password else 'Majestic2'
    id_hotel = args.id_hotel if args.password else '118510'
    target_date = args.date if args.date else config.TARGET_DATE

    if not username or not password:
        print("[!] Error: Se requieren usuario y contraseña.")
        print("    Uso: python main.py --user USUARIO --password PASS")
        return

    print(f"[+] Iniciando scraper con usuario: {username}")
    print(f"[+] Fecha objetivo: {target_date}")

    # 2. Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        debug=config.DEV_MODE
    )

    # 3. Login
    if not scraper.login():
        print("[!] No se pudo iniciar sesión. Abortando.")
        return

    # 4. Obtener Calendario
    try:
        html_content = scraper.get_reservation_calendar()
        
        # Guardar HTML para debug
        if config.DEV_MODE:
            with open(config.get_output_path("calendar_requests.html"), "w", encoding="utf-8") as f:
                f.write(html_content)
                
    except Exception as e:
        print(f"[!] Error obteniendo calendario: {e}")
        return

    # 5. Extraer Datos
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    print(f"\n[+] Extracción completada:")
    print(f"    - Categorías encontradas: {len(calendar_data.categories)}")
    print(f"    - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # 6. Buscar reservas para la fecha objetivo
    print(f"\n[+] Buscando reservas para la fecha: {target_date}")
    
    found = False
    for room in calendar_data.reservation_data:
        if room.date == target_date and room.status == 'occupied':
            found = True
            print(f"    - Habitación {room.room_number}: OCUPADA")
            if room.detail_url:
                print(f"      URL Detalle: {room.detail_url}")
                # Opcional: Navegar al detalle
                # detail_html = scraper.get_page(room.detail_url, save_prefix=f"res_{room.room_number}")
            elif room.reservation_id:
                print(f"      ID Reserva: {room.reservation_id}")

    if not found:
        print(f"    - No se encontraron habitaciones ocupadas para {target_date}")

if __name__ == "__main__":
    main()
