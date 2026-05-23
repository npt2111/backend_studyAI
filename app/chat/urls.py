from django.urls import path

from .views import DocumentChatSessionApiView, SendDocumentChatMessageApiView, StartDocumentChatApiView

urlpatterns = [
    path("document/start/", StartDocumentChatApiView.as_view(), name="document-chat-start"),
    path("document/message/", SendDocumentChatMessageApiView.as_view(), name="document-chat-message"),
    path("document/sessions/<uuid:session_id>/", DocumentChatSessionApiView.as_view(), name="document-chat-session"),
]
