from rest_framework import serializers

from payment.models import PaymentType, PaymentMethod


class PaymentMethodSerializer(serializers.ModelSerializer):
    payment_type = serializers.PrimaryKeyRelatedField(queryset=PaymentType.objects.all())

    class Meta:
        model = PaymentMethod
        exclude = ('user',)

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['user'] = request.user  # Set the user from the request
        return super().create(validated_data)


class UserPaymentTypeSerializer(serializers.ModelSerializer):
    payment_methods = PaymentMethodSerializer(many=True)

    class Meta:
        model = PaymentType
        fields = '__all__'


