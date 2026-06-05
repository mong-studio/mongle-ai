import json

from sft_pipeline.build.validate_dataset import validate_samples
from sft_pipeline.latte.synthesize import (
    build_synthesis_prompt,
    dedup_seeds,
    synthesize_dialogue,
)

_SEED = {
    "id": "1",
    "task_title": "buy milk",
    "broad_ko": "외부",
    "place_ko": "마트",
    "times_ko": ["주말 아침"],
}


def test_build_synthesis_prompt_contains_seed_fields():
    prompt = build_synthesis_prompt(_SEED)
    assert "buy milk" in prompt
    assert "마트" in prompt
    assert "주말 아침" in prompt


def test_fallback_dialogue_is_valid_multiturn(tmp_path):
    """모델 없이 템플릿 폴백 → user/assistant 4턴, provenance=daily-latte, validate 통과."""
    sample = synthesize_dialogue(_SEED, client=None)
    msgs = sample["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert sample["meta"]["provenance"] == "daily-latte"
    assert sample["meta"]["source_id"] == "1"
    assert sample["meta"]["license"] == "MIT"
    assert sample["meta"]["synthesized_by"] == "template"
    # 장소가 대화에 반영되어야 한다
    assert any("마트" in m["content"] for m in msgs)

    # 산출물이 통일 validate 스키마를 통과해야 한다
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")
    report = validate_samples(path)
    assert report["ok"] == 1, report["errors"]


def test_synthesize_uses_llm_client_when_present():
    """클라이언트가 있으면 LLM 응답(JSON messages)을 파싱하고 synthesized_by=llm."""

    class _FakeMsg:
        content = json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "마트에서 우유 사야 하는데 언제가 좋아?"},
                    {"role": "assistant", "content": "주말 아침에 마트 들르는 걸 추천해요."},
                ]
            },
            ensure_ascii=False,
        )

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeResp()

    sample = synthesize_dialogue(_SEED, client=_FakeClient(), model="local")
    assert sample["meta"]["synthesized_by"] == "llm"
    assert sample["messages"][-1]["role"] == "assistant"
    assert "마트" in sample["messages"][0]["content"]


def test_synthesize_falls_back_on_bad_llm_output():
    """LLM이 깨진 출력을 주면 템플릿으로 폴백한다."""

    class _FakeMsg:
        content = "이건 JSON이 아니에요"

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _FakeResp()

    sample = synthesize_dialogue(_SEED, client=_FakeClient(), model="local")
    assert sample["meta"]["synthesized_by"] == "template"


def test_dedup_seeds_by_task_title():
    seeds = [
        {"task_title": "buy milk"},
        {"task_title": "Buy Milk"},
        {"task_title": "walk dog"},
    ]
    out = dedup_seeds(seeds)
    assert len(out) == 2
