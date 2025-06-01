


from payment.providers.flutterwave import FlutterWaveProvider
from payment.providers.pawapay import PawapayProvider


class PaymentProviderFactory:
    @staticmethod
    def get_instance(provider_name):
        if provider_name == "flutterwave":
            return FlutterWaveProvider()
        if provider_name == "pawapay":
            return PawapayProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")