from decimal import Decimal
import logging
from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import uuid
from django.core.exceptions import ValidationError
from django.conf import settings

from core.models import Order, SystemConfiguration
from gift.models import Coupon
from payment.managers import PaymentManager
from users.models import User, UserLoyalty, UserReferal
from notification.alert_service import alert_payment_success, alert_payment_failed, AlertService
from notification.models import AlertEventType

logger = logging.getLogger(__name__)


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
    
    deposit_fee_percentage = models.FloatField(default=0.0)
    deposit_fee_fixed = models.FloatField(default=0.0)
    emaketa_deposit_fee_percentage = models.FloatField(default=0.0)
    emaketa_deposit_fee_fixed = models.FloatField(default=0.0)
    
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

    class PaymentProvider(models.TextChoices):
        FLUTTERWAVE = 'flutterwave', 'Flutterwave'
        PAWAPAY = 'pawapay', 'Pawapay'

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")  # Link to the user making the transaction
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # Amount of the transaction
    amount_refundable = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Amount that can be refunded
    currency = models.CharField(max_length=10, default="XAF")  # Currency code (e.g., 'USD', 'EUR')
    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the transaction was created
    updated_at = models.DateTimeField(auto_now=True)  # Timestamp when the transaction was last updated
    payment_type = models.ForeignKey(PaymentType, on_delete=models.PROTECT, max_length=50, blank=True, null=True)  # Optional field for payment method details
    payment_detail = models.JSONField(_('Detail'))
    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)  # Unique identifier for the transaction
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, null=True, blank=True)  # Link to the applied coupon
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")  # Link to the associated order
    external_reference = models.CharField(max_length=255, blank=True, null=True)  # External reference for the transaction
    provider = models.CharField(max_length=50, choices=PaymentProvider.choices)

    def save(self, *args, **kwargs):
        if not self.provider:
            self.provider = settings.PAYMENT_PROVIDER
        super().save(*args, **kwargs)

    def pending(self):
        logger.info(f"Payment status set to PENDING - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.PENDING.value)

        # Send alert for payment initiation
        AlertService.send_alert(
            event_type=AlertEventType.PAYMENT_INITIATED,
            title='💳 Payment Initiated',
            message=f'Payment of {self.amount} {self.currency} has been initiated',
            metadata={
                'transaction_id': str(self.transaction_id),
                'amount': str(self.amount),
                'currency': self.currency,
                'order_id': self.order.id if self.order else None,
                'user_phone': self.user.phone_number if self.user else 'Unknown',
                'provider': self.provider
            }
        )

    def success(self):
        logger.info(f"Payment SUCCESSFUL - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}, Order: {self.order.id if self.order else 'N/A'}")
        with transaction.atomic():
            self.save()
            PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.COMPLETED.value)
            self.reward_referer()

            # Send alert for successful payment
            alert_payment_success(
                self,
                transaction_id=str(self.transaction_id),
                amount=str(self.amount),
                currency=self.currency,
                order_id=self.order.id if self.order else None,
                user_phone=self.user.phone_number if self.user else 'Unknown',
                provider=self.provider,
                external_reference=self.external_reference or 'N/A'
            )
            
    def reward_referer(self):
        try:
            referal = UserReferal.objects.get(user=self.user, is_rewarded=False)
            user_loyalty, _ = UserLoyalty.objects.get_or_create(user=referal.referer)
            system_configs = SystemConfiguration.objects.first()
            user_loyalty.referral_points += system_configs.points_per_referral

            logger.info(f"Referral reward granted - Referer: {referal.referer.id}, Referred: {self.user.id}, Points: {system_configs.points_per_referral}")

            # Mark referral as rewarded and save
            referal.is_rewarded = True
            referal.save()
            # Signal will handle coupon creation and notification when threshold is reached
            user_loyalty.save()
        except UserReferal.DoesNotExist:
            logger.debug(f"No unrewarded referral found for user: {self.user.id}")
            pass
    def failed(self):
        logger.warning(f"Payment FAILED - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}, Order: {self.order.id if self.order else 'N/A'}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.FAILED.value)

        # Send alert for failed payment
        try:
            alert_payment_failed(
                self,
                reason='Payment processing failed',
                transaction_id=str(self.transaction_id),
                amount=str(self.amount),
                currency=self.currency,
                order_id=self.order.id if self.order else None,
                user_phone=self.user.phone_number if self.user else 'Unknown',
                provider=self.provider
            )
        except Exception as e:
            logger.warning(f"Could not send payment failed alert: {str(e)}")
    
    def refund_initiated(self, provider_refund_id: str):
        logger.info(f"Payment REFUND initiated - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}, Refund ID: {provider_refund_id}")
        with transaction.atomic():
            self.save()
            PaymentRefund.objects.create(transaction=self, provider_refund_id=provider_refund_id)
            PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.REFUNDED.value)

            # Send alert for refund
            AlertService.send_alert(
                event_type=AlertEventType.PAYMENT_REFUNDED,
                title='💸 Payment Refunded',
                message=f'Payment of {self.amount} {self.currency} has been refunded',
                metadata={
                    'transaction_id': str(self.transaction_id),
                    'amount': str(self.amount),
                    'currency': self.currency,
                    'order_id': self.order.id if self.order else None,
                    'user_phone': self.user.phone_number if self.user else 'Unknown',
                    'provider_refund_id': provider_refund_id
                }
            )
            
    def refund_failed(self):
        logger.error(f"Payment REFUND FAILED - Transaction: {self.transaction_id}, Amount: {self.amount} {self.currency}")
        self.save()
        PaymentStatus.objects.create(transaction=self, status=PaymentStatus.StatusChoices.REFUND_FAILED.value)


    objects = PaymentManager

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.amount} {self.currency}"
    
    
class PaymentRefund(models.Model):
    transaction = models.OneToOneField(PaymentTransaction, on_delete=models.PROTECT, related_name='refund')
    created_at = models.DateTimeField(auto_now_add=True)
    provider_refund_id = models.CharField(max_length=100, null=True, blank=True)  # if exist then refund was initiated by the provider where the payment was made
    manual_refund_id = models.CharField(max_length=100, null=True, blank=True)  # if exist then refund was made manually and needs the reference for the transaction
    succeeded = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Ensure that either provider_refund_id or manual_refund_id is present, but not both
        if not (self.provider_refund_id or self.manual_refund_id):
            raise ValidationError("Either provider_refund_id or manual_refund_id must be present.")
        if self.provider_refund_id and self.manual_refund_id:
            raise ValidationError("Only one of provider_refund_id or manual_refund_id can be present.")
        
        # Set refunded to True if manual_refund_id is present
        if self.manual_refund_id:
            self.succeeded = True
        
        super().save(*args, **kwargs)  # Call the original save method
        
    def __str__(self) -> str:
        return self.transaction


class PaymentStatus(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'
        REFUND_FAILED = "refund_failed", "Refund Failed"

    # Define the valid status transitions
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
        StatusChoices.REFUNDED.value: [
            
        ],  # No further statuses allowed
        StatusChoices.REFUND_FAILED.value: [
            StatusChoices.REFUND_FAILED.value,
            StatusChoices.REFUNDED.value
        ]  # No further statuses allowed
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
        # Get the latest status of the transaction
        latest_status = self.transaction.statuses.order_by('-created_at').first()
        
        if latest_status:
            # Check if the new status is a valid next status
            valid_next_statuses = self.STATUS_FLOW.get(latest_status.status, [])
            if self.status not in valid_next_statuses:
                raise ValidationError(
                    f"Invalid status transition. Current status is {latest_status.status}. "
                    f"Valid next statuses are: {', '.join(valid_next_statuses)}"
                )
        else:
            # If this is the first status, it must be PENDING
            if self.status != self.StatusChoices.PENDING.value:
                raise ValidationError("First status must be 'pending'")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
    