def pytest_configure():
    """
    Called by pytest before any tests are collected.
    We configure Django here with the minimum settings our app needs.

    We also include dummy values for all provider settings because several
    provider modules (pawapay.py, momo_provider.py, flutterwave.py) read
    settings at import time — Django will crash before any test even runs
    if those keys are missing.
    """
    from django.conf import settings

    settings.configure(
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "kunshort_payment",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        },
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        PROVIDERS={
            "MTN_CAMEROON": "MTN_CAMEROON",
            "ORANGE_CAMEROON": "ORANGE_CAMEROON",
        },
        PAYMENT_PROVIDER="mtn_money",
        # Dummy values — providers import these at module level, so they must exist.
        # In real usage these come from your actual Django settings file.
        PAWAPAY={
            "BASE_URL": "https://fake.pawapay.test",
            "BEARER_TOKEN": "fake-token",
        },
        MTN_MOMO={
            "BASE_URL": "https://fake.mtn.test",
            "API_USER_ID": "fake-user-id",
            "API_KEY": "fake-api-key",
            "SUBSCRIPTION_KEY": "fake-sub-key",
            "TARGET_ENVIRONMENT": "sandbox",
            "CALLBACK_URL": "",
        },
        MTN_DISBURSEMENT={
            "BASE_URL": "https://fake.mtn.test",
            "API_USER_ID": "fake-user-id",
            "API_KEY": "fake-api-key",
            "SUBSCRIPTION_KEY": "fake-sub-key",
            "TARGET_ENVIRONMENT": "sandbox",
            "CALLBACK_URL": "",
            "CHECK_BALANCE_BEFORE_TRANSFER": False,
        },
        FLUTTERWAVE_PAYMENT={
            "SECRET_KEY": "fake-flutterwave-key",
        },
    )
