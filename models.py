from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import uuid

from core.models import Order
from gift.models import Coupon
from payment.managers import PaymentManager
from users.models import User


# Create your models here.


class PaymentType(models.Model):
    logo = models.ImageField(_('Payment Logo'), upload_to='payment_logos')
    short_name = models.CharField(_('Short name'), max_length=15)
    name = models.CharField(_('Name'), max_length=50)
    
    is_active = models.BooleanField(default=False)
    metadata = models.JSONField(null=True, blank=True)

    class PaymentClass(models.TextChoices):
        PHONE_NUMBER = 'phone_number', _('Phone Number')
        CREDIT_CARD = 'credit_card', _('Credit Card')
        MASTER_CARD = 'master_card', _('Master Card')
        # Add more choices as needed

    class PaymentProviderChoices(models.TextChoices):
        ORANGE_CAMEROON = 'orange_cameroon', _('Orange Cameroon')
        MTN_CAMEROON = 'mtn_cameroon', _('MTN Cameroon')

    payment_class = models.CharField(_('Payment Class'), max_length=20, choices=PaymentClass.choices)
    payment_provider = models.CharField(_('Payment Provider'), max_length=20, choices=PaymentProviderChoices.choices)

    def __str__(self):
        return f'{self.name}'


class PaymentMethod(models.Model):
    payment_type = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name='payment_methods')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='users')
    detail = models.JSONField(_('Detail'))
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

    # Add other fields as necessary


class PaymentTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")  # Link to the user making the transaction
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Amount of the transaction
    amount_refundable = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Amount that can be refunded
    currency = models.CharField(max_length=10, default="XAF")  # Currency code (e.g., 'USD', 'EUR')
    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the transaction was created
    updated_at = models.DateTimeField(auto_now=True)  # Timestamp when the transaction was last updated
    payment_type = models.ForeignKey(PaymentType, on_delete=models.PROTECT, max_length=50, blank=True, null=True)  # Optional field for payment method details
    payment_detail = models.JSONField(_('Detail'))
    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)  # Unique identifier for the transaction
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, null=True, blank=True)  # Link to the applied coupon
    order = models.ForeignKey(Order, on_delete=models.PROTECT)  # Link to the associated order
    external_reference = models.CharField(max_length=255, blank=True, null=True)  # External reference for the transaction

    def paid(self):
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.COMPLETED.value)

    def failed(self):
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.FAILED.value)
    
    def refunded(self):
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.REFUNDED.value)


    objects = PaymentManager

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.amount} {self.currency}"


class PaymentStatus(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'

    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name='statuses')  # Link to the payment transaction
    status = models.CharField(max_length=10, choices=StatusChoices.choices, default=StatusChoices.PENDING.value)  # Status of the payment
    updated_at = models.DateTimeField(auto_now=True)  # Timestamp when the status was last updated
    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the status was created

    class Meta:
        unique_together = ("transaction", "status")

    def __str__(self):
        return f"PaymentStatus {self.status} for Transaction {self.transaction.transaction_id}"
    