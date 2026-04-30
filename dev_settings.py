INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "kunshort_payment",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PROVIDERS = {
    "MTN_CAMEROON": "MTN_CAMEROON",
}

PAYMENT_PROVIDER = "mtn_money"

PAWAPAY = {
    "BASE_URL": "https://fake.pawapay.test",
    "BEARER_TOKEN": "fake-token",
}

MTN_MOMO = {
    "BASE_URL": "https://fake.mtn.test",
    "API_USER_ID": "fake-user-id",
    "API_KEY": "fake-api-key",
    "SUBSCRIPTION_KEY": "fake-sub-key",
    "TARGET_ENVIRONMENT": "sandbox",
    "CALLBACK_URL": "",
}

MTN_DISBURSEMENT = {
    "BASE_URL": "https://fake.mtn.test",
    "API_USER_ID": "fake-user-id",
    "API_KEY": "fake-api-key",
    "SUBSCRIPTION_KEY": "fake-sub-key",
    "TARGET_ENVIRONMENT": "sandbox",
    "CALLBACK_URL": "",
    "CHECK_BALANCE_BEFORE_TRANSFER": False,
}

FLUTTERWAVE_PAYMENT = {
    "SECRET_KEY": "fake-flutterwave-key",
}
