from django.contrib import admin

from payment.models import PaymentType


# Register your models here.


@admin.register(PaymentType)
class PaymentTypeAdmin(admin.ModelAdmin):
    list_display = ('short_name', 'name', 'logo')

from django.contrib import admin
from .models import PaymentTransaction, PaymentStatus

class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'user', 'amount', 'currency', 'created_at', 'updated_at')
    list_filter = ('currency', 'created_at')
    search_fields = ('transaction_id', 'user__username', 'amount')
    ordering = ('-created_at',)
    readonly_fields = ('transaction_id', 'created_at', 'updated_at')

    def status(self, obj):
        return obj.status.status if obj.status else 'No Status'
    status.short_description = 'Payment Status'

class PaymentStatusAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('transaction__transaction_id', 'status')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

# Register the models with the admin site
admin.site.register(PaymentTransaction, PaymentTransactionAdmin)
admin.site.register(PaymentStatus, PaymentStatusAdmin)