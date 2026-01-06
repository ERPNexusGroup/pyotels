import argparse
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
    # db_file = "reservations.db"
    # if os.path.exists(db_file):
    #     try:
    #         os.remove(db_file)
    #         print(f"[+] Base de datos anterior '{db_file}' eliminada para regenerar esquema.")
    #     except Exception as e:
    #         print(f"[!] No se pudo eliminar la base de datos anterior: {e}")

    await Tortoise.init(
        db_url=config.DATABASE_URL,
        modules={'models': ['src.models.db_models']}
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
                
    except Exception as e:
        print(f"[!] Error obteniendo calendario: {e}")
        return

    # 6. Extraer Datos
    extractor = OtelsExtractor(html_content)
    calendar_data = extractor.extract_calendar_data()

    print(f"\n[+] Extracción completada:")
    print(f"    - Categorías encontradas: {len(calendar_data.categories)}")
    print(f"    - Celdas de datos procesadas: {len(calendar_data.reservation_data)}")
    
    # Análisis de datos extraídos
    occupied_count = sum(1 for r in calendar_data.reservation_data if r.status == 'occupied')
    with_id_count = sum(1 for r in calendar_data.reservation_data if r.reservation_id)
    available_count = sum(1 for r in calendar_data.reservation_data if r.status == 'available')
    locked_count = sum(1 for r in calendar_data.reservation_data if r.status == 'locked')
    
    print(f"    - Ocupadas (status='occupied'): {occupied_count}")
    print(f"    - Con ID de reserva: {with_id_count}")
    print(f"    - Disponibles: {available_count}")
    print(f"    - Bloqueadas: {locked_count}")

    # 7. Guardar en Base de Datos
    print("\n[+] Guardando/actualizando reservas en la base de datos...")
    saved_count = 0
    skipped_no_id = 0
    skipped_status = 0
    error_count = 0
    
    for room in calendar_data.reservation_data:
        # Relaxed filter: Save if it has an ID, or if it says 'occupied' (even without ID, to see it in DB)
        # For now, we MUST have an ID to update_or_create safely, unless we generate a fake one for debugging.
        # Let's try to save if we have ID.
        
        should_save = False
        if room.reservation_id:
            should_save = True
        elif room.status == 'occupied':
            skipped_no_id += 1
            # Generate FAKE ID to force save and debug
            room.reservation_id = f"DEBUG_NO_ID_{room.room_number}_{room.date}"
            should_save = True
            if skipped_no_id <= 10:
                print(f"    [WARN] Room {room.room_number} ({room.date}) marcada 'occupied' pero SIN ID. Generado: {room.reservation_id}")
        else:
            skipped_status += 1

        if should_save:
            # Asegurarse que guest_name no sea None para reportes (opcional, pero ayuda)
            if not room.guest_name:
                room.guest_name = "Unknown Guest (Debug)"

            # Usamos update_or_create para insertar o actualizar si ya existe
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
            except Exception as e:
                error_count += 1
                if error_count <= 10: # Limitar logs de error
                    print(f"    [!] Error guardando {room.reservation_id}: {e}")
            
    print(f"    - {saved_count} reservas guardadas/actualizadas.")
    print(f"    - {skipped_no_id} tenían ID faltante (se generó ID temporal).")
    print(f"    - {skipped_status} omitidas por no estar ocupadas/reservadas.")
    print(f"    - {error_count} errores al guardar.")

    # 8. Buscar reservas para la fecha objetivo (ahora desde la DB)
    print(f"\n[+] Buscando reservas para la fecha: {target_date} desde la DB")
    
    # Nota: check_in y check_out son Datetime, target_date es string YYYY-MM-DD.
    # Tortoise puede necesitar casting o rangos.
    # Intentamos filtro simple primero, asumiendo que target_date funciona con lte/gte para fechas.
    try:
        reservations_on_date = await Reservation.filter(check_in__lte=target_date, check_out__gte=target_date)
        
        if reservations_on_date:
            print(f"    - Encontradas {len(reservations_on_date)} reservas activas para {target_date}:")
            for res in reservations_on_date:
                print(f"      * Habitación {res.room_number}: {res.guest_name} (ID: {res.reservation_id}, Status: {res.status})")
        else:
            print(f"    - No se encontraron habitaciones ocupadas para {target_date}")
            
            # Debug: mostrar algunas reservas guardadas cualquiera
            all_res = await Reservation.all().limit(5)
            if all_res:
                print("    - Muestra de reservas en DB (cualquier fecha):")
                for res in all_res:
                    print(f"      * {res.reservation_id}: {res.check_in} - {res.check_out}")
    except Exception as e:
        print(f"    [!] Error consultando DB: {e}")

if __name__ == "__main__":
    run_async(main())
