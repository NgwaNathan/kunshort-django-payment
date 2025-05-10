from django.urls import path, include
from rest_framework.routers import DefaultRouter

from payment.views import UserPaymentMethods, UserPaymentTypes

router = DefaultRouter()
router.register(r'user-payment-types', UserPaymentTypes, basename='user_payment_types')
router.register(r'user-payment-method', UserPaymentMethods, basename='user_payment_methods')

urlpatterns = [
    path('', include((router.urls, 'payment'), namespace='payment'))
]