from django.urls import path

from .views import (
    DeleteQuizAttemptApiView,
    FinishQuizAttemptApiView,
    GenerateQuizApiView,
    QuizDetailApiView,
    QuizListApiView,
    QuizShareApiView,
    QuizSharedDetailApiView,
    StartQuizAttemptApiView,
    SubmitQuizAnswerApiView,
)

urlpatterns = [
    path("generate/", GenerateQuizApiView.as_view(), name="quiz-generate"),
    path("items/", QuizListApiView.as_view(), name="quiz-list"),
    path("items/<uuid:quiz_id>/", QuizDetailApiView.as_view(), name="quiz-detail"),
    path("items/<uuid:quiz_id>/share/", QuizShareApiView.as_view(), name="quiz-share"),
    path("share/<str:share_code>/", QuizSharedDetailApiView.as_view(), name="quiz-shared-detail"),
    path("attempts/start/", StartQuizAttemptApiView.as_view(), name="quiz-attempt-start"),
    path("attempts/<uuid:attempt_id>/answer/", SubmitQuizAnswerApiView.as_view(), name="quiz-attempt-answer"),
    path("attempts/<uuid:attempt_id>/finish/", FinishQuizAttemptApiView.as_view(), name="quiz-attempt-finish"),
    path("attempts/<uuid:attempt_id>/", DeleteQuizAttemptApiView.as_view(), name="quiz-attempt-delete"),
]
