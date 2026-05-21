from django.urls import path

from .views import (
    DocumentReadResultDetailApiView,
    DocumentReadResultListApiView,
    UploadDocumentApiView,
)

urlpatterns = [
    path("upload/", UploadDocumentApiView.as_view(), name="documents-upload"),
    path("reads/", DocumentReadResultListApiView.as_view(), name="documents-read-list"),
    path("reads/<uuid:read_id>/", DocumentReadResultDetailApiView.as_view(), name="documents-read-detail"),
]
