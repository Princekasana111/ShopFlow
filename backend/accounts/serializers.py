from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import ShopperProfile

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "is_staff"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        validate_password(attrs["password"], user=candidate)
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class ShopperProfileSerializer(serializers.ModelSerializer):
    needs = serializers.CharField(max_length=500, required=False, allow_blank=True)

    class Meta:
        model = ShopperProfile
        fields = ["shoe_size_uk", "clothing_size", "waist_in", "needs", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_needs(self, value):
        from ai import guardrails  # the purchase check sends this text to the LLM

        value = value.strip()
        if value:
            check = guardrails.check_user_message(value)
            if not check.allowed:
                raise serializers.ValidationError(check.reply)
        return value
