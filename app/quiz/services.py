import json
import re
from typing import Any, Dict, List

import requests
from django.conf import settings


QUIZ_SYSTEM_PROMPT = """
Ban la cong cu tao quiz hoc tap bang tieng Viet. Chi tao cau hoi dua tren noi dung tai lieu duoc cung cap, khong bia them thong tin.
Tra ve JSON thuan, khong markdown, khong giai thich ngoai JSON.
""".strip()


def normalize_quiz(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    questions = row.get("questions")
    return {
        "id": row.get("id_quiz"),
        "id_quiz": row.get("id_quiz"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "file_name": row.get("file_name"),
        "quiz_type": row.get("quiz_type"),
        "difficulty": row.get("difficulty"),
        "question_count": int(row.get("question_count") or 0),
        "status": row.get("status"),
        "questions": questions if isinstance(questions, list) else [],
        "error": row.get("error_message"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "latest_attempt": normalize_attempt(row.get("latest_attempt") or {}) if row.get("latest_attempt") else None,
    }


def normalize_attempt(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    answers = row.get("answers")
    return {
        "id": row.get("id_attempt"),
        "id_attempt": row.get("id_attempt"),
        "quiz_id": row.get("id_quiz"),
        "user_id": row.get("id_user"),
        "read_id": row.get("id_read"),
        "status": row.get("status"),
        "answers": answers if isinstance(answers, list) else [],
        "correct_count": int(row.get("correct_count") or 0),
        "wrong_count": int(row.get("wrong_count") or 0),
        "total_questions": int(row.get("total_questions") or 0),
        "completion_percent": float(row.get("completion_percent") or 0),
        "elapsed_seconds": int(row.get("elapsed_seconds") or 0),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def build_attempt_answer(
    *,
    quiz_row: Dict[str, Any],
    question_index: int,
    selected_answer: str,
) -> Dict[str, Any]:
    questions = quiz_row.get("questions")
    if not isinstance(questions, list) or question_index >= len(questions):
        raise RuntimeError("question_index khong hop le.")

    question = questions[question_index] if isinstance(questions[question_index], dict) else {}
    correct_answer = str(question.get("correct_answer") or "").strip().upper()
    selected = str(selected_answer or "").strip().upper()
    if selected not in {"A", "B", "C", "D"}:
        raise RuntimeError("selected_answer khong hop le.")
    if not correct_answer:
        raise RuntimeError("Quiz thieu correct_answer.")

    return {
        "question_index": question_index,
        "question_number": question_index + 1,
        "selected_answer": selected,
        "correct_answer": correct_answer,
        "is_correct": selected == correct_answer,
    }


def merge_attempt_answer(existing_answers: Any, answer: Dict[str, Any]) -> List[Dict[str, Any]]:
    answers = existing_answers if isinstance(existing_answers, list) else []
    merged = [
        item for item in answers
        if not (isinstance(item, dict) and int(item.get("question_index", -1)) == answer["question_index"])
    ]
    merged.append(answer)
    return sorted(merged, key=lambda item: int(item.get("question_index", 0)))


def calculate_attempt_stats(answers: List[Dict[str, Any]], total_questions: int) -> Dict[str, Any]:
    correct = sum(1 for item in answers if isinstance(item, dict) and bool(item.get("is_correct")))
    answered = len([item for item in answers if isinstance(item, dict)])
    wrong = max(0, answered - correct)
    percent = round((answered / max(total_questions, 1)) * 100, 2)
    return {
        "correct_count": correct,
        "wrong_count": wrong,
        "completion_percent": percent,
    }


def build_learning_recommendations(
    *,
    quiz_row: Dict[str, Any],
    attempt_row: Dict[str, Any],
) -> Dict[str, Any]:
    answers = attempt_row.get("answers") if isinstance(attempt_row.get("answers"), list) else []
    questions = quiz_row.get("questions") if isinstance(quiz_row.get("questions"), list) else []
    total = int(attempt_row.get("total_questions") or len(questions) or 0)
    correct = int(attempt_row.get("correct_count") or 0)
    completion = float(attempt_row.get("completion_percent") or 0)
    accuracy = round((correct / max(total, 1)) * 100, 2)

    wrong_questions: List[Dict[str, Any]] = []
    for answer in answers:
        if not isinstance(answer, dict) or bool(answer.get("is_correct")):
            continue
        index = int(answer.get("question_index", -1))
        question = questions[index] if 0 <= index < len(questions) and isinstance(questions[index], dict) else {}
        wrong_questions.append(
            {
                "question_index": index,
                "question_number": int(answer.get("question_number") or index + 1),
                "question": str(question.get("question") or ""),
                "selected_answer": str(answer.get("selected_answer") or ""),
                "correct_answer": str(answer.get("correct_answer") or ""),
                "explanation": str(question.get("explanation") or ""),
            }
        )

    recommendations: List[Dict[str, str]] = []
    if accuracy < 50:
        recommendations.append(
            {
                "type": "retake_quiz",
                "title": "Lam lai quiz",
                "message": "Diem duoi 50%, ban nen lam lai quiz de cung co kien thuc.",
            }
        )
        recommendations.append(
            {
                "type": "create_flashcard",
                "title": "Tao flashcard on tap",
                "message": "Hay tao flashcard tu tai lieu nay de ghi nho cac y con yeu.",
            }
        )
    if completion < 80:
        recommendations.append(
            {
                "type": "continue_learning",
                "title": "Tiep tuc hoc",
                "message": "Ban chua hoan thanh het quiz, nen tiep tuc hoc cac cau con lai.",
            }
        )
    if wrong_questions:
        recommendations.append(
            {
                "type": "review_wrong_questions",
                "title": "On lai cau sai",
                "message": f"Ban sai {len(wrong_questions)} cau. Hay xem lai danh sach cau sai va phan giai thich.",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "type": "keep_practicing",
                "title": "Duy tri luyen tap",
                "message": "Ket qua tot. Ban co the tao quiz kho hon hoac tiep tuc on tap bang flashcard.",
            }
        )

    return {
        "accuracy_percent": accuracy,
        "recommendations": recommendations,
        "wrong_questions": wrong_questions,
    }


def generate_quiz_questions(
    *,
    source_text: str,
    quiz_type: str,
    difficulty: str,
    question_count: int,
) -> Dict[str, Any]:
    api_key = str(getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY chua duoc cau hinh.")

    source = (source_text or "").strip()
    if not source:
        raise RuntimeError("Khong co noi dung tai lieu de tao quiz.")

    max_chars = int(getattr(settings, "QUIZ_SOURCE_MAX_CHARS", 16000))
    source = source[:max_chars]

    schema_instruction = _schema_instruction(quiz_type=quiz_type, question_count=question_count)
    user_prompt = f"""
Loai quiz: {quiz_type}
Do kho: {difficulty}
So cau: {question_count}

Yeu cau:
{schema_instruction}
- Moi cau co explanation ngan gon giai thich vi sao dap an dung.
- correct_answer phai la key dap an dung.
- Noi dung cau hoi va explanation viet bang tieng Viet.
- Khong duoc lap lai y/cau hoi; moi cau phai kiem tra mot y khac nhau trong tai lieu.
- Khong duoc bia dat thong tin ngoai tai lieu. Neu tai lieu khong du thong tin de tao du so cau hop le, hay tao cac cau o muc tong quat nhung van phai dua tren noi dung co trong tai lieu.

Tai lieu:
{source}
""".strip()

    payload = {
        "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
        "messages": [
            {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "response_format": {"type": "json_object"},
    }

    base_url = str(getattr(settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1")).rstrip("/")
    timeout = int(getattr(settings, "GROQ_TIMEOUT_SECONDS", 120))
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq loi {response.status_code}: {response.text[:500]}")

    data = response.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    content = ""
    if choices:
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("Groq tra ve noi dung rong.")

    parsed = _parse_json(content)
    questions = _sanitize_questions(
        parsed.get("questions") if isinstance(parsed, dict) else None,
        quiz_type=quiz_type,
        question_count=question_count,
    )
    if len(questions) != question_count:
        raise RuntimeError(f"Groq tao {len(questions)}/{question_count} cau hoi hop le.")
    if quiz_type == "true_false":
        answer_keys = {str(item.get("correct_answer") or "").upper() for item in questions}
        min_false_count = max(1, question_count // 3)
        false_count = sum(1 for item in questions if str(item.get("correct_answer") or "").upper() == "B")
        if answer_keys != {"A", "B"} or false_count < min_false_count:
            raise RuntimeError("Groq tao quiz Dung/Sai bi lech: phai co ca dap an Dung va Sai.")
    return {
        "questions": questions,
        "raw_response": content,
    }


def _schema_instruction(*, quiz_type: str, question_count: int) -> str:
    if quiz_type == "true_false":
        return f"""
Tra ve dung schema:
{{"questions":[{{"question":"Ti the la noi dien ra qua trinh ho hap te bao.","options":[{{"key":"A","text":"Đúng"}},{{"key":"B","text":"Sai"}}],"correct_answer":"A","explanation":"Theo tai lieu, ti the tham gia tao nang luong qua ho hap te bao."}}]}}
questions co dung {question_count} phan tu.
True/False chi co 2 dap an co dinh: A = "Đúng", B = "Sai".
Truong "question" bat buoc la mot menh de khang dinh co the danh gia Dung/Sai, khong phai cau hoi mo, khong phai cau hoi co 4 lua chon.
Phai co ca menh de dung va menh de sai. Khong duoc de tat ca correct_answer la "A".
Ty le dap an nen gan 50/50: voi {question_count} cau, it nhat {max(1, question_count // 3)} cau phai co correct_answer = "B".
Menh de dung: viet lai mot thong tin dung trong tai lieu, correct_answer = "A".
Menh de sai: sua doi mot chi tiet quan trong trong tai lieu de menh de tro thanh sai ro rang, correct_answer = "B".
Moi menh de phai dua truc tiep tren tai lieu; khi tao menh de sai, chi duoc doi mot chi tiet co trong tai lieu mot cach ro rang va khong gay mo ho.
Khong lap lai menh de, khong lap lai cung mot y bang cach doi tu ngu nhe.
Khong bia dat kien thuc ngoai tai lieu.
""".strip()
    return f"""
Tra ve dung schema:
{{"questions":[{{"question":"...","options":[{{"key":"A","text":"..."}},{{"key":"B","text":"..."}},{{"key":"C","text":"..."}},{{"key":"D","text":"..."}}],"correct_answer":"A","explanation":"..."}}]}}
questions co dung {question_count} phan tu.
Multiple choice bat buoc co 4 dap an A, B, C, D va chi 1 dap an dung.
Dap an khong duoc trung lap.
Khong lap lai cau hoi, khong bia dat thong tin ngoai tai lieu.
""".strip()


def _parse_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    candidate = match.group(0) if match else text
    return json.loads(candidate)


def _sanitize_questions(raw_questions: Any, *, quiz_type: str, question_count: int) -> List[Dict[str, Any]]:
    if not isinstance(raw_questions, list):
        return []

    expected_keys = ["A", "B"] if quiz_type == "true_false" else ["A", "B", "C", "D"]
    questions: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        correct_answer = str(item.get("correct_answer") or "").strip().upper()
        options = _sanitize_options(item.get("options"), expected_keys=expected_keys, quiz_type=quiz_type)
        if not question or not explanation or correct_answer not in expected_keys:
            continue
        if len(options) != len(expected_keys):
            continue
        questions.append({
            "number": index,
            "question": question,
            "options": options,
            "correct_answer": correct_answer,
            "explanation": explanation,
        })
        if len(questions) == question_count:
            break
    return questions


def _sanitize_options(raw_options: Any, *, expected_keys: List[str], quiz_type: str) -> List[Dict[str, str]]:
    if quiz_type == "true_false":
        return [
            {"key": "A", "text": "Đúng"},
            {"key": "B", "text": "Sai"},
        ]
    if not isinstance(raw_options, list):
        return []

    by_key: Dict[str, str] = {}
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        key = str(option.get("key") or "").strip().upper()
        text = str(option.get("text") or "").strip()
        if key in expected_keys and text:
            by_key[key] = text
    return [{"key": key, "text": by_key[key]} for key in expected_keys if key in by_key]
