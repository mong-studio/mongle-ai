from __future__ import annotations

from datetime import date

import pytest

from tests.agents.todo_creation.fake_llm import FakeLLM
from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.schemas import TodoInput, TaskCandidate
from agents.todo_creation.todo.nodes.task_splitter import (
    _is_grounded,
    _repair_title,
    task_splitter_node,
)


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


async def test_complex_input_reaches_llm_and_splits() -> None:
    # 회귀 가드: 길고 반복적인(되돌이 사유가 섞인) 입력도 사전 게이트로 버려지지 않고
    # LLM 을 호출해 분해돼야 한다. (예전 압축률 게이트가 이런 입력을 out_of_scope 로 떨궜다.)
    prompt = (
        "오뚜기 밥을 먹어야 되고 반찬도 필요하니까 반찬가게 가서 반찬을 사와야 되겠다. "
        "쌀과자도 후식으로 먹어야 되는데 다 떨어졌으니까 마트 들려서 쌀과자도 사야겠어"
    )
    llm = FakeLLM(responses=[[_t("반찬 사기"), _t("쌀과자 사기")]])
    state, config = _state_and_config(llm, prompt=prompt)
    diff = await task_splitter_node(state, config)
    assert llm.calls == 1
    assert [t.title for t in diff["split_tasks"]] == ["반찬 사기", "쌀과자 사기"]


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


async def test_over_30_tasks_raises_llm_output_error() -> None:
    # 200자 입력 task 상한(~25)을 넘는 30개 초과 = 모델 오동작. 그라운딩 이전에 에러로 막는다.
    too_many = [_t(f"t{i}") for i in range(31)]
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


# --- 출력 그라운딩 ---


def test_is_grounded_keeps_input_words_drops_hallucination() -> None:
    assert _is_grounded("토익 시험", "내일 토익 시험") is True
    assert _is_grounded("건강하기", "건강하고 건강해야해") is True  # 어간 겹침
    assert _is_grounded("토익 공부", "오늘 코테 발표") is False  # 입력에 없음
    # 회귀: 조사(을/를)로 명사와 동사가 갈린 정상 입력의 정규화 제목도 통과해야 한다.
    # (예전 글자 2-gram 방식은 '밥을'↔'밥 먹기' 의 '밥먹' bigram 이 안 맞아 잘못 떨궜다.)
    assert _is_grounded("밥 먹기", "밥을 먹어야지") is True
    assert _is_grounded("숙제 하기", "숙제를 해야해") is True


# --- 손상 복원 (repair) ---


def test_repair_title_recovers_corrupted_word() -> None:
    p = "헬스장 갔다가 두쫀쿠 먹고 엄마 보러 가야지"
    # base 모델이 깬 '두啭iku' → 입력 표면형 '두쫀쿠'로 복원
    assert _repair_title("두啭iku 먹기", p) == "두쫀쿠 먹기"
    # 손상(CJK) 없는 정상 제목은 그대로
    assert _repair_title("헬스장 가기", p) == "헬스장 가기"
    assert _repair_title("먹기", p) == "먹기"


async def test_node_repairs_corrupted_title() -> None:
    # 노드가 깨진 제목을 입력 표면형으로 복원해 내보낸다.
    llm = FakeLLM(responses=[[_t("두啭iku 먹기")]])
    state, config = _state_and_config(llm, prompt="두쫀쿠 먹고")
    diff = await task_splitter_node(state, config)
    assert [t.title for t in diff["split_tasks"]] == ["두쫀쿠 먹기"]


async def test_node_drops_ungrounded_task() -> None:
    # 입력에 근거 없는 환각 task('토익')는 떨구고, 근거 있는 것만 남긴다.
    llm = FakeLLM(responses=[[_t("코테"), _t("토익")]])
    state, config = _state_and_config(llm, prompt="코테 준비하기")
    diff = await task_splitter_node(state, config)
    assert [t.title for t in diff["split_tasks"]] == ["코테"]


async def test_node_dedupes_repeated_tasks() -> None:
    # 모델이 반복 입력을 같은 task 로 여러 번 쪼개면(밥 먹기 ×3) 하나로 합친다.
    d = date(2026, 5, 24)
    llm = FakeLLM(responses=[[_t("밥 먹기", d), _t("밥 먹기", d), _t("밥 먹기", d)]])
    state, config = _state_and_config(llm, prompt="밥을 먹고 밥을 먹어야지 밥을 먹어야해")
    diff = await task_splitter_node(state, config)
    assert [t.title for t in diff["split_tasks"]] == ["밥 먹기"]
