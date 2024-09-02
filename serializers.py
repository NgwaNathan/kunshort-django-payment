from rest_framework import serializers

from payment.models import PaymentType, PaymentMethod


class PaymentTypeSerializer(serializers.ModelSerializer):

    class Meta:
        model = PaymentType
        fields = '__all__'


class UserPaymentTypeSerializer(serializers.ModelSerializer):
    payment_type = serializers.PrimaryKeyRelatedField(queryset=PaymentType.objects.all())

    class Meta:
        model = PaymentMethod
        exclude = ('user',)

    def create(self, validated_data):
        print(PaymentMethod.objects.all())
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().update(instance, validated_data)
