from django.urls import path, include
from rest_framework.routers import DefaultRouter

from payment.views import PaymentTypesViewSet, UserPaymentTypes

router = DefaultRouter()
router.register(r'payment-types', PaymentTypesViewSet, basename='payment_types')
router.register(r'user-payment-types', UserPaymentTypes, basename='user_payment_types')

urlpatterns = [
    path('', include((router.urls, 'payment'), namespace='payment'))
]