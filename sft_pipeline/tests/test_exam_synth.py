import collections
import json
from datetime import date

from sft_pipeline.build.exam_synth import (
    EXAM_TYPES,
    build_exam_prompt,
    build_seeds,
    synthesize_sample,
    synthesize_to_file,
    to_user_text,
)
from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.structure.exam_structure import concreteness_ratio

TODAY = date(2026, 6, 6)

_SEED = {
    "exam_type": "토익",
    "goal": "900점",
    "days_left": 14,
    "daily_hours": 3,
    "level": "중급",
    "note": "직장 병행",
}


def test_build_seeds_even_per_type_and_deterministic():
    s1 = build_seeds(1000)
    s2 = build_seeds(1000)
    assert s1 == s2  # 결정론적
    counts = collections.Counter(s["exam_type"] for s in s1)
    assert set(counts) == set(EXAM_TYPES)
    vals = list(counts.values())
    assert max(vals) - min(vals) <= 1  # 종류별 균등(±1)
    assert 994 <= len(s1) <= 1000


def test_to_user_text_has_condition_fields():
    u = to_user_text(_SEED, today=TODAY)
    assert "토익" in u
    assert "D-14" in u
    assert "900점" in u
    assert "2026-06-06" in u  # 기준일 앵커


def test_fallback_is_consistent_exam_plan():
    sample = synthesize_sample(_SEED, today=TODAY, client=None)
    meta = sample["meta"]
    assert meta["provenance"] == "exam-synth"
    assert meta["exam_type"] == "토익"
    assert meta["time_left_days"] == 14
    assert meta["today"] == "2026-06-06"
    assert meta["task_type"] == "plan"
    assert "turn_type" not in meta
    assert meta["synthesized_by"] == "template"
    assert [m["role"] for m in sample["messages"]] == ["user", "assistant"]
    plan = parse_plan(sample["messages"][-1]["content"])
    assert check_plan_consistency(plan, today=TODAY, horizon_days=14) == []


def _fake_client(content: str):
    class _Msg:
        pass

    _Msg.content = content

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _Resp()

    return _Client()


def _plan_payload():
    return json.dumps(
        {
            "summary_text": "기출 회독 후 파트별 약점 보완에 집중하는 전략이에요.",
            "todos": [{"title": "오늘 파트5 집중", "due_date": "2026-06-06", "tags": ["공부"]}],
            "calendar_events": [
                {"title": "LC Part2 기출 풀이", "due_date": "2026-06-08", "tags": ["공부"]},
                {"title": "RC Part7 오답 정리", "due_date": "2026-06-12", "tags": ["공부"]},
            ],
        },
        ensure_ascii=False,
    )


def test_synthesize_uses_llm_client_and_marks_llm():
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(_plan_payload()))
    assert sample["meta"]["synthesized_by"] == "llm"
    plan = parse_plan(sample["messages"][-1]["content"])
    assert plan.calendar_events[0].title == "LC Part2 기출 풀이"


def test_synthesize_falls_back_on_out_of_horizon_plan():
    bad = _plan_payload().replace("2026-06-12", "2026-08-01")  # D-14 밖
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(bad))
    assert sample["meta"]["synthesized_by"] == "template"


def test_build_seeds_include_language_exams():
    """어학 시험(오픽·토플·JLPT)이 시드 풀에 포함되는지 확인."""
    counts = collections.Counter(s["exam_type"] for s in build_seeds(900))
    assert {"오픽", "토플", "JLPT"} <= set(counts)


def test_exam_prompt_injects_structure():
    """합성 프롬프트에 시험 구조(과목/파트)가 주입되는지 확인."""
    prompt = build_exam_prompt(_SEED, today=TODAY, exemplars=[])
    assert "Part5" in prompt  # 토익 공식 구조
    assert "과목/파트/영역명" in prompt  # 구체성 지시


def test_fallback_titles_reference_exam_structure():
    """폴백 템플릿 제목이 시험 구조를 참조하는지 확인 (추상 문구 고정 금지)."""
    sample = synthesize_sample(_SEED, today=TODAY, client=None)
    plan = parse_plan(sample["messages"][-1]["content"])
    titles = [t.title for t in plan.todos] + [e.title for e in plan.calendar_events]
    assert concreteness_ratio(titles, "토익") >= 0.6


def test_synthesize_falls_back_on_abstract_llm_plan():
    """구조 키워드 없는 추상 플랜은 구체성 게이트가 거부하고 템플릿으로 폴백하는지 확인."""
    abstract = json.dumps(
        {
            "summary_text": "기출 중심으로 약점을 보완하는 전략이에요.",
            "todos": [{"title": "기출 문제 1회독", "due_date": "2026-06-06", "tags": ["공부"]}],
            "calendar_events": [
                {"title": "약점 보완", "due_date": "2026-06-08", "tags": ["공부"]},
                {"title": "최종 점검 및 복습", "due_date": "2026-06-12", "tags": ["공부"]},
            ],
        },
        ensure_ascii=False,
    )
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(abstract))
    assert sample["meta"]["synthesized_by"] == "template"


def test_synthesize_to_file_writes_and_counts(tmp_path):
    seeds = build_seeds(12)
    out = tmp_path / "exam_synth.jsonl"
    total, counts = synthesize_to_file(seeds, out, today=TODAY, client=None)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert total == len(seeds)
    assert len(lines) == len(seeds)
    assert counts["template"] == len(seeds)


def test_synthesize_to_file_concurrent_writes_all(tmp_path):
    # 페이로드가 토익 구조 기준이므로 토익 시드만 사용(타 시험은 구체성 게이트에 걸림)
    seeds = [dict(_SEED) for _ in range(12)]
    out = tmp_path / "exam_synth.jsonl"
    total, counts = synthesize_to_file(
        seeds, out, today=TODAY, client=_fake_client(_plan_payload()), model="x", concurrency=4
    )
    assert total == len(seeds)
    assert counts["llm"] == len(seeds)
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(seeds)
