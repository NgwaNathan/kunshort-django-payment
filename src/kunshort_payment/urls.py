from django.urls import path

from kunshort_payment.views import (
    update_flutterwave_transaction,
    update_pawapay_transaction,
    update_momo_omo_transaction,
    update_momo_disbursement_transaction,
)

urlpatterns = [
    path("flutterwave/webhook/", update_flutterwave_transaction, name="flutterwave-webhook"),
    path("pawapay/webhook/", update_pawapay_transaction, name="pawapay-webhook"),
    path("momo/collection/webhook/", update_momo_omo_transaction, name="momo-collection-webhook"),
    path("momo/disbursement/webhook/", update_momo_disbursement_transaction, name="momo-disbursement-webhook"),
]
