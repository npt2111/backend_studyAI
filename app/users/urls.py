from django.urls import path

from .views import LoginApiView, MeApiView, RefreshTokenApiView, RegisterApiView

urlpatterns = [
    path("register/", RegisterApiView.as_view(), name="users-register"),
    path("login/", LoginApiView.as_view(), name="users-login"),
    path("me/", MeApiView.as_view(), name="users-me"),
    path("token/refresh/", RefreshTokenApiView.as_view(), name="users-token-refresh"),
]
