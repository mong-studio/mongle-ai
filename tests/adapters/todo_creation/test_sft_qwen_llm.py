from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError


# 검증 대상: SFT LoRA 플래너 어댑터 — generate_plan 만 학습 분포(단일 user 턴,
# system 없음, 기준일 앵커) 호출로 바꾸고, 출력(GenerateResult 미러 JSON)을
# 파이프라인 PlanDay 목록으로 변환한다. 나머지 역할은 QwenLLM 프롬프트 경로 그대로.
class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, text: str = "", status_error: Exception | None = None) -> None:
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class _FakeAsyncClient:
    responses: list[_FakeResponse | Exception] = []
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, endpoint: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.calls.append({"endpoint": endpoint, "headers": headers, "json": json})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    """기능별 공통 준비: 모든 HTTP 호출을 메모리 fake 로 대체한다.

    SftQwenLLM 은 QwenLLM 을 상속하므로 complete_raw 의 httpx 는
    qwen_llm 모듈 것을 패치한다.
    """
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    monkeypatch.setattr("adapters.todo_creation.qwen_llm.httpx.AsyncClient", _FakeAsyncClient)


def _payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


_PLAN_JSON = json.dumps(
    {
        "summary_text": "옷장 정리 이틀 플랜",
        "todos": [
            {"title": "옷 분류하기", "due_date": "2026-06-07", "tags": ["정리"]},
        ],
        "calendar_events": [
            {"title": "안 입는 옷 기부", "due_date": "2026-06-08", "tags": ["정리"]},
            {"title": "서랍 정리", "due_date": "2026-06-08", "tags": ["정리"]},
        ],
    },
    ensure_ascii=False,
)


# 파싱·변환: SFT 출력(todos/calendar_events)은 due_date 별 PlanDay 로 묶인다.
async def test_generate_plan_parses_sft_output_into_days() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [_FakeResponse(_payload(_PLAN_JSON))]

    llm = SftQwenLLM(base_url="http://sft.test/v1", model="qwen7b-planner-lora")
    summary, days = await llm.generate_plan(
        parsed_goal={"goal_text": "옷장 정리"}, today=date(2026, 6, 7)
    )

    assert summary == "옷장 정리 이틀 플랜"
    assert [d["date"] for d in days] == [date(2026, 6, 7), date(2026, 6, 8)]
    assert [t.title for t in days[0]["tasks"]] == ["옷 분류하기"]
    assert [t.title for t in days[1]["tasks"]] == ["안 입는 옷 기부", "서랍 정리"]


# 프롬프트 계약: 학습 분포와 동일하게 system 없이 단일 user 턴 + 기준일 앵커.
async def test_generate_plan_sends_single_user_turn_without_system() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [_FakeResponse(_payload(_PLAN_JSON))]

    llm = SftQwenLLM(base_url="http://sft.test/v1", model="qwen7b-planner-lora")
    await llm.generate_plan(
        parsed_goal={
            "goal_text": "토익 850",
            "deadline": date(2026, 6, 28),
            "daily_capacity_minutes": 120,
        },
        today=date(2026, 6, 7),
    )

    call = _FakeAsyncClient.calls[0]
    messages = call["json"]["messages"]
    assert call["json"]["model"] == "qwen7b-planner-lora"
    assert [m["role"] for m in messages] == ["user"]
    content = messages[0]["content"]
    assert "토익 850" in content
    assert "2026-06-28" in content
    assert "D-21" in content
    assert "120분" in content
    assert "기준일" in content
    assert "2026-06-07" in content


# 원문 파싱 보정: 코드펜스를 섞어도 JSON 본문만 추출한다.
async def test_generate_plan_strips_code_fence() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(f"```json\n{_PLAN_JSON}\n```"))
    ]

    llm = SftQwenLLM(base_url="http://sft.test/v1")
    summary, days = await llm.generate_plan(
        parsed_goal={"goal_text": "옷장 정리"}, today=date(2026, 6, 7)
    )
    assert summary == "옷장 정리 이틀 플랜"
    assert len(days) == 2


# 재시도: 첫 응답이 파싱 불가면 스키마 강화 메시지로 1회 재요청한다.
async def test_generate_plan_retries_once_on_invalid_json() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload("설명: 계획을 세웠습니다")),
        _FakeResponse(_payload(_PLAN_JSON)),
    ]

    llm = SftQwenLLM(base_url="http://sft.test/v1")
    summary, _ = await llm.generate_plan(
        parsed_goal={"goal_text": "옷장 정리"}, today=date(2026, 6, 7)
    )

    assert summary == "옷장 정리 이틀 플랜"
    assert len(_FakeAsyncClient.calls) == 2
    retry_messages = _FakeAsyncClient.calls[1]["json"]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "todos" in retry_messages[-1]["content"]
    assert "calendar_events" in retry_messages[-1]["content"]


# 실패 처리: 두 번 모두 파싱 불가면 LLMOutputError.
async def test_generate_plan_raises_output_error_after_retry() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload("not json")),
        _FakeResponse(_payload('{"todos": "이상한 형식"}')),
    ]

    llm = SftQwenLLM(base_url="http://sft.test/v1")
    with pytest.raises(LLMOutputError):
        await llm.generate_plan(
            parsed_goal={"goal_text": "x"}, today=date(2026, 6, 7)
        )


# 실패 처리: HTTP 오류는 LLMFailedError 로 변환된다(QwenLLM 상속 경로).
async def test_generate_plan_wraps_http_error() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [httpx.ConnectError("connection failed")]

    llm = SftQwenLLM(base_url="http://sft.test/v1")
    with pytest.raises(LLMFailedError):
        await llm.generate_plan(
            parsed_goal={"goal_text": "x"}, today=date(2026, 6, 7)
        )


# 통합: multi_turn 파이프라인에 꽂아 되묻기 → 답변 → SFT 플랜 생성까지
# 멀티턴 흐름이 관통하는지 확인한다 (LLM 은 전부 scripted fake 응답).
async def test_multi_turn_pipeline_follow_up_then_sft_plan() -> None:
    from datetime import datetime

    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM
    from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts, run
    from agents.todo_creation.schemas import (
        FollowUpResult,
        GenerateResult,
        MultiGenerateInput,
    )

    today = date(2026, 6, 7)
    ports = MultiTurnPorts(llm=SftQwenLLM(base_url="http://sft.test/v1"))

    # 1턴: 정보 부족 → judge(불충분) → follow_up 질문
    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                '{"intent":"plan","is_sufficient":false,"missing_aspects":["deadline"],'
                '"parsed_goal":{"intent":"plan","goal_text":"옷장 정리"}}'
            )
        ),
        _FakeResponse(_payload('{"question":"언제까지 끝내고 싶으세요?"}')),
    ]
    first = await run(
        MultiGenerateInput(user_id="u1", message="옷장 정리하고 싶어", today=today),
        ports=ports,
        now=datetime(2026, 6, 7, 9, 0),
    )
    assert isinstance(first, FollowUpResult)
    assert first.question == "언제까지 끝내고 싶으세요?"

    # 2턴: 답변으로 재개 — interrupt 재개 시 follow_up 노드가 재실행되므로
    # 질문 응답이 한 번 더 소비된 뒤 judge(충분) → goal_tag → SFT generate_plan.
    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"question":"언제까지 끝내고 싶으세요?"}')),
        _FakeResponse(
            _payload(
                '{"intent":"plan","is_sufficient":true,"missing_aspects":[],'
                '"parsed_goal":{"intent":"plan","goal_text":"옷장 정리",'
                '"deadline":"2026-06-08"}}'
            )
        ),
        _FakeResponse(_payload('{"goal_tag":"옷장정리"}')),
        _FakeResponse(_payload(_PLAN_JSON)),
    ]
    second = await run(
        MultiGenerateInput(
            user_id="u1",
            message="내일까지 끝내고 싶어",
            today=today,
            thread_id=first.thread_id,
        ),
        ports=ports,
        now=datetime(2026, 6, 7, 9, 1),
    )
    assert isinstance(second, GenerateResult)
    assert second.thread_id == first.thread_id
    assert second.summary_text == "옷장 정리 이틀 플랜"
    # C5 분기: 오늘 마감은 todos, 미래는 calendar_events
    assert [t.due_date for t in second.todos] == [today]
    assert all(t.due_date > today for t in second.calendar_events)

    # SFT generate_plan 호출(마지막)은 학습 분포대로 system 없는 단일 user 턴이다.
    sft_call_messages = _FakeAsyncClient.calls[-1]["json"]["messages"]
    assert [m["role"] for m in sft_call_messages] == ["user"]
    assert "기준일" in sft_call_messages[0]["content"]


# 상속 계약: generate_plan 외 역할(예: judge_sufficiency)은 QwenLLM
# 프롬프트 경로(system 메시지 포함)를 그대로 쓴다.
async def test_other_roles_keep_prompted_path() -> None:
    from adapters.todo_creation.sft_qwen_llm import SftQwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                '{"intent":"plan","is_sufficient":true,"missing_aspects":[],'
                '"parsed_goal":{"intent":"plan","goal_text":"옷장 정리"}}'
            )
        )
    ]

    llm = SftQwenLLM(base_url="http://sft.test/v1")
    sufficient, _, goal = await llm.judge_sufficiency(
        history=[], message="옷장 정리하고 싶어", today=date(2026, 6, 7)
    )

    assert sufficient is True
    assert goal["goal_text"] == "옷장 정리"
    messages = _FakeAsyncClient.calls[0]["json"]["messages"]
    assert messages[0]["role"] == "system"
