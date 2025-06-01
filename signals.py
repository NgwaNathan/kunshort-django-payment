from django.db.models.signals import post_save
from django.dispatch import receiver

from payment.utils import get_customer_message_from_payment_status
from .models import PaymentStatus
from notification.tasks import send_payment_status_notification

@receiver(post_save, sender=PaymentStatus)
def schedule_notification_for_payment_status(sender, instance, **kwargs):
    message = get_customer_message_from_payment_status(instance)
    if message:
        send_payment_status_notification.delay(
            user_id=instance.transaction.user.id,
            title='Payment Status',
            description=message
        )