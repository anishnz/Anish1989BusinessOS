"""
JSON authentication API for the React frontend and mobile app.

Uses Django sessions with CSRF protection:
  1. GET  /api/auth/csrf/        sets the csrftoken cookie
  2. POST /api/auth/login/       email + password (send the X-CSRFToken header)
  3. POST /api/auth/mfa/verify/  6-digit code, if the login response says mfa_required
"""
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordResetForm
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django_otp import login as otp_login
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import security
from .models import LoginEvent


def _is_verified(user) -> bool:
    check = getattr(user, "is_verified", None)  # added by django-otp's middleware
    return bool(check()) if callable(check) else False


def auth_state(request) -> dict:
    user = request.user
    must_verify = user.mfa_required or security.has_mfa(user)
    return {
        "user": {
            "id": user.pk,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_staff": user.is_staff,
        },
        "mfa": {
            "required": must_verify,
            "enabled": security.has_mfa(user),
            "verified": _is_verified(user),
            "setup_required": must_verify and not security.has_mfa(user),
            "backup_codes_remaining": security.backup_codes_remaining(user),
        },
    }


class EmailPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=20)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie set."})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        data = EmailPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].strip().lower()
        user = authenticate(request._request, username=email, password=data.validated_data["password"])
        if getattr(request._request, "login_locked_out", False):
            return Response(
                {"detail": "Too many failed attempts. Try again in 15 minutes.", "code": "locked_out"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if user is None:
            # Same message whether the email exists or not.
            return Response({"detail": "Invalid email or password.", "code": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST)
        login(request._request, user)
        request.user = user  # DRF caches the anonymous user from before login
        return Response(auth_state(request))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(auth_state(request))


class MfaVerifyView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    def post(self, request):
        data = TokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if not security.has_mfa(request.user):
            return Response({"detail": "Set up MFA first.", "code": "mfa_setup_required"}, status=status.HTTP_400_BAD_REQUEST)
        device = security.verify_mfa(request.user, data.validated_data["token"])
        if device is None:
            security.record_event(LoginEvent.Event.MFA_FAILED, request._request, user=request.user)
            return Response({"detail": "That code is not valid. Wait a few seconds and try the newest code.", "code": "invalid_token"}, status=status.HTTP_400_BAD_REQUEST)
        otp_login(request._request, device)
        security.record_event(LoginEvent.Event.MFA_SUCCESS, request._request, user=request.user)
        return Response(auth_state(request))


def _may_change_mfa(user) -> bool:
    """A user who already has MFA must be verified before adding or replacing devices."""
    return (not security.has_mfa(user)) or user.is_verified()


class TotpSetupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _may_change_mfa(user):
            return Response({"detail": "Verify with your current MFA first.", "code": "mfa_required"}, status=status.HTTP_403_FORBIDDEN)
        if security.has_totp(user):
            return Response({"detail": "An authenticator app is already set up.", "code": "already_enabled"}, status=status.HTTP_409_CONFLICT)
        device = security.start_totp_setup(user)
        return Response(security.totp_setup_details(device))


class TotpConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    def post(self, request):
        user = request.user
        if not _may_change_mfa(user):
            return Response({"detail": "Verify with your current MFA first.", "code": "mfa_required"}, status=status.HTTP_403_FORBIDDEN)
        data = TokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        device = security.pending_totp_device(user)
        if device is None:
            return Response({"detail": "Start setup first.", "code": "no_pending_setup"}, status=status.HTTP_400_BAD_REQUEST)
        if not security.confirm_totp(device, data.validated_data["token"]):
            return Response({"detail": "That code did not match. Wait a few seconds and try the newest code.", "code": "invalid_token"}, status=status.HTTP_400_BAD_REQUEST)
        device.refresh_from_db()
        otp_login(request._request, device)
        security.record_event(LoginEvent.Event.MFA_ENABLED, request._request, user=user)
        codes = security.create_backup_codes(user)
        security.record_event(LoginEvent.Event.BACKUP_CODES_CREATED, request._request, user=user)
        return Response({**auth_state(request), "backup_codes": codes})


class BackupCodesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not (security.has_mfa(request.user) and request.user.is_verified()):
            return Response({"detail": "Verify with MFA first.", "code": "mfa_required"}, status=status.HTTP_403_FORBIDDEN)
        codes = security.create_backup_codes(request.user)
        security.record_event(LoginEvent.Event.BACKUP_CODES_CREATED, request._request, user=request.user)
        return Response({"backup_codes": codes})


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(APIView):
    """Always answers the same way, so it cannot be used to find out which emails exist."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        data = EmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].strip().lower()
        form = PasswordResetForm(data={"email": email})
        if form.is_valid():
            form.save(request=request._request, use_https=request.is_secure())
        security.record_event(LoginEvent.Event.PASSWORD_RESET_REQUESTED, request._request, email=email)
        return Response({"detail": "If an account exists for that email, a reset link has been sent."})
