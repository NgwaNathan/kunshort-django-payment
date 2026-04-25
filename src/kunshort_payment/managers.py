from typing import Any
from django.db import models, transaction



class PaymentManager(models.Manager):
    @transaction.atomic
    def create(self, **kwargs: Any) -> Any:
        from kunshort_payment.models import PaymentStatus
        transaction = super().create(**kwargs)
        PaymentStatus.objects.create(transaction=transaction)
    