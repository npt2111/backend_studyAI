from rest_framework import serializers


class NotificationQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=30)


class NotificationReadSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    notification_id = serializers.CharField(max_length=120)


class NotificationReadAllSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=30)
