from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import ShopperProfile
from .serializers import RegisterSerializer, ShopperProfileSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class PreferencesView(APIView):
    """GET or PUT the signed-in shopper's saved sizes and standing needs (used by the purchase check)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile = ShopperProfile.objects.filter(user=request.user).first() or ShopperProfile(user=request.user)
        return Response(ShopperProfileSerializer(profile).data)

    def put(self, request):
        profile, _ = ShopperProfile.objects.get_or_create(user=request.user)
        serializer = ShopperProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
