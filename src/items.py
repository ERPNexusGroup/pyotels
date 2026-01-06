import scrapy

class ReservationItem(scrapy.Item):
    id = scrapy.Field()
    room_number = scrapy.Field()
    check_in = scrapy.Field()
    check_out = scrapy.Field()
    status = scrapy.Field()
    total_price = scrapy.Field()
    currency = scrapy.Field()
    source = scrapy.Field()
    main_guest_name = scrapy.Field()
    main_guest_email = scrapy.Field()
    main_guest_phone = scrapy.Field()
    companions = scrapy.Field() # Lista de dicts
    raw_data = scrapy.Field()   # Dict con info extra
