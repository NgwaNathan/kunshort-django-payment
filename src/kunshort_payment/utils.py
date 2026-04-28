from kunshort_payment.models import PaymentStatus


def clean_phone_number(phone_number: str, prefx = "237") -> str:
    if phone_number.startswith(prefx):
        return phone_number[3:]
    if phone_number.startswith(f"+{prefx}"):
        return phone_number[4:]
    
    return phone_number

def get_customer_message_from_payment_status(payment_status: PaymentStatus):
    if payment_status.status == PaymentStatus.StatusChoices.FAILED:
        return "❌ We experienced a failure processing your payment. Visit your eMaketa List, copy your order ID and contact us with your order ID."
    elif payment_status.status == PaymentStatus.StatusChoices.COMPLETED:
        transaction = payment_status.transaction
        return f"✅ Thank you. We have received your payment of {transaction.currency} {transaction.amount}. Thanks for trusting eMaketa."
    elif payment_status.status == PaymentStatus.StatusChoices.REFUNDED:
        transaction = payment_status.transaction
        return f"✅ We have refunded your payment of {transaction.currency} {transaction.amount_refundable}. Thanks for trusting eMaketa."
