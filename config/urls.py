from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health_check(_request):
    return JsonResponse({"status": "ok", "service": "ai-study-assistant-backend"})

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", health_check, name="health-check"),
    path("api/users/", include("app.users.urls")),
    path("api/documents/", include("app.documents.urls")),
    path("api/quiz/", include("app.quiz.urls")),
    path("api/flashcards/", include("app.flashcards.urls")),
    path("api/mindmap/", include("app.mindmap.urls")),
    path("api/planner/", include("app.planner.urls")),
]
