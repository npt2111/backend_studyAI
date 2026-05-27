import json
from typing import Dict, Tuple

import firebase_admin
from django.conf import settings
from firebase_admin import credentials, messaging

from config.services import supabase_client


def _firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    raw_json = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_json:
        raise RuntimeError("Thieu FIREBASE_SERVICE_ACCOUNT_JSON.")

    info = json.loads(raw_json)
    cred = credentials.Certificate(info)
    return firebase_admin.initialize_app(cred)


def send_due_task_notifications() -> Dict[str, int]:
    _firebase_app()
    tasks, task_status = supabase_client.list_due_plan_tasks()
    if task_status >= 400:
        return {"checked": 0, "sent": 0, "failed": 0}

    sent = 0
    failed = 0
    for task in tasks:
        tokens, token_status = supabase_client.list_active_fcm_tokens(str(task.get("id_user") or ""))
        if token_status >= 400 or not tokens:
            failed += 1
            continue

        title = "Den gio hoc roi"
        subject = (task.get("subject") or "").strip()
        task_name = (task.get("task_name") or "Ban co nhiem vu can lam").strip()
        body = f"{task_name}" + (f" - {subject}" if subject else "")

        delivered = _send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data={
                "type": "task_reminder",
                "id_task": str(task.get("id_task") or ""),
            },
        )
        sent += delivered[0]
        failed += delivered[1]
        if delivered[0] > 0:
            supabase_client.mark_plan_task_reminder_sent(str(task.get("id_task")))

    return {"checked": len(tasks), "sent": sent, "failed": failed}


def _send_to_tokens(*, tokens, title: str, body: str, data: Dict[str, str]) -> Tuple[int, int]:
    sent = 0
    failed = 0
    for row in tokens:
        token = str(row.get("token") or "").strip()
        if not token:
            continue
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data=data,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="task_reminder_channel",
                    priority="high",
                    sound="default",
                ),
            ),
        )
        try:
            messaging.send(message)
            sent += 1
        except messaging.UnregisteredError:
            supabase_client.deactivate_fcm_token(token)
            failed += 1
        except Exception:
            failed += 1
    return sent, failed
