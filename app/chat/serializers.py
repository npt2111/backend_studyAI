from rest_framework import serializers


class ChatSessionStartSerializer(serializers.Serializer):
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


class ChatSessionQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )


class ChatSessionListSerializer(ChatSessionQuerySerializer):
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=50,
        error_messages={
            "invalid": "limit khong hop le.",
            "min_value": "limit phai lon hon 0.",
            "max_value": "limit toi da la 100.",
        },
    )
    offset = serializers.IntegerField(
        required=False,
        min_value=0,
        default=0,
        error_messages={"invalid": "offset khong hop le."},
    )


class ChatMessageSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    session_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu session_id.",
            "invalid": "session_id khong hop le.",
        }
    )
    message = serializers.CharField(
        max_length=2000,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "Thieu noi dung tin nhan.",
            "blank": "Tin nhan khong duoc de trong.",
            "max_length": "Tin nhan qua dai.",
        },
    )
