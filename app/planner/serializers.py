from rest_framework import serializers


class PlanTaskSerializer(serializers.Serializer):
    id_user = serializers.UUIDField()
    task_name = serializers.CharField(max_length=255)
    subject = serializers.CharField(max_length=120, allow_blank=True, required=False)
    task_date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    priority = serializers.ChoiceField(choices=["low", "medium", "high"])
    status = serializers.ChoiceField(choices=["pending", "done"], required=False, default="pending")

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError("Gio ket thuc phai sau gio bat dau.")
        return attrs


class PlanTaskStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "done"])
