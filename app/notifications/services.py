from datetime import date
from typing import Any, Dict, List, Set

from config.services import supabase_client


def build_notifications(*, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 30), 100))
    activity_rows, activity_status = supabase_client.list_study_activities(user_id=user_id, limit=safe_limit)
    task_rows, task_status = supabase_client.list_plan_tasks(user_id=user_id)
    read_ids, read_status = supabase_client.list_notification_read_ids(user_id=user_id)

    if activity_status >= 400:
        raise RuntimeError("Không đọc được hoạt động học tập.")
    if task_status >= 400:
        raise RuntimeError("Không đọc được kế hoạch học tập.")
    if read_status >= 400:
        raise RuntimeError("Không đọc được trạng thái thông báo.")

    read_set = set(read_ids)
    notifications = [_activity_to_notification(row, read_set) for row in activity_rows[:safe_limit]]
    notifications.extend(_task_to_notification(row, read_set) for row in task_rows[:safe_limit])
    notifications = [item for item in notifications if item.get("id")]
    notifications.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return notifications[:safe_limit]


def mark_notification_read(*, user_id: str, notification_id: str) -> Dict[str, Any]:
    row, status_code = supabase_client.mark_notification_read(
        user_id=user_id,
        notification_id=notification_id,
    )
    if status_code >= 400:
        raise RuntimeError("Đánh dấu đã đọc thất bại.")
    return row


def mark_all_notifications_read(*, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    notifications = build_notifications(user_id=user_id, limit=limit)
    unread_ids = [item["id"] for item in notifications if not item.get("is_read")]
    rows, status_code = supabase_client.mark_notifications_read_bulk(
        user_id=user_id,
        notification_ids=unread_ids,
    )
    if status_code >= 400:
        raise RuntimeError("Đánh dấu tất cả đã đọc thất bại.")
    return rows


def unread_count(notifications: List[Dict[str, Any]]) -> int:
    return sum(1 for item in notifications if not item.get("is_read"))


def _activity_to_notification(row: Dict[str, Any], read_set: Set[str]) -> Dict[str, Any]:
    activity_id = str(row.get("id_activity") or "")
    notification_id = f"activity:{activity_id}" if activity_id else ""
    activity_type = str(row.get("activity_type") or "study")
    title = _activity_title(activity_type, str(row.get("title") or "Hoạt động học tập"))
    description = str(row.get("description") or "").strip()
    message = description or _activity_message(activity_type, str(row.get("title") or ""))

    return {
        "id": notification_id,
        "title": title,
        "message": message,
        "type": activity_type,
        "source_type": "activity",
        "source_id": activity_id,
        "created_at": row.get("created_at") or "",
        "is_read": notification_id in read_set,
    }


def _task_to_notification(row: Dict[str, Any], read_set: Set[str]) -> Dict[str, Any]:
    task_id = str(row.get("id_task") or "")
    notification_id = f"plan:{task_id}" if task_id else ""
    task_name = str(row.get("task_name") or "Nhiệm vụ học tập").strip()
    subject = str(row.get("subject") or "").strip()
    task_date = str(row.get("task_date") or "").strip()
    start_time = _short_time(str(row.get("start_time") or ""))
    status = str(row.get("status") or "pending")
    priority = _priority_label(str(row.get("priority") or ""))
    date_label = _date_label(task_date)

    pieces = [piece for piece in [subject, date_label, start_time, priority] if piece]
    if status == "done":
        title = "Kế hoạch đã hoàn thành"
        message = f"Bạn đã hoàn thành: {task_name}"
    else:
        title = "Kế hoạch học tập"
        message = f"{task_name}" + (f" - {', '.join(pieces)}" if pieces else "")

    return {
        "id": notification_id,
        "title": title,
        "message": message,
        "type": "plan",
        "source_type": "plan",
        "source_id": task_id,
        "created_at": row.get("created_at") or "",
        "is_read": notification_id in read_set,
    }


def _activity_title(activity_type: str, fallback: str) -> str:
    return {
        "document": "Tài liệu mới",
        "quiz": "Hoạt động quiz",
        "flashcard": "Hoạt động flashcard",
        "mindmap": "Sơ đồ tư duy",
        "chat": "Chat tài liệu",
        "study": "Hoạt động học tập",
    }.get(activity_type, fallback)


def _activity_message(activity_type: str, title: str) -> str:
    clean_title = title.strip() or "Bạn vừa có hoạt động học tập mới."
    return {
        "document": f"Bạn đã tải hoặc đọc tài liệu: {clean_title}",
        "quiz": f"Bạn vừa làm quiz: {clean_title}",
        "flashcard": f"Bạn vừa học flashcard: {clean_title}",
        "mindmap": f"Bạn vừa tạo sơ đồ tư duy: {clean_title}",
        "chat": f"Bạn vừa chat với tài liệu: {clean_title}",
    }.get(activity_type, clean_title)


def _priority_label(priority: str) -> str:
    return {
        "low": "ưu tiên thấp",
        "medium": "ưu tiên vừa",
        "high": "ưu tiên cao",
    }.get(priority, "")


def _short_time(value: str) -> str:
    if not value:
        return ""
    return value[:5]


def _date_label(value: str) -> str:
    if not value:
        return ""
    today = date.today().isoformat()
    return "hôm nay" if value == today else value
