

from .mobile_money_provider import MobileMoneyProvider


class OrangeMoneyProvider(MobileMoneyProvider):

    def _collect(self, number, amount, tx_ref):
        pass

    def _transfer(self, number, amount, tx_ref):
        pass

    def _verify_transaction(self, ref):
        pass

    def _initiate_refund(self, ref, payload):
        pass
    
    def collect(self, number, amount, tx_ref):
        return self._collect(number, amount, tx_ref)

    def transfer(self, number, amount, tx_ref):
        return super().transfer(number, amount, tx_ref)

    def verify_transaction(self, ref):
        return super().verify_transaction(ref)

    def initiate_refund(self, ref, payload):
        return super().initiate_refund(ref, payload)