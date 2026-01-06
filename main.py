import argparse
import asyncio
import os
from tortoise import Tortoise, run_async
from src.scraper import OtelMSScraper
from src.extractor import OtelsExtractor
from src.config import config
from src.models import Reservation

def parse_arguments():
    parser = argparse.ArgumentParser(description="Scraper para OtelMS")
    parser.add_argument("--user", type=str, help="Usuario de OtelMS")
    parser.add_argument("--password", type=str, help="Contraseña de OtelMS")
    parser.add_argument("--date", type=str, help="Fecha objetivo (YYYY-MM-DD)")
    parser.add_argument("--id_hotel", type=str, help="ID del Hotel")
    return parser.parse_args()

async def init_db():
    """Inicializa la base de datos Tortoise ORM."""
    # En desarrollo, eliminamos la DB para asegurar que el esquema esté actualizado
    # Esto soluciona el error "table reservations has no column named room_number"
    db_file = "reservations.db"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
            print(f"[+] Base de datos anterior '{db_file}' eliminada para regenerar esquema.")
        except Exception as e:
            print(f"[!] No se pudo eliminar la base de datos anterior: {e}")

    await Tortoise.init(
        db_url=config.DATABASE_URL,
        modules={'models': ['src.models']}
    )
    await Tortoise.generate_schemas()

async def main():
    # 1. Inicializar DB
    await init_db()

    # 2. Procesar argumentos
    args = parse_arguments()
    
    username = args.user if args.user else 'gerencia@harmonyhotelgroup.com'
    password = args.password if args.password else 'Majestic2'
    id_hotel = args.id_hotel if args.id_hotel else '118510'
    target_date = args.date if args.date else config.TARGET_DATE

    if not username or not password:
        print("[!] Error: Se requieren usuario y contraseña.")
        return

    print(f"[+] Iniciando scraper con usuario: {username}")
    print(f"[+] Fecha objetivo: {target_date}")

    # 3. Inicializar Scraper
    scraper = OtelMSScraper(
        id_hotel=id_hotel,
        username=username,
        password=password,
        debug=config.DEBUG
    )

    # 4. Login (sigue siendo síncrono, se ejecuta antes del loop principal de scraping)
    if not scraper.login():
        print("[!] No se pudo iniciar sesión. Abortando.")
        return

    # 5. Obtener Calendario (ahora asíncrono y con caché)
    try:
        print("[+] Obteniendo calendario de reservas...")
        html_content = await scraper.get_reservation_calendar()
        
        if config.DEBUG:
            with open(config.get_output_path("calendar_requests.html"), "w", encoding="utf-8") as f:
                f.write(html_content)
                
    except Exception as e:
        print(f"[!] Error obteniendo calendario: {e}")
        return

    # 6. Extraer Datos
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    print(f"\n[+] Extracción completada:")
    print(f"    - Categorías encontradas: {len(calendar_data.categories)}")
    print(f"    - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # 7. Guardar en Base de Datos
    print("\n[+] Guardando/actualizando reservas en la base de datos...")
    saved_count = 0
    for room in calendar_data.reservation_data:
        if room.status == 'occupied' and room.reservation_id:
            # Usamos update_or_create para insertar o actualizar si ya existe
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
            if created:
                saved_count += 1
    print(f"    - {saved_count} nuevas reservas guardadas.")

    # 8. Buscar reservas para la fecha objetivo (ahora desde la DB)
    print(f"\n[+] Buscando reservas para la fecha: {target_date} desde la DB")
    
    reservations_on_date = await Reservation.filter(check_in__lte=target_date, check_out__gte=target_date)
    
    if reservations_on_date:
        for res in reservations_on_date:
            print(f"    - Habitación {res.room_number}: OCUPADA por {res.guest_name} (ID: {res.reservation_id})")
    else:
        print(f"    - No se encontraron habitaciones ocupadas para {target_date}")

if __name__ == "__main__":
    run_async(main())
