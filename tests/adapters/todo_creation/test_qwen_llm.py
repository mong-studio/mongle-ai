from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from adapters.todo_creation.qwen_llm import QwenLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import SplitResult, TaskCandidate


# 검증 대상 기능: Qwen OpenAI 호환 응답 껍데기에서 원문 content 를 꺼낸다.
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
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs
        type(self).last_kwargs = kwargs

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
    """기능별 공통 준비: 모든 Qwen HTTP 호출을 메모리 fake 로 대체한다."""
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.last_kwargs = {}
    monkeypatch.setattr("adapters.todo_creation.qwen_llm.httpx.AsyncClient", _FakeAsyncClient)


def _payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


# 입력 검증/파싱: 유효한 원문 JSON 은 TaskCandidate 목록으로 변환된다.
async def test_split_tasks_parses_valid_json() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "title": "코테",
                                "due_date": "2026-05-24",
                                "tags": ["학습"],
                            },
                            {
                                "title": "발표 준비",
                                "due_date": "2026-05-27",
                                "tags": ["업무"],
                            },
                        ]
                    }
                )
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(
        prompt="오늘 코테, 3일 뒤 발표", today=date(2026, 5, 24)
    )
    assert len(out.tasks) == 2
    assert out.tasks[0].title == "코테"
    assert out.tasks[0].tags == ["학습"]


async def test_complete_raw_uses_configured_timeout() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"ok": true}'))
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1", timeout_seconds=120)
    await llm.complete_raw(
        messages=[{"role": "user", "content": "테스트"}],
        label="timeout_test",
    )

    assert _FakeAsyncClient.last_kwargs["timeout"] == 120


# 프롬프트 계약: today 와 사용자 입력은 user message 에 포함된다.
async def test_split_tasks_sends_today_and_prompt() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({"tasks": []})))
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1", model="Qwen/Qwen2.5-7B-Instruct")
    await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))

    call = _FakeAsyncClient.calls[0]
    serialized = json.dumps(call["json"]["messages"], ensure_ascii=False)
    assert call["endpoint"] == "http://qwen.test/v1/chat/completions"
    assert call["json"]["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert "2026-05-24" in serialized
    assert "오늘 코테" in serialized
    assert "tags" in serialized
    assert "todos.content" in serialized
    assert "schedules.title" in serialized


# 원문 파싱 보정: Qwen 이 코드펜스를 섞어도 JSON 본문만 추출한다.
async def test_split_tasks_strips_code_fence() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                '```json\n{"tasks":[{"title":"운동가기","due_date":"2026-05-24","tags":["건강"]}]}\n```'
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 운동 다녀올거야", today=date(2026, 5, 24))
    assert out.tasks[0].title == "운동가기"


# 재시도: 첫 응답이 JSON 이 아니면 스키마 강화 메시지로 1회 재요청한다.
async def test_split_tasks_retries_once_on_invalid_json() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload("설명: 할 일을 정리했습니다")),
        _FakeResponse(
            _payload(
                '{"tasks":[{"title":"발표 준비","due_date":"2026-05-27","tags":["학습"]}]}'
            )
        ),
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="3일 뒤 발표 준비", today=date(2026, 5, 24))
    assert out.tasks[0].title == "발표 준비"
    assert len(_FakeAsyncClient.calls) == 2
    retry_messages = _FakeAsyncClient.calls[1]["json"]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "스키마" in retry_messages[-1]["content"]
    assert "tags" in retry_messages[-1]["content"]


# 실패 처리: HTTP 오류는 LLMFailedError 로 변환된다.
async def test_split_tasks_wraps_http_error() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [httpx.ConnectError("connection failed")]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    with pytest.raises(LLMFailedError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))


# 실패 처리: 두 번 모두 스키마가 틀리면 LLMOutputError 를 반환한다.
async def test_split_tasks_raises_output_error_after_retry() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"unrelated": []}')),
        _FakeResponse(_payload("not json")),
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    with pytest.raises(LLMOutputError):
        await llm.split_tasks(prompt="x", today=date(2026, 5, 24))


async def test_judge_sufficiency_parses_plan_intent() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "intent": "plan",
                        "is_sufficient": True,
                        "missing_aspects": [],
                        "parsed_goal": {
                            "intent": "plan",
                            "goal_text": "코딩테스트 준비",
                            "goal_tag": "코딩테스트",
                            "deadline": "2026-05-27",
                            "daily_capacity_minutes": 120,
                            "profile_memory_patch": {
                                "preferences": ["실전 문제 선호"]
                            },
                        },
                    },
                    ensure_ascii=False,
                )
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    sufficient, missing, goal = await llm.judge_sufficiency(
        history=[],
        message="3일 뒤 코테 준비",
        today=date(2026, 5, 24),
        user_profile_memory={"preferences": ["저녁 선호"]},
    )

    assert sufficient is True
    assert missing == []
    assert goal["deadline"] == date(2026, 5, 27)
    assert goal["goal_tag"] == "코딩테스트"
    assert goal["profile_memory_patch"]["preferences"] == ["실전 문제 선호"]
    serialized = json.dumps(_FakeAsyncClient.calls[0]["json"]["messages"], ensure_ascii=False)
    assert "저녁 선호" in serialized


async def test_judge_sufficiency_parses_out_of_scope() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                '{"intent":"out_of_scope","is_sufficient":false,'
                '"missing_aspects":[],"parsed_goal":{"intent":"out_of_scope"}}'
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    sufficient, _, goal = await llm.judge_sufficiency(
        history=[], message="오늘 날씨가 뭐야?", today=date(2026, 5, 24)
    )

    assert sufficient is False
    assert goal["intent"] == "out_of_scope"


async def test_generate_follow_up_question_parses_json() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"question":"언제까지 준비해야 하나요?"}'))
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    question = await llm.generate_follow_up_question(
        missing_aspects=["deadline"], history=[]
    )

    assert question == "언제까지 준비해야 하나요?"
    serialized = json.dumps(_FakeAsyncClient.calls[0]["json"]["messages"], ensure_ascii=False)
    assert "이장님" in serialized
    assert "한 번에 하나" in serialized


async def test_generate_plan_parses_days_and_profile_patch() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(
            _payload(
                json.dumps(
                    {
                        "summary_text": "3일 플랜",
                        "profile_memory_patch": {"planning_style": ["짧은 TODO"]},
                        "days": [
                            {
                                "date": "2026-05-24",
                                "tasks": [
                                    {
                                        "title": "개념 복습",
                                        "due_date": "2026-05-24",
                                        "tags": ["학습"],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    parsed_goal = {"goal_text": "코테 준비"}
    summary, days = await llm.generate_plan(
        parsed_goal=parsed_goal, today=date(2026, 5, 24)
    )

    assert summary == "3일 플랜"
    assert days[0]["tasks"][0].title == "개념 복습"
    assert parsed_goal["profile_memory_patch"] == {"planning_style": ["짧은 TODO"]}
    serialized = json.dumps(_FakeAsyncClient.calls[0]["json"]["messages"], ensure_ascii=False)
    assert "전체 tasks 는 12개 이하" in serialized


async def test_generate_goal_tag_parses_structured_tag() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM

    _FakeAsyncClient.responses = [
        _FakeResponse(_payload('{"goal_tag":"회계자격증필기"}'))
    ]

    llm = QwenLLM(base_url="http://qwen.test/v1")
    tag = await llm.generate_goal_tag(
        parsed_goal={"goal_text": "회계 자격증 필기 시험 준비"},
        history=[],
    )

    assert tag == "회계자격증필기"
    serialized = json.dumps(_FakeAsyncClient.calls[0]["json"]["messages"], ensure_ascii=False)
    assert "전체 대화 목표" in serialized
    assert "task 별 태그" in serialized


async def test_split_tasks_returns_split_result_with_plan_intent() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({
            "intent": "plan",
            "tasks": [{"title": "코테", "due_date": "2026-05-24", "tags": ["학습"]}],
        })))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))
    assert isinstance(out, SplitResult)
    assert out.intent == "plan"
    assert out.tasks[0].title == "코테"


async def test_split_tasks_missing_intent_defaults_to_plan() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({
            "tasks": [{"title": "운동가기", "due_date": "2026-05-24", "tags": ["건강"]}],
        })))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="오늘 운동", today=date(2026, 5, 24))
    assert out.intent == "plan"
    assert out.tasks[0].title == "운동가기"


async def test_split_tasks_out_of_scope_returns_empty_tasks() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({"intent": "out_of_scope", "tasks": []})))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    out = await llm.split_tasks(prompt="배고프다", today=date(2026, 5, 24))
    assert out.intent == "out_of_scope"
    assert out.tasks == []


async def test_tag_plan_does_not_call_qwen_and_applies_goal_tag() -> None:
    from adapters.todo_creation.qwen_llm import QwenLLM
    from agents.todo_creation.schemas import TaskCandidate

    llm = QwenLLM(base_url="http://qwen.test/v1")
    days = await llm.tag_plan(
        plan=[
            {
                "date": date(2026, 5, 24),
                "tasks": [TaskCandidate(title="개념 복습", due_date=date(2026, 5, 24))],
            }
        ],
        parsed_goal={"goal_text": "코테 준비", "goal_tag": "코테"},
    )

    assert days[0]["tasks"][0].tags == ["코테"]
    assert _FakeAsyncClient.calls == []


# 후보2(구조화 출력): split_tasks 는 JSON 스키마를 response_format 으로 강제한다.
# 단 PoC 교훈상 한국어를 깨뜨리는 CJK character-class pattern 은 스키마에 없어야 한다.
async def test_split_tasks_sends_json_schema_response_format() -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(_payload(json.dumps({"intent": "plan", "tasks": []})))
    ]
    llm = QwenLLM(base_url="http://qwen.test/v1")
    await llm.split_tasks(prompt="오늘 코테", today=date(2026, 5, 24))

    body = _FakeAsyncClient.calls[0]["json"]
    rf = body.get("response_format")
    assert rf is not None and rf["type"] == "json_schema"
    schema_str = json.dumps(rf["json_schema"]["schema"], ensure_ascii=False)
    assert "intent" in schema_str and "tasks" in schema_str
    assert "pattern" not in schema_str  # CJK pattern 재유입 차단(한국어 손상 방지)
