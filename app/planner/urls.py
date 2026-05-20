from django.urls import path

from .views import PlanTaskApiView

urlpatterns = [
    path("tasks/", PlanTaskApiView.as_view(), name="planner-tasks"),
]
