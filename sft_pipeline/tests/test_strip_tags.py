import json

from sft_pipeline.build.strip_tags import strip_tags_record


def _plan_record():
    return {
        "messages": [
            {"role": "user", "content": "계획 세워줘 (기준일: 2026-06-08)"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "summary_text": "요약",
                        "todos": [
                            {"title": "할 일", "due_date": "2026-06-08", "tags": ["공부"]}
                        ],
                        "calendar_events": [
                            {"title": "내일 일", "due_date": "2026-06-09", "tags": []}
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "meta": {"provenance": "exam-synth", "task_type": "plan", "today": "2026-06-08"},
    }


def test_strip_removes_tags_from_plan_assistant():
    rec = strip_tags_record(_plan_record())
    asst = rec["messages"][-1]["content"]
    assert '"tags"' not in asst
    assert "할 일" in asst and "내일 일" in asst  # 내용 보존


def test_strip_is_idempotent():
    once = strip_tags_record(_plan_record())
    twice = strip_tags_record(once)
    assert once == twice


def test_strip_keeps_user_meta_and_chat_unchanged():
    rec = _plan_record()
    out = strip_tags_record(rec)
    assert out["messages"][0] == rec["messages"][0]  # user 턴 불변
    assert out["meta"] == rec["meta"]  # meta 불변
    chat = {
        "messages": [
            {"role": "user", "content": "안녕"},
            {"role": "assistant", "content": "안녕하세요, tags 얘기를 해볼까요"},
        ],
        "meta": {"provenance": "distractor", "task_type": "chat"},
    }
    assert strip_tags_record(chat) == chat  # chat 샘플은 손대지 않음
