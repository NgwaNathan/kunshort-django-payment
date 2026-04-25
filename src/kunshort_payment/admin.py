import logging
from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from kunshort_payment.models import PaymentType
from kunshort_payment.service import PaymentService


# Register your models here.

logger = logging.getLogger(__name__)
@admin.register(PaymentType)
class PaymentTypeAdmin(admin.ModelAdmin):
    list_display = ('short_name', 'name', 'logo')

from django.contrib import admin
from .models import PaymentRefund, PaymentTransaction, PaymentStatus

class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'external_reference', 'order_id', 'user_id', 'amount', 'currency', 'created_at', 'updated_at', 'status', 'check_status_button')
    list_filter = ('currency', 'created_at')
    search_fields = ('transaction_id', 'external_reference', 'order_id', 'user_id', 'amount')
    ordering = ('-created_at',)
    readonly_fields = ('transaction_id', 'created_at', 'updated_at')

    def get_status_action_text(self, obj):
        last_status = obj.statuses.last()
        last_sibling_transaction = PaymentTransaction.objects.filter(order_id=obj.order_id).last()
        if not obj.statuses.exists():
            return "Initiate", True, "payment:retry_failed_transaction"
        elif last_status.status == PaymentStatus.StatusChoices.PENDING.value:
            return "Check", True, "payment:check_transaction_status"
        elif last_status.status == PaymentStatus.StatusChoices.FAILED.value and last_sibling_transaction.id == obj.id:
            return "Retry", True, "payment:retry_failed_transaction"
        elif last_status.status == PaymentStatus.StatusChoices.COMPLETED.value or last_status.status == PaymentStatus.StatusChoices.REFUND_FAILED:
            return "Refund", True, "payment:initiate_refund"
        elif last_status.status == PaymentStatus.StatusChoices.REFUNDED.value:
            refund = PaymentRefund.objects.get(transaction=obj)
            if refund.succeeded:
                return "✅ Refunded", False, ""
            else:
                return "Verify", True, "payment:verify_refund_status"
        else:
            return "", False, ""

    def status(self, obj):
        if not obj.statuses.exists():
            return "No Status"
        return obj.statuses.last().status
    status.short_description = 'Payment Status'

    def check_status_button(self, obj):
        text, is_action, view = self.get_status_action_text(obj)
        if is_action:
            return format_html('<a class="button" href="{}">{}</a>', reverse(view, args=[str(obj.transaction_id), obj.external_reference]), text)
        else:
            return format_html('<h4>{}</h4>', text)
    check_status_button.short_description = 'Action'

    def check_transaction_status(request, transaction_id):
        transaction = PaymentTransaction.objects.get(transaction_id=transaction_id)
        payment_service = PaymentService(transaction.payment_type.payment_provider)
        success, _ = payment_service.verify_transaction(transaction.external_reference)
        
        if success and _["status"] == payment_service.provider.status.COMPLETED.value:
            transaction.success()
            messages.success(request, f'Transaction {transaction_id} was successful.')
        else:
            transaction.failed()
            messages.error(request, f'Transaction {transaction_id} failed.')

        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
    
    def retry_failed_transaction(request, transaction_id, external_reference):
        transaction = PaymentTransaction.objects.get(transaction_id=transaction_id)
        payment_service = PaymentService(transaction.payment_type.payment_provider)
        logger.info(f"Retrying transaction with ID: {transaction_id}")
        try:
            success, _ = payment_service.verify_transaction(transaction_id)
            if not hasattr(_, "status") or _["status"] != payment_service.provider.status.ACCEPTED.value:
                success, _, _ = payment_service.initiate_payment_retry(transaction)
                if success:
                    messages.success(request, f'Re initiated payment for order {transaction.order_id}.')
                else:
                    logger.info(f"Retrying payment was not successful | {_}")
                    messages.error(request, f"Retrying payment for transaction {transaction_id} wasn't successful")
            logger.info(f"Transaction for {transaction_id} completed | {_}")
            messages.success(request, f"Retrying transaction {transaction_id} failed because transaction was already completed")
            
        except Exception as ex:
            logger.exception(ex)
            transaction.failed()
            messages.error(request, f'Transaction {transaction_id} retry failed')
            
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
    
    def initiate_refund(request, transaction_id, external_reference):
        transaction = PaymentTransaction.objects.get(transaction_id=transaction_id)
        payment_service = PaymentService(transaction.payment_type.payment_provider)
        try:
            success, _ = payment_service.initiate_refund(external_reference, {"amount": transaction.amount_refundable, "comments": "Cancelled"})
            if success:
                transaction.refund_initiated(_["data"]["tx_id"])
                messages.success(request, f'Refund for transaction {transaction_id} was initiated successfully.')
            else:
                transaction.refund_failed()
                messages.error(request, f'Refund for transaction {transaction_id} failed')
                
        except Exception as ex:
            logger.exception(ex)
            transaction.refund_failed()
            messages.error(request, f'Refund for transaction {transaction_id} failed')
            
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
    
    def verify_refund_status(request, transaction_id, external_reference):
        transaction = PaymentTransaction.objects.select_related('refund').get(transaction_id=transaction_id)
        payment_service = PaymentService(transaction.payment_type.payment_provider)
        try:
            pass
        except Exception as ex:
            logger.exception(ex)
            
class PaymentStatusAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('transaction__transaction_id', 'status')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    
@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'provider_refund_id', 'manual_refund_id', 'succeeded', 'created_at')
    search_fields = ('transaction__transaction_id', 'provider_refund_id', 'manual_refund_id')
    list_filter = ('succeeded', 'created_at')
    ordering = ('-created_at',)

    def __str__(self):
        return f"Refund for Transaction {self.transaction.transaction_id}"

# Register the models with the admin site
admin.site.register(PaymentTransaction, PaymentTransactionAdmin)
admin.site.register(PaymentStatus, PaymentStatusAdmin)