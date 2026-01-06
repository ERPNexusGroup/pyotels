from tortoise import fields, models

class Reservation(models.Model):
    """Modelo principal de la reserva con información básica y totales."""
    id = fields.IntField(pk=True)
    reservation_id = fields.CharField(max_length=50, unique=True, index=True)
    hotel_id = fields.CharField(max_length=50, null=True)
    
    # Información Básica
    status = fields.CharField(max_length=50, null=True)
    sub_status = fields.CharField(max_length=50, null=True)
    source = fields.CharField(max_length=100, null=True) # Fuente: Booking, etc.
    legal_entity = fields.CharField(max_length=255, null=True)
    payer = fields.CharField(max_length=255, null=True)
    guest_name = fields.CharField(max_length=255, null=True)
    
    # Alojamiento
    check_in = fields.DatetimeField(null=True)
    check_out = fields.DatetimeField(null=True)
    nights = fields.IntField(null=True)
    adults = fields.IntField(default=0)
    children = fields.IntField(default=0)
    room_number = fields.CharField(max_length=50, null=True)
    room_category = fields.CharField(max_length=100, null=True)
    rate_name = fields.CharField(max_length=100, null=True) # Tarifa: Tarifa Booking
    
    # Información Adicional (Grupo)
    group_name = fields.CharField(max_length=255, null=True)
    group_id = fields.CharField(max_length=50, null=True)
    
    # Totales y Balance
    total_price = fields.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance = fields.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount = fields.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Metadatos del sistema
    created_at_hotel = fields.DatetimeField(null=True)
    updated_at_hotel = fields.DatetimeField(null=True)
    
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "reservations"

    def __str__(self):
        return f"Reserva {self.reservation_id}"


class ReservationGuest(models.Model):
    """Huespedes asociados a la reserva."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='guests')
    guest_id = fields.CharField(max_length=50, null=True) # ID interno del sistema
    name = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255, null=True)
    phone = fields.CharField(max_length=50, null=True)
    country = fields.CharField(max_length=100, null=True)
    is_main = fields.BooleanField(default=False)
    
    class Meta:
        table = "reservation_guests"


class ReservationService(models.Model):
    """Servicios cargados a la reserva."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='services')
    service_id = fields.CharField(max_length=50, null=True)
    date = fields.DatetimeField(null=True)
    title = fields.CharField(max_length=255)
    description = fields.TextField(null=True)
    quantity = fields.IntField(default=1)
    price = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    class Meta:
        table = "reservation_services"


class ReservationPayment(models.Model):
    """Pagos realizados."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='payments')
    payment_id = fields.CharField(max_length=50, null=True)
    date = fields.DatetimeField(null=True)
    created_at_payment = fields.DatetimeField(null=True)
    type = fields.CharField(max_length=100, null=True)
    method = fields.CharField(max_length=100, null=True)
    amount = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    description = fields.TextField(null=True)
    
    class Meta:
        table = "reservation_payments"


class ReservationCard(models.Model):
    """Tarjetas de crédito asociadas (tokenizadas o información segura)."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='cards')
    card_number_masked = fields.CharField(max_length=50, null=True) # Ej: ****** 1234
    holder_name = fields.CharField(max_length=255, null=True)
    expiration_date = fields.CharField(max_length=20, null=True)
    
    class Meta:
        table = "reservation_cards"


class ReservationNote(models.Model):
    """Notas y comentarios."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='notes')
    date = fields.DatetimeField(null=True)
    author = fields.CharField(max_length=255, null=True)
    message = fields.TextField()
    type = fields.CharField(max_length=50, default="note") # note, remark, etc.
    
    class Meta:
        table = "reservation_notes"


class ReservationCar(models.Model):
    """Información de vehículos."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='cars')
    brand = fields.CharField(max_length=100, null=True)
    model = fields.CharField(max_length=100, null=True)
    color = fields.CharField(max_length=50, null=True)
    plate = fields.CharField(max_length=50, null=True)
    
    class Meta:
        table = "reservation_cars"


class ReservationDailyTariff(models.Model):
    """Desglose de tarifa por día."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='daily_tariffs')
    date = fields.DateField()
    rate_type = fields.CharField(max_length=100, null=True)
    price = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    class Meta:
        table = "reservation_daily_tariffs"


class ReservationChangeLog(models.Model):
    """Historial de cambios (Log)."""
    reservation = fields.ForeignKeyField('models.Reservation', related_name='logs')
    log_id = fields.CharField(max_length=50, null=True)
    date = fields.DatetimeField(null=True)
    user = fields.CharField(max_length=255, null=True)
    type = fields.CharField(max_length=100, null=True)
    action = fields.CharField(max_length=255, null=True)
    amount = fields.CharField(max_length=100, null=True)
    description = fields.TextField(null=True)
    
    class Meta:
        table = "reservation_logs"

class HtmlCache(models.Model):
    """Almacena el HTML crudo de las páginas visitadas para caché."""
    id = fields.IntField(pk=True)
    url = fields.CharField(max_length=500, unique=True, index=True)
    raw_html = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()

    class Meta:
        table = "html_cache"
