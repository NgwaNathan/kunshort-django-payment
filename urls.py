from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter
from payment.admin import PaymentTransactionAdmin

from payment.views import UserPaymentMethods, UserPaymentTypes, retry_failed_transaction, update_flutterwave_transaction, update_pawapay_transaction, update_momo_omo_transaction, check_transaction_status

router = DefaultRouter()
router.register(r'user-payment-types', UserPaymentTypes, basename='user_payment_types')
router.register(r'user-payment-method', UserPaymentMethods, basename='user_payment_methods')

urlpatterns = [
    path('', include((router.urls, 'payment'), namespace='payment')),
    path("flutterwave/transaction-update/", update_flutterwave_transaction, name='flutterwave-transaction-update'),
    path("pawapay/transaction-update/", update_pawapay_transaction, name="paway-transaction-update"),
    path("momo-omo/transaction-update/", update_momo_omo_transaction, name="momo-omo-transaction-update"),
    path('check_transaction_status/<str:transaction_id>/', check_transaction_status, name='check_transaction_status'),
    path('retry-failed-transaction/<str:transaction_id>/<str:external_reference>/', PaymentTransactionAdmin.retry_failed_transaction, name="retry_failed_transaction"),
    path('initiate_refund/<str:transaction_id>/<str:external_reference>/', PaymentTransactionAdmin.initiate_refund, name="initiate_refund"),
    path('retry-payment/<str:transaction_id>/', retry_failed_transaction, name='user-retry-failed-transaction')
]