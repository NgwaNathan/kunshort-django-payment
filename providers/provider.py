from abc import abstractmethod, ABC


class Provider(ABC):
    @abstractmethod
    def momo_pay_cameroon(self, number):
        pass

    @abstractmethod
    def orange_money_pay_cameroon(self, number):
        pass

    
