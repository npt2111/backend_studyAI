from django.urls import path

from .views import GenerateMindmapApiView, MindmapByReadApiView

urlpatterns = [
    path("generate/", GenerateMindmapApiView.as_view(), name="mindmap-generate"),
    path("by-read/<uuid:read_id>/", MindmapByReadApiView.as_view(), name="mindmap-by-read"),
]
