from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

from config.services import supabase_client

LOCAL_TZ = timezone(timedelta(hours=7))
DEFAULT_WEEKLY_GOAL_HOURS = 20.0


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _date_to_iso(value: date) -> str:
    return value.isoformat()


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def ensure_weekly_goal(user_id: str, start: date) -> Dict:
    goal_row, goal_status = supabase_client.get_weekly_goal(
        user_id=user_id,
        week_start_date=_date_to_iso(start),
    )
    if goal_status >= 400:
        raise RuntimeError("Khong doc duoc muc tieu tuan.")
    if goal_row:
        return goal_row

    created, create_status = supabase_client.create_weekly_goal(
        user_id=user_id,
        week_start_date=_date_to_iso(start),
        goal_hours=DEFAULT_WEEKLY_GOAL_HOURS,
    )
    if create_status >= 400:
        raise RuntimeError("Khong tao duoc muc tieu tuan mac dinh.")
    return created


def calculate_streak(checkins: List[Dict], today: date) -> int:
    checked_dates = {
        datetime.fromisoformat(str(row.get("checkin_date"))).date()
        for row in checkins
        if row.get("checkin_date")
    }
    streak = 0
    cursor = today
    while cursor in checked_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def normalize_activity(row: Dict) -> Dict:
    activity_type = str(row.get("activity_type") or "study")
    default_titles = {
        "document": "Tài liệu",
        "quiz": "Quiz",
        "flashcard": "Flash Card",
        "mindmap": "Mind Map",
        "chat": "Chat tài liệu",
        "study": "Học tập",
    }
    duration_seconds = _safe_int(row.get("duration_seconds"))
    return {
        "id": row.get("id_activity"),
        "type": activity_type,
        "title": row.get("title") or default_titles.get(activity_type, "Học tập"),
        "description": row.get("description") or "",
        "duration_seconds": duration_seconds,
        "created_at": row.get("created_at"),
    }


def build_overview(user_id: str) -> Dict:
    today = local_today()
    start = week_start(today)
    end = start + timedelta(days=6)
    previous_start = start - timedelta(days=7)
    previous_end = start - timedelta(days=1)

    goal_row = ensure_weekly_goal(user_id, start)
    goal_hours = _safe_float(goal_row.get("goal_hours"), DEFAULT_WEEKLY_GOAL_HOURS)

    week_rows, week_status = supabase_client.list_study_activities(
        user_id=user_id,
        start_date=_date_to_iso(start),
        end_date=_date_to_iso(end),
        limit=500,
    )
    if week_status >= 400:
        raise RuntimeError("Khong lay duoc hoat dong tuan nay.")

    previous_rows, previous_status = supabase_client.list_study_activities(
        user_id=user_id,
        start_date=_date_to_iso(previous_start),
        end_date=_date_to_iso(previous_end),
        limit=500,
    )
    if previous_status >= 400:
        raise RuntimeError("Khong lay duoc hoat dong tuan truoc.")

    recent_rows, recent_status = supabase_client.list_study_activities(user_id=user_id, limit=5)
    if recent_status >= 400:
        raise RuntimeError("Khong lay duoc hoat dong gan day.")

    checkins, checkin_status = supabase_client.list_daily_checkins(
        user_id=user_id,
        start_date=_date_to_iso(today - timedelta(days=370)),
        end_date=_date_to_iso(today),
    )
    if checkin_status >= 400:
        raise RuntimeError("Khong lay duoc chuoi hoc.")

    document_count, document_status = supabase_client.count_document_read_results(user_id=user_id)
    if document_status >= 400:
        raise RuntimeError("Khong lay duoc so tai lieu.")

    daily_seconds = {start + timedelta(days=index): 0 for index in range(7)}
    for row in week_rows:
        raw_date = row.get("activity_date")
        if not raw_date:
            continue
        activity_date = datetime.fromisoformat(str(raw_date)).date()
        if activity_date in daily_seconds:
            daily_seconds[activity_date] += _safe_int(row.get("duration_seconds"))

    week_seconds = sum(_safe_int(row.get("duration_seconds")) for row in week_rows)
    previous_seconds = sum(_safe_int(row.get("duration_seconds")) for row in previous_rows)
    studied_hours = round(week_seconds / 3600, 1)
    percent = round(min(100.0, (studied_hours / max(goal_hours, 0.1)) * 100))
    if previous_seconds <= 0:
        growth_percent = 100.0 if week_seconds > 0 else 0.0
    else:
        growth_percent = round(((week_seconds - previous_seconds) / previous_seconds) * 100, 1)

    return {
        "weekly_goal": {
            "studied_hours": studied_hours,
            "goal_hours": goal_hours,
            "progress_percent": percent,
            "week_start_date": _date_to_iso(start),
            "week_end_date": _date_to_iso(end),
        },
        "activity_chart": [
            {
                "date": _date_to_iso(day),
                "day_label": ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][index],
                "hours": round(seconds / 3600, 2),
            }
            for index, (day, seconds) in enumerate(daily_seconds.items())
        ],
        "growth_percent": growth_percent,
        "streak_days": calculate_streak(checkins, today),
        "document_count": document_count,
        "recent_activities": [normalize_activity(row) for row in recent_rows],
    }
