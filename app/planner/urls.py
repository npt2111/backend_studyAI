from django.urls import path

from .views import FcmTokenApiView, PlanTaskApiView, PlanTaskDetailApiView, PlanTaskStatusApiView, SendDueTaskNotificationsApiView

urlpatterns = [
    path("tasks/", PlanTaskApiView.as_view(), name="planner-tasks"),
    path("tasks/<uuid:task_id>/", PlanTaskDetailApiView.as_view(), name="planner-task-detail"),
    path("tasks/<uuid:task_id>/status/", PlanTaskStatusApiView.as_view(), name="planner-task-status"),
    path("fcm-token/", FcmTokenApiView.as_view(), name="planner-fcm-token"),
    path("send-due-notifications/", SendDueTaskNotificationsApiView.as_view(), name="planner-send-due-notifications"),
]
