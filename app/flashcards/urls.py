from django.urls import path

from .views import (
    FinishFlashcardAttemptApiView,
    FlashcardDetailApiView,
    GenerateFlashcardApiView,
    StartFlashcardAttemptApiView,
    UpdateFlashcardAttemptApiView,
)

urlpatterns = [
    path("generate/", GenerateFlashcardApiView.as_view(), name="flashcard-generate"),
    path("items/<uuid:flashcard_id>/", FlashcardDetailApiView.as_view(), name="flashcard-detail"),
    path("attempts/start/", StartFlashcardAttemptApiView.as_view(), name="flashcard-attempt-start"),
    path("attempts/<uuid:attempt_id>/progress/", UpdateFlashcardAttemptApiView.as_view(), name="flashcard-attempt-progress"),
    path("attempts/<uuid:attempt_id>/finish/", FinishFlashcardAttemptApiView.as_view(), name="flashcard-attempt-finish"),
]
