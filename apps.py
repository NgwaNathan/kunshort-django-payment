from django.apps import AppConfig


class PaymentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payment'
    
    def ready(self):
        import payment.signals  # noqa: F401 — registers signal definitions
        import payment.tasks    # noqa: F401 — registers the @receiver on start_momo_polling_on_payment_initiated
