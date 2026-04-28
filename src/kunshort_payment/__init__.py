from kunshort_payment.signals import (
    payment_initiated,
    payment_succeeded,
    payment_failed,
    payment_refunded,
    payment_refund_failed,
)


def __getattr__(name):
    if name == "PaymentService":
        from kunshort_payment.service import PaymentService
        return PaymentService
    raise AttributeError(f"module 'kunshort_payment' has no attribute {name!r}")


__all__ = [
    "PaymentService",
    "payment_initiated",
    "payment_succeeded",
    "payment_failed",
    "payment_refunded",
    "payment_refund_failed",
]
