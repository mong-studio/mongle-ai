from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from agents.todo_creation.planner.nodes.plan_generator import plan_generator_node
from agents.todo_creation.schemas import TaskCandidate
from agents.todo_creation.state import ParsedGoal, PlanDay

_TODAY = date(2026, 5, 27)
_FUTURE = date(2026, 5, 30)


@dataclass
class _FakeLLM:
    plan_response: tuple[str, list[PlanDay]] = field(
        default_factory=lambda: ("", [])
    )
    goal_tag_response: str = "목표"
    tag_response: list[PlanDay] | None = None
    tag_error: Exception | None = None
    rationale_to_stash: str | None = None
    generate_calls: int = 0
    goal_tag_calls: int = 0
    tag_calls: int = 0
    seen_temperatures: list[float | None] = field(default_factory=list)

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date, temperature: float | None = None
    ) -> tuple[str, list[PlanDay]]:
        self.generate_calls += 1
        self.seen_temperatures.append(temperature)
        # 실제 어댑터처럼 rationale 을 parsed_goal 에 실어둔다.
        if self.rationale_to_stash is not None:
            parsed_goal["rationale"] = self.rationale_to_stash
        return self.plan_response

    async def generate_goal_tag(
        self, *, parsed_goal: ParsedGoal, history: list
    ) -> str:
        self.goal_tag_calls += 1
        return self.goal_tag_response

    async def tag_plan(
        self, *, plan: list[PlanDay], parsed_goal: ParsedGoal
    ) -> list[PlanDay]:
        self.tag_calls += 1
        if self.tag_error:
            raise self.tag_error
        return self.tag_response if self.tag_response is not None else plan

    async def judge_sufficiency(self, **_): ...
    async def generate_follow_up_question(self, **_): ...
    async def split_tasks(self, **_): ...


@dataclass
class _Ports:
    llm: _FakeLLM


def _config(llm: _FakeLLM) -> dict:
    return {"configurable": {"ports": _Ports(llm=llm)}}


def _state(parsed_goal: ParsedGoal | None = None) -> dict:
    return {"today": _TODAY, "parsed_goal": parsed_goal or {"goal_tag": "목표"}}


async def test_splits_today_tasks_into_todos() -> None:
    task = TaskCandidate(title="코테", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("오늘 코테 준비", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"][0].title == task.title
    assert result["calendar_events"] == []
    assert result["summary_text"] == "오늘 코테 준비"
    assert result["todos"][0].tags == ["목표"]


async def test_propagates_parsed_goal_with_rationale_into_state() -> None:
    """critic 이 읽도록 rationale·goal_tag 가 실린 parsed_goal 을 state 로 전파한다."""
    task = TaskCandidate(title="코테", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(
        plan_response=("요약", plan),
        goal_tag_response="코테",
        rationale_to_stash="개념→점검 순으로 난이도를 점증시켰습니다.",
    )

    result = await plan_generator_node(_state({"goal_text": "코테 준비"}), _config(llm))

    pg = result["parsed_goal"]
    assert pg["rationale"] == "개념→점검 순으로 난이도를 점증시켰습니다."
    assert pg["goal_tag"] == "코테"


async def test_first_pass_uses_default_temperature() -> None:
    """1차 생성(critique_retries=0)은 어댑터 기본 temp → None 전달."""
    task = TaskCandidate(title="코테", due_date=_TODAY)
    llm = _FakeLLM(plan_response=("요약", [{"date": _TODAY, "tasks": [task]}]))

    await plan_generator_node(_state(), _config(llm))

    assert llm.seen_temperatures == [None]


async def test_regeneration_pass_uses_high_temperature() -> None:
    """재생성(critique_retries>=1)은 Qwen 기본 0.7 로 샘플링 다양성을 준다(레버①)."""
    task = TaskCandidate(title="코테", due_date=_TODAY)
    llm = _FakeLLM(plan_response=("요약", [{"date": _TODAY, "tasks": [task]}]))
    state = {**_state(), "critique_retries": 1}

    await plan_generator_node(state, _config(llm))

    assert llm.seen_temperatures == [0.7]


async def test_splits_future_tasks_into_calendar_events() -> None:
    task = TaskCandidate(title="발표", due_date=_FUTURE)
    plan: list[PlanDay] = [{"date": _FUTURE, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("발표 준비", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == []
    assert result["calendar_events"][0].title == task.title
    assert result["calendar_events"][0].tags == ["목표"]


async def test_mixed_plan_splits_correctly() -> None:
    today_task = TaskCandidate(title="코테", due_date=_TODAY)
    future_task = TaskCandidate(title="발표", due_date=_FUTURE)
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [today_task]},
        {"date": _FUTURE, "tasks": [future_task]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"][0].title == today_task.title
    assert result["calendar_events"][0].title == future_task.title
    assert result["todos"][0].tags == ["목표"]
    assert result["calendar_events"][0].tags == ["목표"]


async def test_empty_plan_returns_empty_lists() -> None:
    llm = _FakeLLM(plan_response=("", []))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"] == []
    assert result["calendar_events"] == []
    assert result["plan"] == []


async def test_spreads_duplicate_plan_dates_across_days() -> None:
    first = TaskCandidate(title="단어 복습", due_date=_TODAY)
    second = TaskCandidate(title="듣기 연습", due_date=_TODAY)
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [first]},
        {"date": _TODAY, "tasks": [second]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(_state({"goal_tag": "영어말하기"}), _config(llm))

    assert result["plan"][0]["date"] == _TODAY
    assert result["plan"][1]["date"] == _TODAY + timedelta(days=1)
    assert result["todos"][0].due_date == _TODAY
    assert result["calendar_events"][0].due_date == _TODAY + timedelta(days=1)


async def test_truncates_summary_after_retry() -> None:
    llm = _FakeLLM(plan_response=("가" * 1600, []))

    result = await plan_generator_node(_state(), _config(llm))

    assert len(result["summary_text"]) <= 1500
    assert llm.generate_calls == 2


async def test_applies_same_goal_tag_without_tag_llm_call() -> None:
    task = TaskCandidate(title="발음 연습", due_date=_TODAY, tags=["학습"])
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(
        plan_response=("요약", plan),
        goal_tag_response="영어말하기시험",
        tag_error=RuntimeError("fail"),
    )

    result = await plan_generator_node(_state({"goal_tag": "영어말하기"}), _config(llm))

    assert result["todos"][0].tags == ["영어말하기시험"]
    assert llm.goal_tag_calls == 1
    assert llm.tag_calls == 0


async def test_sanitizes_goal_tag_without_domain_word_lists() -> None:
    task = TaskCandidate(title="여권 확인", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("요약", plan), goal_tag_response="나부산가족여행")

    result = await plan_generator_node(
        _state({"goal_tag": "부산 가족여행 준비"}),
        _config(llm),
    )

    assert result["todos"][0].tags == ["부산가족여행"]


async def test_drops_tasks_after_deadline() -> None:
    """parsed_goal.deadline 이후 날짜의 task 는 제거한다 (P1)."""
    deadline = _TODAY + timedelta(days=2)
    # due_date 는 _prepare_plan_days 가 PlanDay["date"] 로 덮어쓰므로 여기 값은 임의값
    d0 = TaskCandidate(title="개념", due_date=_TODAY)
    d1 = TaskCandidate(title="기출", due_date=_TODAY + timedelta(days=1))
    after = TaskCandidate(title="회고", due_date=_TODAY + timedelta(days=3))  # 마감 이후
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [d0]},
        {"date": _TODAY + timedelta(days=1), "tasks": [d1]},
        {"date": _TODAY + timedelta(days=3), "tasks": [after]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(
        _state({"goal_tag": "목표", "deadline": deadline}), _config(llm)
    )

    titles = [t.title for t in result["todos"] + result["calendar_events"]]
    assert "회고" not in titles
    assert "개념" in titles
    assert "기출" in titles


async def test_truncated_plan_is_stretched_to_deadline() -> None:
    """모델이 마감 한참 전에 끝내면(truncation) 코드가 today~deadline 전체로 펼쳐 마지막날=deadline."""
    deadline = _TODAY + timedelta(days=40)
    # 모델은 첫 2주 안에 몰아넣음(마감까지 한참 못 미침) → 버그 재현.
    d0 = TaskCandidate(title="기초 체력", due_date=_TODAY)
    d1 = TaskCandidate(title="중간 점검", due_date=_TODAY + timedelta(days=5))
    d2 = TaskCandidate(title="실전 대비", due_date=_TODAY + timedelta(days=10))
    plan: list[PlanDay] = [
        {"date": _TODAY, "tasks": [d0]},
        {"date": _TODAY + timedelta(days=5), "tasks": [d1]},
        {"date": _TODAY + timedelta(days=10), "tasks": [d2]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(
        _state({"goal_tag": "철인삼종", "deadline": deadline}), _config(llm)
    )

    days = [d["date"] for d in result["plan"]]
    assert days[0] == _TODAY
    assert days[-1] == deadline  # 마지막날이 마감일까지 도달 (truncation 해소)
    assert days == sorted(days)  # 단조 증가


async def test_keeps_all_tasks_when_no_deadline() -> None:
    """deadline 이 없으면 clamp 하지 않는다 (기존 거동 보존)."""
    after = TaskCandidate(title="회고", due_date=_TODAY + timedelta(days=3))
    plan: list[PlanDay] = [{"date": _TODAY + timedelta(days=3), "tasks": [after]}]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(_state({"goal_tag": "목표"}), _config(llm))

    titles = [t.title for t in result["todos"] + result["calendar_events"]]
    assert "회고" in titles


async def test_p1_no_task_strictly_after_deadline() -> None:
    """P1 회귀: 마감일 '이후'(>)에는 어떤 task 도 남지 않는다."""
    deadline = _TODAY + timedelta(days=6)  # "일주일 뒤" 류
    d5 = _TODAY + timedelta(days=5)
    d7 = _TODAY + timedelta(days=7)
    plan: list[PlanDay] = [
        {"date": d5, "tasks": [TaskCandidate(title="최종점검", due_date=d5)]},
        {"date": deadline, "tasks": [TaskCandidate(title="시험 응시", due_date=deadline)]},
        {"date": d7, "tasks": [TaskCandidate(title="회고", due_date=d7)]},
    ]
    llm = _FakeLLM(plan_response=("요약", plan))

    result = await plan_generator_node(
        _state({"goal_tag": "정처기", "deadline": deadline}), _config(llm)
    )

    all_tasks = result["todos"] + result["calendar_events"]
    assert all(t.due_date <= deadline for t in all_tasks)
    assert any(t.title == "시험 응시" and t.due_date == deadline for t in all_tasks)
    assert all(t.title != "회고" for t in all_tasks)
