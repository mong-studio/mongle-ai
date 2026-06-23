from __future__ import annotations

from datetime import date

import pytest

from tests.agents.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TodoInput, TaskCandidate
from agents.todo_creation.todo.nodes.task_splitter import (
    _is_grounded,
    _is_low_information,
    task_splitter_node,
)

# 반복뿐이라 정보가 거의 없는 입력(실측 압축률 ≈0.67 < 0.75 게이트).
DEGENERATE = "건강하고 건강하며 건강한데 또 건강했다가 건강하려다가 건강해야해"


def _input(prompt: str = "오늘 코테") -> TodoInput:
    return TodoInput(user_id="u1", prompt=prompt, today=date(2026, 5, 24))


def _t(title: str = "코테", d: date = date(2026, 5, 24)) -> TaskCandidate:
    return TaskCandidate(title=title, due_date=d)


def _state_and_config(llm: FakeLLM, prompt: str = "오늘 코테") -> tuple[dict, dict]:
    state = {"input": _input(prompt), "now": None}

    class _P:
        pass

    p = _P()
    p.llm = llm
    config = {"configurable": {"ports": p, "now": None}}
    return state, config


async def test_returns_split_tasks_on_happy_path() -> None:
    llm = FakeLLM(responses=[[_t("코테"), _t("발표", date(2026, 5, 27))]])
    state, config = _state_and_config(llm, prompt="코테 발표 준비")
    diff = await task_splitter_node(state, config)
    assert len(diff["split_tasks"]) == 2
    assert diff["split_tasks"][0].title == "코테"


async def test_propagates_llm_failure() -> None:
    llm = FakeLLM(fail_times=1, responses=[[_t()]])
    state, config = _state_and_config(llm)
    with pytest.raises(LLMFailedError):
        await task_splitter_node(state, config)


async def test_empty_response_retries_once() -> None:
    llm = FakeLLM(responses=[[], [_t("재시도 결과")]])
    state, config = _state_and_config(llm, prompt="재시도 결과")
    diff = await task_splitter_node(state, config)
    assert len(diff["split_tasks"]) == 1
    assert llm.calls == 2


async def test_empty_twice_degrades_to_out_of_scope() -> None:
    # 재시도 후에도 빈 결과 = 나눌 수 없는 입력 → 에러가 아니라 친절 안내로 강등.
    llm = FakeLLM(responses=[[], []])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff == {"intent": "out_of_scope"}
    assert llm.calls == 2


async def test_unparseable_output_degrades_to_out_of_scope() -> None:
    # 반복/무의미 입력으로 모델이 끝내 파싱 가능한 분해를 못 냄 → out_of_scope 안내.
    llm = FakeLLM(responses=[[_t()]], output_fail_times=1)
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff == {"intent": "out_of_scope"}
    assert "split_tasks" not in diff


async def test_over_20_tasks_raises_llm_output_error() -> None:
    # 한 문장에서 20개 초과 = 모델 오동작. 그라운딩 이전에 에러로 막는다.
    too_many = [_t(f"t{i}") for i in range(21)]
    llm = FakeLLM(responses=[too_many])
    state, config = _state_and_config(llm)
    with pytest.raises(LLMOutputError):
        await task_splitter_node(state, config)


async def test_node_passes_through_resolved_dates() -> None:
    # 날짜 계산/클램프는 split_tasks(resolver)가 끝낸다. 노드는 그대로 통과.
    future = date(2026, 5, 27)
    llm = FakeLLM(responses=[[_t("발표", future)]])
    state, config = _state_and_config(llm, prompt="발표")
    diff = await task_splitter_node(state, config)
    assert diff["split_tasks"][0].due_date == future


async def test_out_of_scope_sets_intent_and_no_split() -> None:
    llm = FakeLLM(responses=[[]], intents=["out_of_scope"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "out_of_scope"
    assert "split_tasks" not in diff
    assert llm.calls == 1


async def test_plan_intent_sets_split_tasks() -> None:
    llm = FakeLLM(responses=[[_t("코테")]], intents=["plan"])
    state, config = _state_and_config(llm)
    diff = await task_splitter_node(state, config)
    assert diff["intent"] == "plan"
    assert len(diff["split_tasks"]) == 1


# --- 정보량 게이트 (압축률) ---


async def test_low_information_input_skips_llm() -> None:
    # 반복뿐인 입력은 LLM 을 부르지 않고 바로 out_of_scope 안내로.
    llm = FakeLLM(responses=[])  # 호출되면 pop 에서 터진다 → 호출 안 됨을 보장
    state, config = _state_and_config(llm, prompt=DEGENERATE)
    diff = await task_splitter_node(state, config)
    assert diff == {"intent": "out_of_scope"}
    assert llm.calls == 0


def test_is_low_information_separates_degenerate_from_normal() -> None:
    assert _is_low_information(DEGENERATE) is True
    assert _is_low_information("공부 공부 공부 공부 공부해야지") is True
    # 정상 문장(반복 단어가 좀 섞여도)은 통과
    assert _is_low_information("회의 준비하고 회의 자료 만들고 회의실 예약하기") is False
    assert (
        _is_low_information(
            "내일 회의 준비하고 모레까지 보고서 작성하고 금요일에 친구 만나기로 했어"
        )
        is False
    )
    # 너무 짧으면 판정 제외
    assert _is_low_information("코테") is False


# --- 출력 그라운딩 ---


def test_is_grounded_keeps_input_words_drops_hallucination() -> None:
    assert _is_grounded("토익 시험", "내일 토익 시험") is True
    assert _is_grounded("건강하기", "건강하고 건강해야해") is True  # 어간 겹침
    assert _is_grounded("토익 공부", "오늘 코테 발표") is False  # 입력에 없음


async def test_node_drops_ungrounded_task() -> None:
    # 입력에 근거 없는 환각 task('토익')는 떨구고, 근거 있는 것만 남긴다.
    llm = FakeLLM(responses=[[_t("코테"), _t("토익")]])
    state, config = _state_and_config(llm, prompt="코테 준비하기")
    diff = await task_splitter_node(state, config)
    assert [t.title for t in diff["split_tasks"]] == ["코테"]
