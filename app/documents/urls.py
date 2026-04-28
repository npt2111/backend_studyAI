from django.urls import path

from .views import (
    RetrySummaryJobApiView,
    SummaryJobDetailApiView,
    SummaryJobListApiView,
    UploadDocumentApiView,
)

urlpatterns = [
    path("upload/", UploadDocumentApiView.as_view(), name="documents-upload"),
    path("jobs/", SummaryJobListApiView.as_view(), name="documents-job-list"),
    path("jobs/<uuid:job_id>/", SummaryJobDetailApiView.as_view(), name="documents-job-detail"),
    path("jobs/<uuid:job_id>/retry/", RetrySummaryJobApiView.as_view(), name="documents-job-retry"),
]
