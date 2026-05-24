from __future__ import annotations

from datetime import date

TASK_SPLITTER_SYSTEM = """\
당신은 한국어 자연어 입력을 TODO/캘린더 항목 후보로 쪼개는 도우미다.
- 출력은 반드시 다음 JSON 스키마: {"tasks": [{"title": str, "due_date": "YYYY-MM-DD", "time_hint": str | null}]}
- title 은 80자 이하 한국어 (필요시 단축)
- due_date 는 ISO 8601 (YYYY-MM-DD). 상대 표현은 today 기준으로 계산.
- 사용자가 시간대를 명시하면 time_hint 에 자유 텍스트로 보존 (예: "오전", "저녁", "오후 3시"). 없으면 null.
- 자른 task 수는 1개 이상 20개 이하.
- 다른 텍스트, 코드 펜스, 주석 없이 JSON 객체만 출력하라.
"""


def task_splitter_user(prompt: str, today: date) -> str:
    return f"today={today.isoformat()}\n사용자 입력:\n{prompt}"
