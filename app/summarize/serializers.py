from rest_framework import serializers


class SummaryStartSerializer(serializers.Serializer):
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


class JobQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )


class JobListQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField(
        error_messages={
            "required": "Thieu user_id.",
            "invalid": "user_id khong hop le.",
        }
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=50,
        default=20,
        error_messages={"invalid": "limit khong hop le."},
    )
