from abc import abstractmethod, ABC


class MobileMoneyProvider(ABC):

    @abstractmethod
    def collect(self, number, amount, tx_ref):
        pass

    def transfer(self, number, amount, tx_ref):
        return False, (
            f"{self.__class__.__name__} does not support disbursements. "
            "Use MomoProvider (MTN MoMo) for transfer operations."
        )

    @abstractmethod
    def verify_transaction(self, ref):
        pass

    @abstractmethod
    def initiate_refund(self, original_reference_id, amount, tx_ref):
        pass
