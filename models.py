from decimal import Decimal
import logging
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
import uuid
from django.core.exceptions import ValidationError
from django.conf import settings

from payment.managers import PaymentManager

logger = logging.getLogger(__name__)


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

    class PaymentProviderChoices(models.TextChoices):
        ORANGE_CAMEROON = 'orange_cameroon', _('Orange Cameroon')
        MTN_CAMEROON = 'mtn_cameroon', _('MTN Cameroon')

    payment_class = models.CharField(_('Payment Class'), max_length=20, choices=PaymentClass.choices)
    payment_provider = models.CharField(_('Payment Provider'), max_length=20, choices=PaymentProviderChoices.choices)

    deposit_fee_percentage = models.FloatField(default=0.0)
    deposit_fee_fixed = models.FloatField(default=0.0)
    platform_deposit_fee_percentage = models.FloatField(default=0.0)
    platform_deposit_fee_fixed = models.FloatField(default=0.0)

    def calculate_deposit_amount(self, amount):
        """
        Calculate the total deposit amount including all fees and charges.

        Formula Derivation:
        -------------------
        Variables:
        - A = Payment Provider Fee (percentage, e.g., 1.5%)
        - B = Payment Provider Fixed Fee (e.g., 50c)
        - C = Payment Provider Exchange Fee (percentage, e.g., 1.5%)
        - D = Payment Provider Fixed Exchange Fee (e.g., 50c)
        - E = eMaketa Fee (percentage, e.g., 1.5%)
        - F = eMaketa Fixed Fee (e.g., 50c)
        - G = eMaketa Exchange Fee (percentage, e.g., 1.5%)
        - H = eMaketa Fixed Exchange Fee (e.g., 50c)
        - Y = Base Amount User Should Pay (parameter 'amount')
        - X = Total Amount to Request (return value)

        Starting Equation:
        X = Y + (A*X)/100 + B + (C*X)/100 + D + (E*X)/100 + F + (G*X)/100 + H

        Simplification:
        X = Y + B + D + F + H + AX/100 + CX/100 + EX/100 + GX/100
        X - AX/100 - CX/100 - EX/100 - GX/100 = Y + B + D + F + H
        X(1 - A/100 - C/100 - E/100 - G/100) = Y + B + D + F + H
        X(100 - A - C - E - G)/100 = Y + B + D + F + H

        Final Formula:
        X = (100Y + 100B + 100D + 100F + 100H) / (100 - A - C - E - G)
        X = 100(Y + B + D + F + H) / (100 - A - C - E - G)

        This ensures the user pays exactly Y after all fees are deducted.
        """
        amount = Decimal(str(amount))
        deposit_fee_fixed = Decimal(str(self.deposit_fee_fixed))
        emaketa_deposit_fee_fixed = Decimal(str(self.emaketa_deposit_fee_fixed))
        deposit_fee_percentage = Decimal(str(self.deposit_fee_percentage))
        emaketa_deposit_fee_percentage = Decimal(str(self.emaketa_deposit_fee_percentage))

        numerator = Decimal('100') * (amount + deposit_fee_fixed + emaketa_deposit_fee_fixed)
        denominator = Decimal('100') - deposit_fee_percentage - emaketa_deposit_fee_percentage
        total_amount = numerator / denominator
        return total_amount.quantize(Decimal('0.01'))

    def __str__(self):
        return f'{self.name}'


class PaymentMethod(models.Model):
    payment_type = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name='payment_methods')
    user_id = models.CharField(max_length=255, default='')
    detail = models.JSONField(_('Detail'))
    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user_id', 'payment_type', 'detail')

    def __str__(self):
        return f'{self.user_id} {self.detail}'


class PaymentTransaction(models.Model):

    class PaymentProvider(models.TextChoices):
        FLUTTERWAVE = 'flutterwave', 'Flutterwave'
        PAWAPAY = 'pawapay', 'Pawapay'
        MOBILE_MONEY = 'mobile_money', 'Mobile Money'
        ORANGE_MONEY = 'orange_money', 'Orange Money'
        MTN_MONEY = 'mtn_money', 'MTN Money'

    user_id = models.CharField(max_length=255, null=True, blank=True)
    order_id = models.CharField(max_length=255, default='')
    coupon_id = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_refundable = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="XAF")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payment_type = models.ForeignKey(PaymentType, on_delete=models.PROTECT, blank=True, null=True)
    payment_detail = models.JSONField(_('Detail'))
    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    external_reference = models.CharField(max_length=255, blank=True, null=True)
    provider = models.CharField(max_length=50, choices=PaymentProvider.choices)

    objects = PaymentManager

    def save(self, *args, **kwargs):
        if not self.provider:
            self.provider = settings.PAYMENT_PROVIDER
        super().save(*args, **kwargs)

    def pending(self):
        from payment.signals import payment_initiated
        logger.info(f"Payment status set to PENDING - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.PENDING.value)
        payment_initiated.send(sender=self.__class__, transaction=self)

    def success(self):
        from payment.signals import payment_succeeded
        logger.info(f"Payment SUCCESSFUL - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        with transaction.atomic():
            self.save()
            PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.COMPLETED.value)
        payment_succeeded.send(sender=self.__class__, transaction=self)

    def failed(self):
        from payment.signals import payment_failed
        logger.warning(f"Payment FAILED - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.FAILED.value)
        payment_failed.send(sender=self.__class__, transaction=self)

    def refund_initiated(self, provider_refund_id: str):
        from payment.signals import payment_refunded
        logger.info(f"Payment REFUND initiated - Transaction: {self.transaction_id}, Refund ID: {provider_refund_id}")
        with transaction.atomic():
            self.save()
            PaymentRefund.objects.create(transaction=self, provider_refund_id=provider_refund_id)
            PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.REFUNDED.value)
        payment_refunded.send(sender=self.__class__, transaction=self, provider_refund_id=provider_refund_id)

    def refund_failed(self):
        from payment.signals import payment_refund_failed
        logger.error(f"Payment REFUND FAILED - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.REFUND_FAILED.value)
        payment_refund_failed.send(sender=self.__class__, transaction=self)

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.amount} {self.currency}"


class PaymentRefund(models.Model):
    transaction = models.OneToOneField(PaymentTransaction, on_delete=models.PROTECT, related_name='refund')
    created_at = models.DateTimeField(auto_now_add=True)
    provider_refund_id = models.CharField(max_length=100, null=True, blank=True)
    manual_refund_id = models.CharField(max_length=100, null=True, blank=True)
    succeeded = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not (self.provider_refund_id or self.manual_refund_id):
            raise ValidationError("Either provider_refund_id or manual_refund_id must be present.")
        if self.provider_refund_id and self.manual_refund_id:
            raise ValidationError("Only one of provider_refund_id or manual_refund_id can be present.")
        if self.manual_refund_id:
            self.succeeded = True
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return str(self.transaction)


class PaymentStatus(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'
        REFUND_FAILED = "refund_failed", "Refund Failed"

    STATUS_FLOW = {
        StatusChoices.PENDING.value: [
            StatusChoices.COMPLETED.value,
            StatusChoices.FAILED.value
        ],
        StatusChoices.COMPLETED.value: [
            StatusChoices.REFUNDED.value,
            StatusChoices.REFUND_FAILED.value
        ],
        StatusChoices.FAILED.value: [
            StatusChoices.FAILED.value,
            StatusChoices.COMPLETED.value
        ],
        StatusChoices.REFUNDED.value: [],
        StatusChoices.REFUND_FAILED.value: [
            StatusChoices.REFUND_FAILED.value,
            StatusChoices.REFUNDED.value
        ]
    }

    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.PROTECT, related_name='statuses')
    status = models.CharField(max_length=30, choices=StatusChoices.choices, default=StatusChoices.PENDING.value)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'PaymentStatus'

    def __str__(self):
        return f"PaymentStatus {self.status} for Transaction {self.transaction.transaction_id}"

    def clean(self):
        latest_status = self.transaction.statuses.order_by('-created_at').first()
        if latest_status:
            valid_next_statuses = self.STATUS_FLOW.get(latest_status.status, [])
            if self.status not in valid_next_statuses:
                raise ValidationError(
                    f"Invalid status transition. Current status is {latest_status.status}. "
                    f"Valid next statuses are: {', '.join(valid_next_statuses)}"
                )
        else:
            if self.status != self.StatusChoices.PENDING.value:
                raise ValidationError("First status must be 'pending'")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
