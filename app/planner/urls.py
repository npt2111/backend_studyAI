from django.urls import path

from .views import PlanTaskApiView, PlanTaskDetailApiView, PlanTaskStatusApiView

urlpatterns = [
    path("tasks/", PlanTaskApiView.as_view(), name="planner-tasks"),
    path("tasks/<uuid:task_id>/", PlanTaskDetailApiView.as_view(), name="planner-task-detail"),
    path("tasks/<uuid:task_id>/status/", PlanTaskStatusApiView.as_view(), name="planner-task-status"),
]
