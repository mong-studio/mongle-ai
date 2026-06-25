from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.todo_creation.planner.nodes.follow_up import follow_up_node


def _state(history: list | None = None) -> dict:
    return {
        "history": history
        if history is not None
        else [{"role": "user", "content": "내일 시험"}],
        "missing_aspects": ["목표 점수"],
    }


def _config(llm: AsyncMock, *, classifier: AsyncMock | None = None) -> dict:
    return {
        "configurable": {
            "ports": type("P", (), {"llm": llm, "classifier": classifier})()
        }
    }


@pytest.mark.asyncio
async def test_calls_llm_and_interrupts_with_question() -> None:
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="목표 점수는?")
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="800점",
    ) as mock_interrupt:
        out = await follow_up_node(_state(), _config(llm))
    assert out["follow_up_question"] == "목표 점수는, 몽글?"
    assert out["history"][-2:] == [
        {"role": "assistant", "content": "목표 점수는, 몽글?"},
        {"role": "user", "content": "800점"},
    ]
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["목표 점수"],
        history=[{"role": "user", "content": "내일 시험"}],
    )
    mock_interrupt.assert_called_once_with("목표 점수는, 몽글?")


@pytest.mark.asyncio
async def test_removes_existing_mongle_without_double_comma() -> None:
    """모델이 이미 '몽글'을 붙여도 쉼표와 호칭을 한 번만 노출한다."""

    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(
        return_value="주 몇 회 가능한가요, 몽글?"
    )
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="주 3회",
    ):
        out = await follow_up_node(_state(), _config(llm))

    assert out["follow_up_question"] == "주 몇 회 가능한가요, 몽글?"


@pytest.mark.asyncio
async def test_history_folds_when_long() -> None:
    # 기존 3 + Q&A 2 = 5턴 > trigger → 오래된 턴이 요약 1줄로 접히고 memory_summary 채워짐.
    prior = [
        {"role": "user", "content": "내일 시험"},
        {"role": "assistant", "content": "어떤 시험?"},
        {"role": "user", "content": "영어 말하기 시험"},
    ]
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="목표 점수?")
    llm.summarize_history = AsyncMock(return_value="영어 말하기 시험 준비 중")
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="800점",
    ):
        out = await follow_up_node(_state(history=prior), _config(llm))
    # 요약 1턴 + 최근 2턴
    assert len(out["history"]) == 3
    assert out["history"][0]["content"].startswith("[이전 대화 요약] ")
    assert out["memory_summary"] == {"text": "영어 말하기 시험 준비 중"}


@pytest.mark.asyncio
async def test_routine_missing_cadence_passes_korean_hint() -> None:
    # routine 의 미충족 슬롯 key(cadence)는 사람용 한국어 힌트로 변환돼 전달된다.
    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(return_value="주 몇 번 하실래요?")
    state = {
        "history": [{"role": "user", "content": "매주 운동하고 싶어"}],
        "missing_aspects": ["cadence"],
        "parsed_goal": {"plan_kind": "routine"},
    }
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="주 3회",
    ):
        await follow_up_node(state, _config(llm))
    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=["주 몇 회 또는 어떤 요일인지"],
        history=[{"role": "user", "content": "매주 운동하고 싶어"}],
    )


@pytest.mark.asyncio
async def test_first_question_selects_date_and_one_other_aspect() -> None:
    """첫 질문은 날짜를 우선하고 한 번에 최대 두 조건만 묻는다."""

    llm = AsyncMock()
    llm.generate_follow_up_question = AsyncMock(
        return_value="언제까지 준비하고, 일주일에 얼마나 시간을 낼 수 있나요?"
    )
    state = {
        "history": [{"role": "user", "content": "요리 대회에서 우승하고 싶어"}],
        "missing_aspects": [
            "horizon",
            "available_time",
            "current_state",
        ],
        "parsed_goal": {"plan_kind": "project"},
        "follow_up_count": 0,
    }
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="두 달 뒤까지 주 3회",
    ):
        await follow_up_node(state, _config(llm))

    llm.generate_follow_up_question.assert_awaited_once_with(
        missing_aspects=[
            "언제까지 준비하거나 실행할지",
            "계획에 쓸 수 있는 시간이나 빈도",
        ],
        history=[{"role": "user", "content": "요리 대회에서 우승하고 싶어"}],
    )


@pytest.mark.asyncio
async def test_follow_up_uses_base_classifier_instead_of_planner_lora() -> None:
    """정처기 편향을 피하려고 꼬리질문은 planner LoRA가 아닌 base가 만든다."""

    planner_llm = AsyncMock()
    classifier = AsyncMock()
    classifier.generate_follow_up_question = AsyncMock(
        return_value="언제까지 준비할까요?"
    )
    with patch(
        "agents.todo_creation.planner.nodes.follow_up.interrupt",
        return_value="다음 달까지",
    ):
        await follow_up_node(_state(), _config(planner_llm, classifier=classifier))

    classifier.generate_follow_up_question.assert_awaited_once()
    planner_llm.generate_follow_up_question.assert_not_awaited()
