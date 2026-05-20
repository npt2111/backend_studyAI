from django.urls import path

from .views import LoginApiView, MeApiView, RefreshTokenApiView, RegisterApiView, UserAvatarApiView, UserProfileApiView

urlpatterns = [
    path("register/", RegisterApiView.as_view(), name="users-register"),
    path("login/", LoginApiView.as_view(), name="users-login"),
    path("me/", MeApiView.as_view(), name="users-me"),
    path("<uuid:user_id>/avatar/", UserAvatarApiView.as_view(), name="users-avatar"),
    path("<uuid:user_id>/", UserProfileApiView.as_view(), name="users-profile"),
    path("token/refresh/", RefreshTokenApiView.as_view(), name="users-token-refresh"),
]
