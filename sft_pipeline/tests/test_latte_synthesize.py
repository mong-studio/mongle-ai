import json
from datetime import date

import pytest

from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.latte.synthesize import (
    build_synthesis_prompt,
    dedup_seeds,
    synthesize_sample,
    synthesize_to_file,
)

TODAY = date(2026, 6, 6)

_SEED = {
    "id": "1",
    "task_title": "buy milk",
    "broad_ko": "외부",
    "place_ko": "마트",
    "times_ko": ["주말 아침"],
}


def _fake_client(content: str):
    class _FakeMsg:
        pass

    _FakeMsg.content = content

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

    return _FakeClient()


def _llm_payload(due="2026-06-07"):
    return json.dumps(
        {
            "user": "주말에 마트에서 우유 사려는데 계획 좀 짜줘.",
            "plan": {
                "summary_text": "주말 아침 마트가 한가해서 추천해요.",
                "todos": [],
                "calendar_events": [
                    {"title": "마트에서 우유 사기", "due_date": due, "tags": ["장보기"]}
                ],
            },
        },
        ensure_ascii=False,
    )


def test_build_synthesis_prompt_contains_seed_fields_and_today():
    prompt = build_synthesis_prompt(_SEED, today=TODAY)
    assert "buy milk" in prompt
    assert "마트" in prompt
    assert "주말 아침" in prompt
    assert "2026-06-06" in prompt  # 날짜 산술 앵커


def test_fallback_is_single_turn_structured_plan():
    """모델 없이 템플릿 폴백 → user/assistant 단일턴 + 정합성 있는 구조화 플랜."""
    sample = synthesize_sample(_SEED, today=TODAY, client=None)
    msgs = sample["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert "마트" in msgs[0]["content"] or "buy milk" in msgs[0]["content"]
    assert "2026-06-06" in msgs[0]["content"]  # 기준일이 user 턴에 노출

    plan = parse_plan(msgs[-1]["content"])
    assert check_plan_consistency(plan, today=TODAY, horizon_days=7) == []

    meta = sample["meta"]
    assert meta["provenance"] == "daily-latte"
    assert meta["source_id"] == "1"
    assert meta["license"] == "MIT"
    assert meta["synthesized_by"] == "template"
    assert meta["task_type"] == "plan"
    assert "turn_type" not in meta
    assert meta["today"] == "2026-06-06"


def test_synthesize_uses_llm_client_when_present():
    """클라이언트가 있으면 {"user","plan"} 응답을 파싱하고 synthesized_by=llm."""
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(_llm_payload()))
    assert sample["meta"]["synthesized_by"] == "llm"
    msgs = sample["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    plan = parse_plan(msgs[-1]["content"])
    assert plan.calendar_events[0].title == "마트에서 우유 사기"


def test_synthesize_falls_back_on_bad_llm_output():
    """LLM이 깨진 출력을 주면 템플릿으로 폴백한다."""
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client("이건 JSON이 아니에요"))
    assert sample["meta"]["synthesized_by"] == "template"


def test_synthesize_falls_back_on_inconsistent_plan():
    """스키마는 맞지만 정합성(7일 지평 밖 날짜)이 깨진 LLM 플랜은 reject → 템플릿 폴백."""
    sample = synthesize_sample(
        _SEED, today=TODAY, client=_fake_client(_llm_payload(due="2026-07-20"))
    )
    assert sample["meta"]["synthesized_by"] == "template"


def test_synthesize_recovers_fenced_json():
    """```json 코드펜스로 감싼 LLM 출력도 파싱해 llm으로 기록."""
    fenced = "```json\n" + _llm_payload() + "\n```"
    sample = synthesize_sample(_SEED, today=TODAY, client=_fake_client(fenced))
    assert sample["meta"]["synthesized_by"] == "llm"


def test_dedup_seeds_by_task_title():
    seeds = [
        {"task_title": "buy milk"},
        {"task_title": "Buy Milk"},
        {"task_title": "walk dog"},
    ]
    out = dedup_seeds(seeds)
    assert len(out) == 2


def _resp(content: str):
    """OpenAI 응답 shape(resp.choices[0].message.content)을 흉내내는 객체."""
    class _Msg:
        pass

    _Msg.content = content

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    return _Resp()


def test_synthesize_passes_request_timeout_to_client():
    """한 요청이 무한 hang 하지 않도록 create()에 timeout 이 전달돼야 한다."""
    captured: dict = {}

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return _resp(_llm_payload())

    synthesize_sample(_SEED, today=TODAY, client=_Client(), request_timeout=12.5)
    assert captured.get("timeout") == 12.5


def test_synthesize_to_file_writes_all_and_returns_counts(tmp_path):
    """모든 시드를 파일로 합성하고 (총개수, {llm,template} 카운트)를 돌려준다."""
    seeds = [dict(_SEED, id=str(i), task_title=f"task {i}") for i in range(2)]
    out = tmp_path / "daily.jsonl"
    total, counts = synthesize_to_file(seeds, out, today=TODAY, client=None, model="x")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert total == 2
    assert len(lines) == 2
    assert counts["template"] == 2
    assert counts["llm"] == 0


def test_synthesize_to_file_concurrent_writes_all(tmp_path):
    """동시처리(concurrency>1)로도 전체를 빠짐없이 기록하고 카운트한다."""
    seeds = [dict(_SEED, id=str(i), task_title=f"task {i}") for i in range(10)]
    out = tmp_path / "daily.jsonl"
    total, counts = synthesize_to_file(
        seeds, out, today=TODAY, client=_fake_client(_llm_payload()), model="x", concurrency=4
    )
    assert total == 10
    assert counts["llm"] == 10
    assert len(out.read_text(encoding="utf-8").splitlines()) == 10


def test_synthesize_to_file_preserves_progress_on_interrupt(tmp_path):
    """3번째 시드 처리 중 KeyboardInterrupt로 죽어도 앞 2건은 파일에 남는다(증분 flush)."""
    seeds = [dict(_SEED, id=str(i), task_title=f"task {i}") for i in range(3)]
    calls = {"n": 0}

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls["n"] += 1
                    if calls["n"] == 3:
                        raise KeyboardInterrupt
                    return _resp(_llm_payload())

    out = tmp_path / "daily.jsonl"
    with pytest.raises(KeyboardInterrupt):
        synthesize_to_file(seeds, out, today=TODAY, client=_Client(), model="x")

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # 중단 시점까지의 진행분 보존
    first = json.loads(lines[0])
    assert first["meta"]["synthesized_by"] == "llm"
