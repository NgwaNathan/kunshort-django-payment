from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from users.models import User


# Create your models here.


class PaymentType(models.Model):
    logo = models.ImageField(_('Payment Logo'), upload_to='payment_logos')
    short_name = models.CharField(_('Short name'), max_length=15)
    name = models.CharField(_('Name'), max_length=50)
    is_active = models.BooleanField(default=False)
    metadata = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f'{self.name}'


class PaymentMethod(models.Model):
    payment_type = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name='payment_methods')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='users')
    detail = models.CharField(_('Detail'), max_length=100)
    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'payment_type', 'detail')

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if self.is_default and not self.id:
            has_default_payment_method = PaymentMethod.objects.filter(user=self.user, is_default=True).exists()
        super().save(force_insert, force_update, using, update_fields)


    def __str__(self):
        return f'{self.user.phone_number} {self.detail}'

