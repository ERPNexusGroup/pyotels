import sqlite3
import json
from .config import Config
from .items import ReservationItem

class SQLitePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def __init__(self, crawler):
        self.crawler = crawler

    def open_spider(self, *args, **kwargs):
        self.conn = sqlite3.connect(Config.DB_PATH)
        self.cursor = self.conn.cursor()
        self._create_table()

    def close_spider(self, *args, **kwargs):
        self.conn.close()

    def _create_table(self):
        self.cursor.execute('''
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
        self.conn.commit()

    def process_item(self, item, spider):
        # Note: Keeping spider argument for compatibility with Scrapy interface, 
        # even though warning mentions it. Using spider logger directly. 
        # If strict deprecation removal is needed, we would use self.crawler.spider
        
        if not isinstance(item, ReservationItem):
            return item

        companions_json = json.dumps(item.get('companions', []), ensure_ascii=False)
        raw_data_json = json.dumps(item.get('raw_data', {}), ensure_ascii=False)

        self.cursor.execute('''
        INSERT OR REPLACE INTO reservations (
            id, room_number, check_in, check_out, status, 
            total_price, currency, source, 
            main_guest_name, main_guest_email, main_guest_phone,
            companions_json, raw_data_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            item.get('id'), item.get('room_number'), item.get('check_in'), item.get('check_out'), item.get('status'),
            item.get('total_price'), item.get('currency'), item.get('source'),
            item.get('main_guest_name'), item.get('main_guest_email'), item.get('main_guest_phone'),
            companions_json, raw_data_json
        ))
        
        self.conn.commit()
        spider.logger.info(f"Reserva {item.get('id')} guardada en DB.")
        return item

class JsonWriterPipeline:
    """Guarda items en JSONL para debug en modo DEV."""
    
    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def __init__(self, crawler):
        self.crawler = crawler

    def open_spider(self, *args, **kwargs):
        if Config.DEV_MODE:
            self.file = open(Config.get_output_path('items.jsonl'), 'w', encoding='utf-8')

    def close_spider(self, *args, **kwargs):
        if Config.DEV_MODE:
            self.file.close()

    def process_item(self, item, spider):
        if Config.DEV_MODE:
            line = json.dumps(dict(item), ensure_ascii=False) + "\n"
            self.file.write(line)
        return item
