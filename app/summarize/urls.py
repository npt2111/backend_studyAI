from django.urls import path

from .views import (
    RetrySummaryJobApiView,
    StartSummaryJobApiView,
    SummaryJobDetailApiView,
    SummaryJobListApiView,
)

urlpatterns = [
    path("start/", StartSummaryJobApiView.as_view(), name="summary-start"),
    path("jobs/", SummaryJobListApiView.as_view(), name="summary-job-list"),
    path("jobs/<uuid:job_id>/", SummaryJobDetailApiView.as_view(), name="summary-job-detail"),
    path("jobs/<uuid:job_id>/retry/", RetrySummaryJobApiView.as_view(), name="summary-job-retry"),
]
