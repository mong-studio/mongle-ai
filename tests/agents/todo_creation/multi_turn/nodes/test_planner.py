from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.multi_turn.nodes.planner import planner_node


def _state() -> dict:
    return {
        "history": [{"role": "user", "content": "내일 영어 말하기 시험"}],
        "message": "내일 영어 말하기 시험",
        "today": date(2026, 5, 25),
    }


def _config(llm: AsyncMock) -> dict:
    return {"configurable": {"ports": type("P", (), {"llm": llm})()}}


@pytest.mark.asyncio
async def test_sufficient_goes_to_plan_generator() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(True, [], {"goal_text": "영어 말하기 시험", "goal_tag": "영어말하기시험"})
    )
    cmd = await planner_node(_state(), _config(llm))
    assert isinstance(cmd, Command)
    assert cmd.goto == "plan_generator"
    assert cmd.update["sufficiency"] is True
    assert cmd.update["parsed_goal"] == {
        "goal_text": "영어 말하기 시험",
        "goal_tag": "영어말하기시험",
        "deadline": date(2026, 5, 26),
        "user_profile_memory": {},
    }
    assert cmd.update["missing_aspects"] == []


@pytest.mark.asyncio
async def test_insufficient_goes_to_follow_up() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(return_value=(False, ["목표 점수"], {}))
    cmd = await planner_node(_state(), _config(llm))
    assert cmd.goto == "follow_up"
    assert cmd.update["sufficiency"] is False
    assert cmd.update["missing_aspects"] == ["목표 점수"]
    assert cmd.update["parsed_goal"] is None


@pytest.mark.asyncio
async def test_llm_output_error_propagates() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(side_effect=LLMOutputError("schema violation"))
    with pytest.raises(LLMOutputError):
        await planner_node(_state(), _config(llm))


@pytest.mark.asyncio
async def test_called_with_history_and_message() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(return_value=(True, [], {"goal_text": "g"}))
    state = _state()
    await planner_node(state, _config(llm))
    llm.judge_sufficiency.assert_awaited_once_with(
        history=state["history"],
        message=state["message"],
        today=state["today"],
        user_profile_memory=None,
    )


@pytest.mark.asyncio
async def test_repeated_follow_up_falls_back_to_plan_generation() -> None:
    llm = AsyncMock()
    state = {
        **_state(),
        "history": [
            {"role": "user", "content": "5일 뒤 영어 말하기 시험 준비"},
            {"role": "assistant", "content": "하루 몇 시간 가능하세요?"},
            {"role": "user", "content": "2시간"},
            {"role": "assistant", "content": "어떤 과목이 약하세요?"},
            {"role": "user", "content": "듣기가 약해요"},
        ],
        "message": "듣기가 약해요",
        "parsed_goal": {
            "goal_text": "영어 말하기 시험 준비",
            "goal_tag": "영어말하기시험",
            "deadline": date(2026, 5, 30),
        },
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["parsed_goal"]["goal_tag"] == "영어말하기시험"
    llm.judge_sufficiency.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovers_long_goal_from_out_of_scope_misclassification() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(False, [], {"intent": "out_of_scope", "goal_text": ""})
    )
    state = {
        **_state(),
        "message": "다음 달 결혼 준비 일정을 같이 정리해줘",
        "history": [{"role": "user", "content": "다음 달 결혼 준비 일정을 같이 정리해줘"}],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["parsed_goal"]["goal_text"] == state["message"]


@pytest.mark.asyncio
async def test_ambiguous_deadline_sensitive_goal_goes_to_follow_up() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "영어 말하기 시험 준비",
                "goal_tag": "영어말하기시험",
                "deadline": None,
            },
        )
    )
    state = {
        **_state(),
        "message": "자격증 시험이 얼마 안 남았는데 공부 계획을 세우고 싶어",
        "history": [
            {
                "role": "user",
                "content": "자격증 시험이 얼마 안 남았는데 공부 계획을 세우고 싶어",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["deadline"]


@pytest.mark.asyncio
async def test_ambiguous_event_deadline_ignores_model_made_up_deadline() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "부산 가족여행 준비",
                "goal_tag": "부산가족여행",
                "deadline": date(2026, 6, 13),
            },
        )
    )
    state = {
        **_state(),
        "message": "곧 부산으로 가족여행을 가는데 준비 계획을 세우고 싶어",
        "history": [
            {
                "role": "user",
                "content": "곧 부산으로 가족여행을 가는데 준비 계획을 세우고 싶어",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["deadline"]


@pytest.mark.asyncio
async def test_explicit_event_deadline_can_generate_plan() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "부산 가족여행 준비",
                "goal_tag": "부산가족여행",
                "deadline": date(2026, 6, 9),
            },
        )
    )
    state = {
        **_state(),
        "message": "3일 뒤 부산 가족여행을 가는데 준비 계획을 세워줘",
        "history": [
            {
                "role": "user",
                "content": "3일 뒤 부산 가족여행을 가는데 준비 계획을 세워줘",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"


@pytest.mark.asyncio
async def test_deadline_answer_after_follow_up_completes_missing_deadline() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["deadline"],
            {
                "goal_text": "자격증 시험 준비",
                "goal_tag": "자격증시험",
                "deadline": None,
            },
        )
    )
    state = {
        **_state(),
        "message": "자격증 시험 공부 계획을 세우고 싶어",
        "history": [
            {"role": "user", "content": "자격증 시험 공부 계획을 세우고 싶어"},
            {"role": "assistant", "content": "시험 날짜는 언제예요?"},
            {"role": "user", "content": "다음주 토요일이야"},
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["missing_aspects"] == []
    assert cmd.update["parsed_goal"]["deadline"] == date(2026, 6, 6)


@pytest.mark.asyncio
async def test_delegate_answer_after_follow_up_uses_existing_goal() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["scope"],
            {
                "goal_text": "영어 말하기 시험 준비",
                "goal_tag": "영어말하기시험",
                "deadline": date(2026, 6, 3),
            },
        )
    )
    state = {
        **_state(),
        "message": "공부 순서는 추천해줘",
        "history": [
            {"role": "user", "content": "영어 말하기 시험 공부 계획을 세우고 싶어"},
            {"role": "assistant", "content": "어떤 순서로 공부하고 싶으세요?"},
            {"role": "user", "content": "공부 순서는 추천해줘"},
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["missing_aspects"] == []
    assert cmd.update["parsed_goal"]["goal_tag"] == "영어말하기시험"
