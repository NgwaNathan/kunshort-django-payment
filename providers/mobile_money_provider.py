from abc import abstractmethod, ABC


class MobileMoneyProvider(ABC):
    @abstractmethod
    def collect(self, number, amount, tx_ref):
        pass

    @abstractmethod
    def transfer(self, number, amount, tx_ref):
        pass

    @abstractmethod
    def verify_transaction(self, ref):
        pass

    @abstractmethod
    def initiate_refund(self, ref, payload):
        pass

    
