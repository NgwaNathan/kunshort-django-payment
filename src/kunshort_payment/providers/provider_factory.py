


from kunshort_payment.providers import SupportedProviders
from kunshort_payment.providers.flutterwave import FlutterWaveProvider
from kunshort_payment.providers.orange_money_provider import OrangeMoneyProvider
from kunshort_payment.providers.pawapay import PawapayProvider
from kunshort_payment.providers.momo_provider import MomoProvider


class PaymentProviderFactory:
    @staticmethod
    def get_instance(provider_name):
        if provider_name == SupportedProviders.FLUTTERWAVE:
            return FlutterWaveProvider()
        if provider_name == SupportedProviders.PAWAPAY:
            return PawapayProvider()
        if provider_name == SupportedProviders.MTN_CAMEROON:
            return MomoProvider()
        if provider_name == SupportedProviders.ORANGE_CAMEROON:
            return OrangeMoneyProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")