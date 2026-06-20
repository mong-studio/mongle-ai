"""exam_synth 도메인 전략 주입 검증.

토익 등 각 시험종류에 대해 LLM 프롬프트와 템플릿 폴백 요약이 일반 '기출 회독'을
넘어 시험 구조(LC/RC·파트)에 맞는 전략 힌트를 담는지 본다.
"""
from datetime import date

from sft_pipeline.build.lib.exam_synth import (
    EXAM_STRATEGY,
    EXAM_TYPES,
    build_exam_prompt,
    synthesize_sample,
)

TODAY = date(2026, 6, 14)
_TOEIC_SEED = {
    "exam_type": "토익",
    "goal": "800점",
    "days_left": 14,
    "daily_hours": 3,
    "level": "중급",
    "note": "직장 병행",
}


def test_every_exam_type_has_strategy():
    assert set(EXAM_STRATEGY) >= set(EXAM_TYPES)


def test_toeic_strategy_is_domain_specific():
    s = EXAM_STRATEGY["토익"]
    assert "LC" in s and "RC" in s
    assert "Part" in s


def test_prompt_injects_toeic_strategy():
    prompt = build_exam_prompt(_TOEIC_SEED, today=TODAY, exemplars=[])
    assert "공략 힌트" in prompt
    assert EXAM_STRATEGY["토익"] in prompt


def test_template_fallback_summary_uses_toeic_strategy():
    sample = synthesize_sample(_TOEIC_SEED, today=TODAY, client=None)
    summary = sample["messages"][-1]["content"]
    assert "LC" in summary and "RC" in summary
