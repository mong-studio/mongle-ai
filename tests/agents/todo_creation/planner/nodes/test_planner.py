from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from langgraph.types import Command

from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.planner.nodes.planner import planner_node


def _state() -> dict:
    return {
        "history": [
            {
                "role": "user",
                "content": "내일 정보처리기사 필기 시험이고 하루 2시간 가능해. 기출 1회독했고 비전공자야.",
            }
        ],
        "message": "내일 정보처리기사 필기 시험이고 하루 2시간 가능해. 기출 1회독했고 비전공자야.",
        "today": date(2026, 5, 25),
    }


def _config(llm: AsyncMock, *, classifier=None) -> dict:
    return {
        "configurable": {
            "ports": type(
                "P",
                (),
                {"llm": llm, "classifier": classifier},
            )()
        }
    }


@pytest.mark.asyncio
async def test_sufficient_goes_to_plan_generator() -> None:
    """planner 노드가 충분한 정보면 plan_generator로 분기하는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "정보처리기사 필기",
                "goal_tag": "정처기필기",
                "slots": {
                    "exam_part": "필기",
                    "exam_date": "내일",
                    "daily_hours": "2시간",
                    "current_level": "기출 1회독",
                    "background": "비전공자",
                },
            },
        )
    )
    cmd = await planner_node(_state(), _config(llm))
    assert isinstance(cmd, Command)
    assert cmd.goto == "plan_generator"
    assert cmd.update["sufficiency"] is True
    assert cmd.update["parsed_goal"] == {
        "intent": "plan",
        "plan_kind": "exam",
        "goal_text": "정보처리기사 필기",
        "goal_tag": "정처기필기",
        "slots": {
            "exam_part": "필기",
            "exam_date": "내일",
            "daily_hours": "2시간",
            "current_level": "기출 1회독",
            "background": "비전공자",
        },
        "deadline": date(2026, 5, 26),
        "user_profile_memory": {},
    }
    assert cmd.update["missing_aspects"] == []


@pytest.mark.asyncio
async def test_insufficient_goes_to_follow_up() -> None:
    """planner 노드가 정보 부족 시 follow_up으로 분기하되 회수한 목표 정보는 보존하는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["exam_part"],
            {"goal_text": "정처기 준비", "goal_tag": "정처기"},
        )
    )
    state = {
        **_state(),
        "history": [{"role": "user", "content": "정처기 공부 계획 짜줘"}],
        "message": "정처기 공부 계획 짜줘",
    }
    cmd = await planner_node(state, _config(llm))
    assert cmd.goto == "follow_up"
    assert cmd.update["sufficiency"] is False
    assert cmd.update["missing_aspects"] == [
        "exam_part",
        "exam_date",
        "daily_hours",
        "current_level",
        "background",
    ]
    assert cmd.update["parsed_goal"]["goal_text"] == "정처기 준비"


@pytest.mark.asyncio
async def test_llm_output_error_propagates() -> None:
    """planner 노드가 LLMOutputError를 감추지 않고 전파하는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(side_effect=LLMOutputError("schema violation"))
    with pytest.raises(LLMOutputError):
        await planner_node(_state(), _config(llm))


@pytest.mark.asyncio
async def test_unrelated_question_goes_out_of_scope() -> None:
    """플랜과 무관한 첫 입력은 플랜 생성 없이 안내로 보낸다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(False, [], {"intent": "out_of_scope", "goal_text": ""})
    )
    state = {
        **_state(),
        "history": [{"role": "user", "content": "오늘 날씨가 뭐야?"}],
        "message": "오늘 날씨가 뭐야?",
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "out_of_scope"
    assert cmd.update["parsed_goal"]["intent"] == "out_of_scope"


@pytest.mark.asyncio
async def test_triathlon_is_event_and_requests_missing_training_context() -> None:
    """파인튜닝 모델이 exam 으로 오분류해도 대회 출전 목표는 event 로 보정한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "intent": "plan",
                "plan_kind": "exam",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
                "slots": {},
            },
        )
    )
    state = {
        "history": [{"role": "user", "content": "철인 삼종 경기에 출전하고 싶어"}],
        "message": "철인 삼종 경기에 출전하고 싶어",
        "today": date(2026, 6, 24),
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["parsed_goal"]["plan_kind"] == "event"
    assert cmd.update["missing_aspects"] == [
        "event_date",
        "current_level",
        "weekly_cadence",
    ]
    assert "exam_part" not in cmd.update["missing_aspects"]


@pytest.mark.asyncio
async def test_triathlon_absolute_date_fills_event_date_only() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "intent": "plan",
                "plan_kind": "exam",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
                "slots": {},
            },
        )
    )
    state = {
        "history": [
            {
                "role": "user",
                "content": "8월 8일 철인 삼종 경기에 출전하고 싶어",
            }
        ],
        "message": "8월 8일 철인 삼종 경기에 출전하고 싶어",
        "today": date(2026, 6, 24),
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["parsed_goal"]["deadline"] == date(2026, 8, 8)
    assert cmd.update["missing_aspects"] == ["current_level", "weekly_cadence"]


@pytest.mark.asyncio
async def test_unknown_goal_misclassified_as_exam_becomes_project_and_asks() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "intent": "plan",
                "plan_kind": "exam",
                "goal_text": "슈퍼스타 K 참가 준비",
                "goal_tag": "슈퍼스타K",
                "slots": {"exam_part": "필기"},
            },
        )
    )
    state = {
        "history": [{"role": "user", "content": "슈퍼스타 K 나갈 계획 짜줘"}],
        "message": "슈퍼스타 K 나갈 계획 짜줘",
        "today": date(2026, 6, 24),
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["parsed_goal"]["plan_kind"] == "project"
    assert cmd.update["parsed_goal"]["slots"] == {}
    assert cmd.update["missing_aspects"] == [
        "success_criteria",
        "horizon",
        "available_time",
    ]


@pytest.mark.asyncio
async def test_project_slots_accumulate_across_follow_up_turns() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["available_time"],
            {
                "intent": "plan",
                "plan_kind": "project",
                "goal_text": "슈퍼스타 K 참가 준비",
                "slots": {"available_time": "주 4회"},
            },
        )
    )
    state = {
        "history": [
            {"role": "user", "content": "슈퍼스타 K 나갈 계획 짜줘"},
            {"role": "assistant", "content": "어떤 결과를 목표로 해?"},
            {"role": "user", "content": "본선 진출이 목표야"},
            {"role": "assistant", "content": "언제까지 준비할까?"},
            {"role": "user", "content": "8월 말까지"},
            {"role": "assistant", "content": "얼마나 자주 준비할 수 있어?"},
            {"role": "user", "content": "주 4회"},
        ],
        "message": "주 4회",
        "today": date(2026, 6, 24),
        "parsed_goal": {
            "intent": "plan",
            "plan_kind": "project",
            "goal_text": "슈퍼스타 K 참가 준비",
            "slots": {
                "goal": "슈퍼스타 K 참가",
                "success_criteria": "본선 진출",
                "horizon": "8월 말",
            },
        },
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["missing_aspects"] == []
    assert cmd.update["parsed_goal"]["slots"]["available_time"] == "주 4회"


@pytest.mark.asyncio
async def test_called_with_history_and_message() -> None:
    """planner 노드가 LLM에 history/message/today를 그대로 전달하는지 확인한다."""
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
    """follow_up가 반복돼도 정처기 필수 정보가 남으면 plan 생성을 막는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["background"],
            {
                "intent": "plan",
                "plan_kind": "exam",
                "goal_text": "정보처리기사 필기 시험 준비",
                "goal_tag": "정처기필기",
                "deadline": date(2026, 5, 30),
                "slots": {
                    "exam_part": "필기",
                    "exam_date": "5일 뒤",
                    "daily_hours": "2시간",
                    "current_level": "기출 1회독",
                },
            },
        )
    )
    state = {
        **_state(),
        "history": [
            {"role": "user", "content": "5일 뒤 정보처리기사 필기 시험 준비"},
            {"role": "assistant", "content": "하루 몇 시간 가능하세요?"},
            {"role": "user", "content": "2시간"},
            {"role": "assistant", "content": "현재 진도는 어디까지예요?"},
            {"role": "user", "content": "기출 1회독했어"},
        ],
        "message": "기출 1회독했어",
        "parsed_goal": {
            "goal_text": "정보처리기사 필기 시험 준비",
            "goal_tag": "정처기필기",
            "deadline": date(2026, 5, 30),
            "slots": {"exam_part": "필기"},
        },
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["background"]
    llm.judge_sufficiency.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovers_long_goal_from_out_of_scope_misclassification() -> None:
    """긴 목표가 out_of_scope로 오판돼도 원래 goal_text를 복구하는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(False, [], {"intent": "out_of_scope", "goal_text": ""})
    )
    state = {
        **_state(),
        "message": "다음 달 정보처리기사 실기 준비 일정을 같이 정리해줘. 하루 2시간 가능하고 SQL까지 봤고 전공자야.",
        "history": [
            {
                "role": "user",
                "content": "다음 달 정보처리기사 실기 준비 일정을 같이 정리해줘. 하루 2시간 가능하고 SQL까지 봤고 전공자야.",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["parsed_goal"]["goal_text"] == state["message"]


@pytest.mark.asyncio
async def test_ambiguous_deadline_sensitive_goal_goes_to_follow_up() -> None:
    """기한이 중요한 목표인데 deadline이 모호하면 follow_up으로 되돌리는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "정보처리기사 필기 준비",
                "goal_tag": "정처기필기",
                "deadline": None,
                "slots": {
                    "exam_part": "필기",
                    "daily_hours": "2시간",
                    "current_level": "기출 1회독",
                    "background": "비전공자",
                },
            },
        )
    )
    state = {
        **_state(),
        "message": "정보처리기사 필기 시험이 얼마 안 남았는데 하루 2시간 가능하고 기출 1회독한 비전공자야",
        "history": [
            {
                "role": "user",
                "content": "정보처리기사 필기 시험이 얼마 안 남았는데 하루 2시간 가능하고 기출 1회독한 비전공자야",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["exam_date"]


@pytest.mark.asyncio
async def test_ambiguous_event_deadline_ignores_model_made_up_deadline() -> None:
    """LLM이 꾸며낸 정처기 시험일은 무시하고 추가 확인으로 돌리는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정처기실기",
                "deadline": date(2026, 6, 13),
                "slots": {
                    "exam_part": "실기",
                    "daily_hours": "2시간",
                    "current_level": "SQL까지",
                    "background": "전공자",
                },
            },
        )
    )
    state = {
        **_state(),
        "message": "곧 정보처리기사 실기 시험인데 하루 2시간 가능하고 SQL까지 봤고 전공자야",
        "history": [
            {
                "role": "user",
                "content": "곧 정보처리기사 실기 시험인데 하루 2시간 가능하고 SQL까지 봤고 전공자야",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "follow_up"
    assert cmd.update["missing_aspects"] == ["exam_date"]


@pytest.mark.asyncio
async def test_explicit_event_deadline_can_generate_plan() -> None:
    """명시적인 정처기 시험일과 필수 정보가 있으면 plan 생성으로 가는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            True,
            [],
            {
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정처기실기",
                "deadline": date(2026, 6, 9),
                "slots": {
                    "exam_part": "실기",
                    "exam_date": "3일 뒤",
                    "daily_hours": "2시간",
                    "current_level": "SQL까지",
                    "background": "전공자",
                },
            },
        )
    )
    state = {
        **_state(),
        "message": "3일 뒤 정보처리기사 실기 시험이고 하루 2시간 가능하고 SQL까지 봤고 전공자야",
        "history": [
            {
                "role": "user",
                "content": "3일 뒤 정보처리기사 실기 시험이고 하루 2시간 가능하고 SQL까지 봤고 전공자야",
            }
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"


@pytest.mark.asyncio
async def test_deadline_answer_after_follow_up_completes_missing_deadline() -> None:
    """follow_up 뒤 사용자가 날짜를 답하면 parsed_goal의 deadline을 채우는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["deadline"],
            {
                "goal_text": "정보처리기사 필기 준비",
                "goal_tag": "정처기필기",
                "deadline": None,
                "slots": {
                    "exam_part": "필기",
                    "daily_hours": "2시간",
                    "current_level": "개념 1회독",
                    "background": "비전공자",
                },
            },
        )
    )
    state = {
        **_state(),
        "message": "다음주 토요일이야",
        "history": [
            {
                "role": "user",
                "content": "정보처리기사 필기 공부 계획을 세우고 싶어. 하루 2시간 가능하고 개념 1회독한 비전공자야",
            },
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
    """follow_up 뒤 위임형 답변이 와도 기존 goal context를 유지하는지 확인한다."""
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["scope"],
            {
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정처기실기",
                "deadline": date(2026, 6, 3),
                "slots": {
                    "exam_part": "실기",
                    "exam_date": "2026-06-03",
                    "daily_hours": "2시간",
                    "current_level": "SQL까지",
                    "background": "전공자",
                },
            },
        )
    )
    state = {
        **_state(),
        "message": "공부 순서는 추천해줘",
        "history": [
            {
                "role": "user",
                "content": "정보처리기사 실기 공부 계획을 세우고 싶어. 6월 3일 시험이고 하루 2시간 가능하고 SQL까지 봤고 전공자야",
            },
            {"role": "assistant", "content": "어떤 순서로 공부하고 싶으세요?"},
            {"role": "user", "content": "공부 순서는 추천해줘"},
        ],
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["missing_aspects"] == []
    assert cmd.update["parsed_goal"]["goal_tag"] == "정처기실기"


@pytest.mark.asyncio
async def test_base_classifier_keeps_unknown_show_goal_out_of_exam() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["exam_part"],
            {
                "intent": "plan",
                "plan_kind": "exam",
                "goal_text": "흑백요리사 우승 준비",
                "slots": {"exam_part": "필기"},
            },
        )
    )
    classifier = AsyncMock()
    classifier.classify_request = AsyncMock(
        return_value={
            "intent": "planning",
            "plan_kind": "project",
            "confidence": 0.91,
            "evidence": ["우승하고 싶어"],
            "unknown_entity": "흑백요리사",
        }
    )
    state = {
        "history": [{"role": "user", "content": "흑백요리사 우승하고 싶어"}],
        "message": "흑백요리사 우승하고 싶어",
        "today": date(2026, 6, 24),
    }

    cmd = await planner_node(state, _config(llm, classifier=classifier))

    assert cmd.goto == "follow_up"
    assert cmd.update["parsed_goal"]["plan_kind"] == "project"
    assert cmd.update["parsed_goal"]["unknown_entity"] == "흑백요리사"
    assert "exam_part" not in cmd.update["missing_aspects"]


@pytest.mark.asyncio
async def test_base_classifier_routes_conversation_without_planner_judge() -> None:
    llm = AsyncMock()
    classifier = AsyncMock()
    classifier.classify_request = AsyncMock(
        return_value={
            "intent": "conversation",
            "plan_kind": None,
            "confidence": 0.97,
            "evidence": ["배고프다"],
            "unknown_entity": None,
        }
    )
    state = {
        "history": [{"role": "user", "content": "배고프다"}],
        "message": "배고프다",
        "today": date(2026, 6, 24),
    }

    cmd = await planner_node(state, _config(llm, classifier=classifier))

    assert cmd.goto == "out_of_scope"
    llm.judge_sufficiency.assert_not_awaited()


@pytest.mark.asyncio
async def test_followup_answer_keeps_existing_goal_even_if_classified_conversation() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["horizon"],
            {
                "intent": "plan",
                "plan_kind": "project",
                "goal_text": "흑백요리사 우승 준비",
                "slots": {"goal": "흑백요리사 우승"},
            },
        )
    )
    classifier = AsyncMock()
    classifier.classify_request = AsyncMock(
        return_value={
            "intent": "conversation",
            "plan_kind": None,
            "confidence": 0.55,
            "evidence": ["잘 모르겠어요"],
            "unknown_entity": None,
        }
    )
    state = {
        "history": [
            {"role": "user", "content": "흑백요리사 우승하고 싶어"},
            {"role": "assistant", "content": "언제까지 준비할까요, 몽글?"},
            {"role": "user", "content": "잘 모르겠어요"},
        ],
        "message": "잘 모르겠어요",
        "today": date(2026, 6, 24),
        "follow_up_count": 1,
        "parsed_goal": {
            "intent": "plan",
            "plan_kind": "project",
            "goal_text": "흑백요리사 우승 준비",
            "slots": {"goal": "흑백요리사 우승"},
        },
    }

    cmd = await planner_node(state, _config(llm, classifier=classifier))

    assert cmd.goto == "follow_up"
    assert cmd.update["parsed_goal"]["plan_kind"] == "project"


@pytest.mark.asyncio
async def test_after_two_followups_generates_seven_day_assumption() -> None:
    llm = AsyncMock()
    llm.judge_sufficiency = AsyncMock(
        return_value=(
            False,
            ["horizon", "available_time"],
            {
                "intent": "plan",
                "plan_kind": "project",
                "goal_text": "흑백요리사 우승 준비",
                "slots": {"goal": "흑백요리사 우승"},
            },
        )
    )
    state = {
        "history": [
            {"role": "user", "content": "흑백요리사 우승하고 싶어"},
            {"role": "assistant", "content": "언제까지 준비할까요, 몽글?"},
            {"role": "user", "content": "아직 모르겠어요"},
            {"role": "assistant", "content": "현재 경험과 가용 시간을 알려주세요, 몽글?"},
            {"role": "user", "content": "요리는 조금 해봤어요"},
        ],
        "message": "요리는 조금 해봤어요",
        "today": date(2026, 6, 24),
        "follow_up_count": 2,
        "parsed_goal": {
            "intent": "plan",
            "plan_kind": "project",
            "goal_text": "흑백요리사 우승 준비",
            "slots": {"goal": "흑백요리사 우승"},
        },
    }

    cmd = await planner_node(state, _config(llm))

    assert cmd.goto == "plan_generator"
    assert cmd.update["parsed_goal"]["deadline"] == date(2026, 6, 30)
    assert any(
        "7일" in item for item in cmd.update["parsed_goal"]["assumptions"]
    )
