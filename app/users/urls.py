from django.urls import path

from .views import ChangePasswordApiView, ForgotPasswordApiView, GoogleLoginApiView, LoginApiView, MeApiView, RefreshTokenApiView, RegisterApiView, ResetPasswordApiView, UserAvatarApiView, UserProfileApiView

urlpatterns = [
    path("register/", RegisterApiView.as_view(), name="users-register"),
    path("login/", LoginApiView.as_view(), name="users-login"),
    path("google-login/", GoogleLoginApiView.as_view(), name="users-google-login"),
    path("password-reset/request/", ForgotPasswordApiView.as_view(), name="users-password-reset-request"),
    path("password-reset/confirm/", ResetPasswordApiView.as_view(), name="users-password-reset-confirm"),
    path("me/", MeApiView.as_view(), name="users-me"),
    path("<uuid:user_id>/avatar/", UserAvatarApiView.as_view(), name="users-avatar"),
    path("<uuid:user_id>/change-password/", ChangePasswordApiView.as_view(), name="users-change-password"),
    path("<uuid:user_id>/", UserProfileApiView.as_view(), name="users-profile"),
    path("token/refresh/", RefreshTokenApiView.as_view(), name="users-token-refresh"),
]
