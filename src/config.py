import os
from datetime import datetime

class Config:
    """Configuración de la aplicación."""
    DEV_MODE = True
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    DEV_OUTPUT_DIR = os.path.join(BASE_DIR, 'extract')
    DB_PATH = os.path.join(BASE_DIR, 'reservations.db')
    
    # Configuración de Scraping
    # Por defecto extrae las reservas de la fecha actual
    TARGET_DATE = datetime.now().strftime('%Y-%m-%d') 
    
    # Credenciales OtelMS
    OTELMS_USER = "gerencia@harmonyhotelgroup.com"
    OTELMS_PASS = "Majestic2"
    
    # ZenRows API Key
    ZENROWS_API_KEY = "TU_ZENROWS_API_KEY_AQUI" 
    
    # Configuración Scrapy
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    if DEV_MODE and not os.path.exists(DEV_OUTPUT_DIR):
        os.makedirs(DEV_OUTPUT_DIR)

    @staticmethod
    def get_output_path(filename: str) -> str:
        if Config.DEV_MODE:
            return os.path.join(Config.DEV_OUTPUT_DIR, filename)
        return filename
