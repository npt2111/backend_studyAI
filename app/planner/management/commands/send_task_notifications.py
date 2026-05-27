from django.core.management.base import BaseCommand

from app.planner.notifications import send_due_task_notifications


class Command(BaseCommand):
    help = "Send FCM notifications for due plan tasks."

    def handle(self, *args, **options):
        result = send_due_task_notifications()
        self.stdout.write(self.style.SUCCESS(str(result)))
