from django.contrib import admin

from payment.models import PaymentType


# Register your models here.


@admin.register(PaymentType)
class PaymentTypeAdmin(admin.ModelAdmin):
    list_display = ('short_name', 'name', 'logo')
