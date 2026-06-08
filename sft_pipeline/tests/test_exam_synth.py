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


def test_exam_prompt_forbids_exam_name_prefix():
    """20자 낭비 주범인 시험명 접두사('JLPT N1 ...') 금지 지시가 있는지 확인."""
    prompt = build_exam_prompt(_SEED, today=TODAY, exemplars=[])
    assert "시험명" in prompt and "접두사" in prompt


def test_exam_prompt_suggests_phase_sequence():
    """프롬프트가 학습 단계 시퀀스(개념→기출→약점→모의→점검)를 제시하는지 확인."""
    prompt = build_exam_prompt(_SEED, today=TODAY, exemplars=[])
    assert "단계" in prompt
    assert "개념" in prompt and "모의고사" in prompt


def _fake_client_seq(contents: list[str]):
    """호출 순서대로 다른 응답을 돌려주는 페이크 (재시도 검증용)."""
    calls = {"i": 0}

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    content = contents[min(calls["i"], len(contents) - 1)]
                    calls["i"] += 1

                    class _Msg:
                        pass

                    _Msg.content = content

                    class _Choice:
                        message = _Msg()

                    class _Resp:
                        choices = [_Choice()]

                    return _Resp()

    return _Client()


def test_synthesize_retries_llm_before_fallback():
    """1차 시도가 게이트에 거부돼도 2차 시도 성공이면 llm 으로 채택하는지 확인."""
    abstract = _plan_payload().replace("LC Part2 기출 풀이", "약점 보완").replace(
        "RC Part7 오답 정리", "최종 점검"
    ).replace("오늘 파트5 집중", "기출 1회독")
    sample = synthesize_sample(
        _SEED, today=TODAY, client=_fake_client_seq([abstract, _plan_payload()])
    )
    assert sample["meta"]["synthesized_by"] == "llm"


def test_fallback_titles_reference_exam_structure():
    """폴백 템플릿 제목이 시험 구조를 참조하는지 확인 (추상 문구 고정 금지)."""
    sample = synthesize_sample(_SEED, today=TODAY, client=None)
    plan = parse_plan(sample["messages"][-1]["content"])
    titles = [t.title for t in plan.todos] + [e.title for e in plan.calendar_events]
    assert concreteness_ratio(titles, "토익") >= 0.6


def test_phases_for_short_horizon_skips_concept():
    """벼락치기(~D-9)는 개념 단계를 생략하고 기출·모의로 압축한다."""
    from sft_pipeline.build.exam_synth import _phases_for

    labels = [label for label, _ in _phases_for(7)]
    assert not any("개념" in label for label in labels)
    assert any("모의" in label for label in labels)


def test_phases_for_long_horizon_has_two_pastexam_passes():
    """충분한 기간(D-17+)은 개념 + 기출 2회독을 포함한다."""
    from sft_pipeline.build.exam_synth import _phases_for

    labels = [label for label, _ in _phases_for(30)]
    assert any("개념" in label for label in labels)
    assert sum(1 for label in labels if "기출" in label) >= 2


_LONG_SEED = {
    "exam_type": "정보처리기사_필기",
    "goal": "합격",
    "days_left": 30,
    "daily_hours": 3,
    "level": "기초",
    "note": "전업 준비",
}


def test_fallback_orders_concept_before_pastexam():
    """폴백 분해의 순서 논리(M3): 개념 단계가 기출 단계보다 앞 날짜에 온다."""
    sample = synthesize_sample(_LONG_SEED, today=TODAY, client=None)
    plan = parse_plan(sample["messages"][-1]["content"])
    items = [(t.due_date, t.title) for t in plan.todos + plan.calendar_events]
    concept_days = [d for d, t in items if "개념" in t]
    exam_days = [d for d, t in items if "기출" in t]
    assert concept_days and exam_days
    assert max(concept_days) <= min(exam_days)


def test_fallback_keeps_concreteness_and_title_limit():
    """phase×section 폴백도 구체성≥0.6, 제목 20자 제약, 정합성을 만족한다."""
    sample = synthesize_sample(_LONG_SEED, today=TODAY, client=None)
    plan = parse_plan(sample["messages"][-1]["content"])
    titles = [t.title for t in plan.todos] + [e.title for e in plan.calendar_events]
    assert concreteness_ratio(titles, "정보처리기사_필기") >= 0.6
    assert all(len(t) <= 20 for t in titles)
    assert check_plan_consistency(plan, today=TODAY, horizon_days=30) == []


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


def test_outputs_and_prompt_exclude_tags():
    """tags 는 Tagger 노드 책임 — 합성 프롬프트와 출력(폴백·LLM) 모두에서 제외."""
    prompt = build_exam_prompt(_SEED, today=TODAY, exemplars=[])
    assert '"tags"' not in prompt
    fallback = synthesize_sample(_SEED, today=TODAY, client=None)
    assert '"tags"' not in fallback["messages"][-1]["content"]
    llm = synthesize_sample(_SEED, today=TODAY, client=_fake_client(_plan_payload()))
    assert '"tags"' not in llm["messages"][-1]["content"]  # 입력에 있어도 직렬화에서 제거
