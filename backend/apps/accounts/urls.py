from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views

app_name = "accounts"

# Server-rendered pages: /account/...
web_urlpatterns = [
    path("mfa/setup/", views.mfa_setup, name="mfa_setup"),
    path("mfa/verify/", views.mfa_verify, name="mfa_verify"),
]

# JSON API: /api/auth/...
api_urlpatterns = [
    path("csrf/", api.CsrfView.as_view(), name="api_csrf"),
    path("login/", api.LoginView.as_view(), name="api_login"),
    path("logout/", api.LogoutView.as_view(), name="api_logout"),
    path("me/", api.MeView.as_view(), name="api_me"),
    path("mfa/verify/", api.MfaVerifyView.as_view(), name="api_mfa_verify"),
    path("mfa/totp/setup/", api.TotpSetupView.as_view(), name="api_totp_setup"),
    path("mfa/totp/confirm/", api.TotpConfirmView.as_view(), name="api_totp_confirm"),
    path("mfa/backup-codes/", api.BackupCodesView.as_view(), name="api_backup_codes"),
    path("password/reset/", api.PasswordResetRequestView.as_view(), name="api_password_reset"),
]

# Password reset pages (Django's views with the admin's templates).
# The emailed link uses the host the request came in on, so each business's
# users get a link to their own subdomain.
password_reset_urlpatterns = [
    path("admin/password_reset/", auth_views.PasswordResetView.as_view(), name="admin_password_reset"),
    path("account/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("account/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("account/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
