import json
import csv
from datetime import datetime
from dataclasses import asdict
from .models import CalendarData
from .config import Config

class DataExporter:
    """Clase encargada de exportar los datos extraídos."""

    @staticmethod
    def export_to_json(data: CalendarData, filename: str = None):
        """Exporta los datos a formato JSON."""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'otelms_calendar_{timestamp}.json'
            
        output_path = Config.get_output_path(filename)

        # Convertir dataclasses a diccionarios y limpiar datos no serializables
        categories_clean = []
        for cat in data.categories:
            cat_dict = asdict(cat)
            # Remover elementos BeautifulSoup de las habitaciones
            cat_dict['rooms'] = [{'room_number': room['room_number']} for room in cat.rooms]
            categories_clean.append(cat_dict)

        export_data = {
            'metadata': {
                'extracted_at': data.extracted_at,
                'date_range': data.date_range,
                'total_categories': len(data.categories),
                'total_rooms_data': len(data.rooms_data)
            },
            'categories': categories_clean,
            'rooms_data': [asdict(room) for room in data.rooms_data]
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        print(f"[+] Datos exportados a {output_path}")
        return output_path

    @staticmethod
    def export_to_csv(data: CalendarData, filename: str = None):
        """Exporta los datos a formato CSV."""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'otelms_calendar_{timestamp}.csv'
            
        output_path = Config.get_output_path(filename)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Escribir encabezados
            writer.writerow(['Fecha', 'Room_ID', 'Room_Number', 'Category_ID', 'Category_Name', 'Status', 'Availability', 'Day_ID'])

            # Escribir datos
            for room in data.rooms_data:
                writer.writerow([
                    room.date,
                    room.room_id,
                    room.room_number,
                    room.category_id,
                    room.category_name,
                    room.status,
                    room.availability,
                    room.day_id
                ])

        print(f"[+] Datos exportados a {output_path}")
        return output_path
