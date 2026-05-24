from django.urls import path

from .views import AnalyticsOverviewApiView, DailyCheckinApiView

urlpatterns = [
    path("overview/", AnalyticsOverviewApiView.as_view(), name="analytics-overview"),
    path("checkin/", DailyCheckinApiView.as_view(), name="analytics-checkin"),
]
