import json
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from core.serializers import OrderSerializer
from payment.utils import get_customer_message_from_payment_status
from .models import PaymentStatus
from notification.tasks import send_payment_status_notification
from djangorestframework_camel_case.util import camelize

# Store previous referral points to detect changes
_user_loyalty_previous_points = {}

@receiver(post_save, sender=PaymentStatus)
def schedule_notification_for_payment_status(sender, instance, **kwargs):
    message = get_customer_message_from_payment_status(instance)
    if message:
        send_payment_status_notification.delay(
            user_id=instance.transaction.user.id,
            data={
                "title": "🤑 Payment Status",
                "description": message,
                "screen": "market-list",
                "order": json.dumps(camelize(OrderSerializer(instance.transaction.order).data))
            }
        )


@receiver(pre_save, sender='users.UserLoyalty')
def store_previous_loyalty_points(sender, instance, **kwargs):
    """Store the previous referral points value before save."""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _user_loyalty_previous_points[instance.pk] = old_instance.referral_points
        except sender.DoesNotExist:
            _user_loyalty_previous_points[instance.pk] = 0
    else:
        _user_loyalty_previous_points[instance.pk] = 0


@receiver(post_save, sender='users.UserLoyalty')
def handle_loyalty_points_update(sender, instance, created, **kwargs):
    """
    Signal to handle UserLoyalty updates:
    1. Send notification when user receives referral points
    2. Create coupon when loyalty points reach the reward threshold
    3. Reset points to 0 after coupon is claimed
    """
    # Import here to avoid circular imports
    from core.models import SystemConfiguration
    from gift.models import Coupon, CouponApplyChoices, CouponTypeChoices
    from notification.service import NotificationService

    # Get system configuration
    system_configs = SystemConfiguration.objects.first()
    if not system_configs:
        return

    # Skip if this is a new object
    if created:
        _user_loyalty_previous_points.pop(instance.pk, None)
        return

    # Get the previous points value
    previous_points = _user_loyalty_previous_points.get(instance.pk, 0)
    current_points = instance.referral_points

    # Calculate points added
    points_added = current_points - previous_points

    # Clean up the stored previous value
    _user_loyalty_previous_points.pop(instance.pk, None)

    # Only proceed if points were actually added (not subtracted or reset)
    if points_added > 0:
        # Check if threshold is reached
        if current_points >= system_configs.max_referral_for_reward:
            # Create coupon for the user
            coupon = Coupon.objects.create(
                type=CouponTypeChoices.percentage,
                value=50,
                apply_to=CouponApplyChoices.service_fee,
                user=instance.user
            )

            # Reset referral points using update to avoid triggering signal again
            sender.objects.filter(pk=instance.pk).update(referral_points=0)

            # Send notification about the coupon reward
            NotificationService.create_notification(
                user=instance.user,
                title="Referral Reward Unlocked!",
                message=f"Congratulations! You've earned a 50% discount coupon on service fees for referring friends. Your coupon is ready to use on your next order!",
                notification_type='promotion',
                priority='high',
                metadata={
                    'coupon_id': coupon.id,
                    'coupon_code': coupon.code if hasattr(coupon, 'code') else None,
                    'discount_value': 50,
                    'apply_to': 'service_fee',
                    'referral_points_used': system_configs.max_referral_for_reward
                }
            )
        else:
            # Send notification about earning points (not yet at threshold)
            points_remaining = system_configs.max_referral_for_reward - current_points
            NotificationService.create_notification(
                user=instance.user,
                title="Referral Points Earned!",
                message=f"You've earned {points_added} eMaketa referral point(s)! You now have {current_points} point(s). Just {points_remaining} more to unlock a 50% discount coupon!",
                notification_type='promotion',
                priority='medium',
                metadata={
                    'points_earned': points_added,
                    'total_points': current_points,
                    'points_remaining': points_remaining,
                    'threshold': system_configs.max_referral_for_reward
                }
            )