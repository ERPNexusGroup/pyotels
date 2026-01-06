import sqlite3
import json
from typing import Optional
from .config import Config
from .models import Reservation

class DatabaseManager:
    """Maneja la persistencia de datos en SQLite."""

    def __init__(self):
        self.db_path = Config.DB_PATH
        self._init_db()

    def _init_db(self):
        """Inicializa la base de datos y crea las tablas si no existen."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Tabla de reservas
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id TEXT PRIMARY KEY,
            room_number TEXT,
            check_in TEXT,
            check_out TEXT,
            status TEXT,
            total_price REAL,
            currency TEXT,
            source TEXT,
            main_guest_name TEXT,
            main_guest_email TEXT,
            main_guest_phone TEXT,
            companions_json TEXT,
            raw_data_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()

    def save_reservation(self, reservation: Reservation):
        """Guarda o actualiza una reserva."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        companions_json = json.dumps([
            {'name': c.name, 'email': c.email, 'phone': c.phone} 
            for c in reservation.companions
        ], ensure_ascii=False)
        
        raw_data_json = json.dumps(reservation.raw_data, ensure_ascii=False)

        main_guest_name = reservation.main_guest.name if reservation.main_guest else None
        main_guest_email = reservation.main_guest.email if reservation.main_guest else None
        main_guest_phone = reservation.main_guest.phone if reservation.main_guest else None

        cursor.execute('''
        INSERT OR REPLACE INTO reservations (
            id, room_number, check_in, check_out, status, 
            total_price, currency, source, 
            main_guest_name, main_guest_email, main_guest_phone,
            companions_json, raw_data_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            reservation.id, reservation.room_number, reservation.check_in, reservation.check_out, reservation.status,
            reservation.total_price, reservation.currency, reservation.source,
            main_guest_name, main_guest_email, main_guest_phone,
            companions_json, raw_data_json
        ))

        conn.commit()
        conn.close()
        print(f"[DB] Reserva {reservation.id} guardada/actualizada.")

    def get_reservation(self, reservation_id: str) -> Optional[tuple]:
        """Obtiene una reserva por ID (crudo)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reservations WHERE id = ?', (reservation_id,))
        row = cursor.fetchone()
        conn.close()
        return row
