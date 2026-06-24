from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from app.chat.views import DocumentChatSessionApiView, SendDocumentChatMessageApiView, StartDocumentChatApiView


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
    path("api/chat/", include("app.chat.urls")),
    path("api/chat/document/start/", StartDocumentChatApiView.as_view(), name="document-chat-start-direct"),
    path("api/chat/document/message/", SendDocumentChatMessageApiView.as_view(), name="document-chat-message-direct"),
    path("api/chat/document/sessions/<uuid:session_id>/", DocumentChatSessionApiView.as_view(), name="document-chat-session-direct"),
    path("api/planner/", include("app.planner.urls")),
    path("api/analytics/", include("app.analytics.urls")),
    path("api/notifications/", include("app.notifications.urls")),
]
