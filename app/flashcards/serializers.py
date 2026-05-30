from rest_framework import serializers


class FlashcardGenerateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    read_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu read_id.",
            "invalid": "read_id khong hop le.",
        }
    )
    difficulty = serializers.ChoiceField(
        choices=("easy", "medium", "hard"),
        error_messages={
            "required": "Thieu difficulty.",
            "invalid_choice": "difficulty khong hop le.",
        },
    )
    card_count = serializers.ChoiceField(
        choices=(10, 20, 30),
        error_messages={
            "required": "Thieu card_count.",
            "invalid_choice": "card_count chi co the la 10, 20 hoac 30.",
        },
    )


class FlashcardQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )


class FlashcardListQuerySerializer(FlashcardQuerySerializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        default=20,
        error_messages={"invalid": "limit khong hop le."},
    )


class FlashcardAttemptStartSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    flashcard_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu flashcard_id.",
            "invalid": "flashcard_id khong hop le.",
        }
    )


class FlashcardAttemptProgressSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    current_index = serializers.IntegerField(min_value=0)
    viewed_count = serializers.IntegerField(min_value=0)
    elapsed_seconds = serializers.IntegerField(required=False, min_value=0, default=0)


class FlashcardAttemptFinishSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    elapsed_seconds = serializers.IntegerField(required=False, min_value=0, default=0)


class FlashcardShareCodeSerializer(serializers.Serializer):
    share_code = serializers.CharField(
        max_length=32,
        error_messages={
            "required": "Thieu share_code.",
            "blank": "share_code khong duoc rong.",
        },
    )


class FlashcardSaveSharedSerializer(FlashcardQuerySerializer):
    pass
