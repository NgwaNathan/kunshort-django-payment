from rest_framework import serializers

from kunshort_payment.models import PaymentType, PaymentMethod, PaymentTransaction, PaymentStatus


class PaymentMethodSerializer(serializers.ModelSerializer):
    payment_type = serializers.PrimaryKeyRelatedField(queryset=PaymentType.objects.all())

    class Meta:
        model = PaymentMethod
        exclude = ('user_id',)

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['user_id'] = str(request.user.id)
        return super().create(validated_data)


class UserPaymentTypeSerializer(serializers.ModelSerializer):
    payment_methods = PaymentMethodSerializer(many=True)

    class Meta:
        model = PaymentType
        fields = '__all__'


class PaymentStatusSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PaymentStatus
        fields = ['id', 'status', 'status_display', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'status_display']


class PaymentTransactionSerializer(serializers.ModelSerializer):
    statuses = PaymentStatusSerializer(many=True, read_only=True)
    current_status = serializers.SerializerMethodField()
    payment_type_name = serializers.CharField(source='payment_type.name', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            'id',
            'user_id',
            'order_id',
            'coupon_id',
            'amount',
            'amount_refundable',
            'currency',
            'created_at',
            'updated_at',
            'payment_type',
            'payment_type_name',
            'payment_detail',
            'transaction_id',
            'external_reference',
            'provider',
            'statuses',
            'current_status',
        ]

    def get_current_status(self, obj):
        latest_status = obj.statuses.order_by('-created_at').first()
        return PaymentStatusSerializer(latest_status).data if latest_status else None

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero")
        return value

    def validate_currency(self, value):
        if value not in ['XAF', 'USD', 'EUR']:
            raise serializers.ValidationError("Invalid currency code")
        return value
