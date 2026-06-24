from django.urls import path

from .views import MarkAllNotificationsReadApiView, MarkNotificationReadApiView, NotificationListApiView

urlpatterns = [
    path("", NotificationListApiView.as_view(), name="notification-list"),
    path("read/", MarkNotificationReadApiView.as_view(), name="notification-read"),
    path("read-all/", MarkAllNotificationsReadApiView.as_view(), name="notification-read-all"),
]
