import json
from pathlib import Path

from sft_pipeline.build.migrate_meta import migrate_file, migrate_meta, migrate_sample


def _old_daily_meta():
    return {
        "provenance": "daily-latte",
        "turn_type": "single",
        "source_id": "latte-000123",
        "license": "MIT",
        "today": "2026-06-06",
        "synthesized_by": "llm",
    }


def test_adds_task_type_plan_and_drops_turn_type():
    out = migrate_meta(_old_daily_meta())
    assert out["task_type"] == "plan"
    assert "turn_type" not in out
    # 나머지 필드는 그대로 보존
    assert out["source_id"] == "latte-000123"
    assert out["today"] == "2026-06-06"


def test_distractor_becomes_chat_and_drops_is_distractor():
    old = {
        "provenance": "distractor",
        "turn_type": "single",
        "is_distractor": True,
        "distractor_type": "thanks_chitchat",
        "label": "todo",
        "source_id": "1",
    }
    out = migrate_meta(old)
    assert out["task_type"] == "chat"
    assert "is_distractor" not in out
    assert "turn_type" not in out
    assert out["label"] == "todo"  # 계보 보존용 passthrough 는 유지


def test_renames_rephrased_by_to_synthesized_by():
    old = {"provenance": "exam-crawl", "turn_type": "single", "rephrased_by": "template"}
    out = migrate_meta(old)
    assert out["synthesized_by"] == "template"
    assert "rephrased_by" not in out


def test_input_meta_not_mutated():
    old = _old_daily_meta()
    snapshot = dict(old)
    migrate_meta(old)
    assert old == snapshot  # 불변성: 입력은 손대지 않는다


def test_idempotent_on_new_schema():
    once = migrate_meta(_old_daily_meta())
    twice = migrate_meta(once)
    assert twice == once  # 새 스키마에 다시 돌려도 변화 없음


def test_migrate_sample_keeps_messages_identical():
    sample = {
        "messages": [
            {"role": "user", "content": "장보기 계획 짜줘. (기준일: 2026-06-06)"},
            {"role": "assistant", "content": "{\"summary_text\": \"주말 아침 추천이에요.\"}"},
        ],
        "meta": _old_daily_meta(),
    }
    out = migrate_sample(sample)
    assert out["messages"] == sample["messages"]
    assert out["meta"]["task_type"] == "plan"


def test_migrate_file_roundtrip(tmp_path: Path):
    rows = [
        {
            "messages": [
                {"role": "user", "content": "u"},
                {"role": "assistant", "content": "a"},
            ],
            "meta": _old_daily_meta(),
        }
    ]
    src = tmp_path / "old.jsonl"
    dst = tmp_path / "new.jsonl"
    src.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    n = migrate_file(src, dst)
    assert n == 1
    out = [json.loads(line) for line in dst.read_text(encoding="utf-8").splitlines()]
    assert out[0]["meta"]["task_type"] == "plan"
    assert "turn_type" not in out[0]["meta"]
