from rest_framework import serializers


class QuizGenerateSerializer(serializers.Serializer):
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
    quiz_type = serializers.ChoiceField(
        choices=("multiple_choice", "true_false"),
        error_messages={
            "required": "Thieu quiz_type.",
            "invalid_choice": "quiz_type khong hop le.",
        },
    )
    difficulty = serializers.ChoiceField(
        choices=("easy", "medium", "hard"),
        error_messages={
            "required": "Thieu difficulty.",
            "invalid_choice": "difficulty khong hop le.",
        },
    )
    question_count = serializers.ChoiceField(
        choices=(10, 20, 30),
        error_messages={
            "required": "Thieu question_count.",
            "invalid_choice": "question_count chi co the la 10, 20 hoac 30.",
        },
    )


class QuizQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )


class QuizListQuerySerializer(QuizQuerySerializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        default=20,
        error_messages={"invalid": "limit khong hop le."},
    )


class AttemptStartSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    quiz_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu quiz_id.",
            "invalid": "quiz_id khong hop le.",
        }
    )


class AttemptAnswerSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    question_index = serializers.IntegerField(min_value=0)
    selected_answer = serializers.ChoiceField(choices=("A", "B", "C", "D"))
    elapsed_seconds = serializers.IntegerField(required=False, min_value=0, default=0)


class AttemptFinishSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    elapsed_seconds = serializers.IntegerField(required=False, min_value=0, default=0)


class AttemptDeleteSerializer(QuizQuerySerializer):
    pass
