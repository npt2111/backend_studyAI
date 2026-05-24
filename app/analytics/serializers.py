from rest_framework import serializers


class UserQuerySerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class CheckinSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
