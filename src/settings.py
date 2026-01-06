# Configuración de Scrapy
from .config import Config

BOT_NAME = 'otelms_bot'

SPIDER_MODULES = ['src.spiders']
NEWSPIDER_MODULE = 'src.spiders'

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# Usar el User-Agent definido en la configuración de negocio
USER_AGENT = Config.USER_AGENT

# Pipelines
ITEM_PIPELINES = {
   'src.pipelines.SQLitePipeline': 300,
   'src.pipelines.JsonWriterPipeline': 400,
}

# Logs
LOG_LEVEL = 'INFO'
