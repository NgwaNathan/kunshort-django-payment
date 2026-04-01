


from payment.providers.flutterwave import FlutterWaveProvider
from payment.providers.orange_money_provider import OrangeMoneyProvider
from payment.providers.pawapay import PawapayProvider
from payment.providers.momo_provider import MomoProvider


class PaymentProviderFactory:
    @staticmethod
    def get_instance(provider_name):
        if provider_name == "flutterwave":
            return FlutterWaveProvider()
        if provider_name == "pawapay":
            return PawapayProvider()
        if provider_name == "mtn_mobile_money":
            return MomoProvider()
        if provider_name == "orange_money":
            return OrangeMoneyProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")