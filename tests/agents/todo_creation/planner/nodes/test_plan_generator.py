from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

from agents.todo_creation.exceptions import LLMOutputError
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
    generate_error: Exception | None = None
    generate_calls: int = 0
    goal_tag_calls: int = 0
    tag_calls: int = 0

    async def generate_plan(
        self, *, parsed_goal: ParsedGoal, today: date
    ) -> tuple[str, list[PlanDay]]:
        self.generate_calls += 1
        if self.generate_error is not None:
            raise self.generate_error
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
    classifier: _FakeLLM | None = None
    validator: object | None = None


def _config(llm: _FakeLLM, *, classifier=None, validator=None) -> dict:
    return {
        "configurable": {
            "ports": _Ports(
                llm=llm,
                classifier=classifier,
                validator=validator,
            )
        }
    }


def _state(parsed_goal: ParsedGoal | None = None) -> dict:
    return {"today": _TODAY, "parsed_goal": parsed_goal or {"goal_tag": "목표"}}


async def test_splits_today_tasks_into_todos() -> None:
    task = TaskCandidate(title="코테", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("오늘 코테 준비", plan))

    result = await plan_generator_node(_state(), _config(llm))

    assert result["todos"][0].title == task.title
    assert result["calendar_events"] == []
    assert result["summary_text"] == "오늘 코테 준비, 몽글."
    assert result["todos"][0].tags == ["목표"]


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


async def test_empty_plan_falls_back_to_safe_plan_after_retry() -> None:
    """모델이 빈 일정을 반복하면 예외 대신 최소 안전 플랜으로 복구한다."""

    llm = _FakeLLM(plan_response=("", []))

    result = await plan_generator_node(_state(), _config(llm))

    assert llm.generate_calls == 2
    assert result["plan"]
    assert result["plan"][0]["tasks"][0].title == "현재 상태 정리"


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
    task = TaskCandidate(title="요약 점검", due_date=_TODAY)
    plan: list[PlanDay] = [{"date": _TODAY, "tasks": [task]}]
    llm = _FakeLLM(plan_response=("가" * 1600, plan))

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

    assert result["todos"][0].tags == ["영어말하기"]
    assert llm.goal_tag_calls == 0
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
        _state({"plan_kind": "exam", "goal_tag": "목표", "deadline": deadline}),
        _config(llm),
    )

    titles = [t.title for t in result["todos"] + result["calendar_events"]]
    assert "회고" not in titles
    assert "개념" in titles
    assert "기출" in titles


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
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 필기",
                "goal_tag": "정처기",
                "deadline": deadline,
            }
        ),
        _config(llm),
    )

    all_tasks = result["todos"] + result["calendar_events"]
    assert all(t.due_date <= deadline for t in all_tasks)
    assert any(t.title == "시험 응시" and t.due_date == deadline for t in all_tasks)
    assert all(t.title != "회고" for t in all_tasks)


async def test_long_event_plan_limits_calendar_to_thirty_day_detail() -> None:
    """30일 밖 목표는 상세 일정만 저장하고 남은 기간은 채팅으로 안내한다."""

    deadline = date(2026, 8, 8)
    plan: list[PlanDay] = [
        {
            "date": _TODAY + timedelta(days=index),
            "tasks": [
                TaskCandidate(
                    title=f"훈련 {index + 1}",
                    due_date=_TODAY + timedelta(days=index),
                )
            ],
        }
        for index in range(7)
    ]
    llm = _FakeLLM(
        plan_response=("철인 삼종 준비", plan),
        goal_tag_response="철인삼종",
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_tag": "철인삼종",
                "deadline": deadline,
            }
        ),
        _config(llm),
    )

    dates = [day["date"] for day in result["plan"]]
    window_end = _TODAY + timedelta(days=29)
    assert dates[0] == _TODAY
    assert dates[-1] == window_end
    assert dates == sorted(dates)
    assert all(_TODAY <= planned_date <= window_end for planned_date in dates)
    assert deadline not in dates
    assert all(
        "진행 점검" not in task.title
        for day in result["plan"]
        for task in day["tasks"]
    )
    assert window_end.isoformat() in result["summary_text"]
    assert deadline.isoformat() in result["summary_text"]
    assert "흐름으로 이어가면" in result["summary_text"]


async def test_general_goal_uses_base_generator() -> None:
    """일반 목표는 시험 특화 LoRA 대신 base 모델로 격리한다."""

    planner = _FakeLLM(
        plan_response=(
            "시험 준비",
            [
                {
                    "date": _TODAY,
                    "tasks": [TaskCandidate(title="필기 공부", due_date=_TODAY)],
                }
            ],
        )
    )
    base = _FakeLLM(
        plan_response=(
            "수영과 달리기를 준비해요.",
            [
                {
                    "date": _TODAY,
                    "tasks": [TaskCandidate(title="수영 자세 점검", due_date=_TODAY)],
                }
            ],
        ),
        goal_tag_response="철인삼종",
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 완주",
                "goal_tag": "철인삼종",
            }
        ),
        _config(planner, classifier=base),
    )

    assert result["plan"][0]["tasks"][0].title == "수영 자세 점검"
    assert base.generate_calls == 1
    assert planner.generate_calls == 0


async def test_supported_exam_keeps_planner_lora_generator() -> None:
    """검증된 정보처리기사 목표는 기존 planner LoRA 지식을 유지한다."""

    planner = _FakeLLM(
        plan_response=(
            "정처기 필기를 준비해요.",
            [
                {
                    "date": _TODAY,
                    "tasks": [TaskCandidate(title="필기 개념 복습", due_date=_TODAY)],
                }
            ],
        ),
        goal_tag_response="정보처리기사",
    )
    base = _FakeLLM()

    await plan_generator_node(
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 필기 준비",
                "goal_tag": "정보처리기사",
            }
        ),
        _config(planner, classifier=base),
    )

    assert planner.generate_calls == 1
    assert base.generate_calls == 0


async def test_invalid_planner_json_falls_back_to_base_generator() -> None:
    """planner LoRA의 JSON이 깨지면 base 모델로 한 번 복구한다."""

    planner = _FakeLLM(
        goal_tag_response="정보처리기사",
        generate_error=LLMOutputError("non-JSON response"),
    )
    base = _FakeLLM(
        plan_response=(
            "시험 전 핵심 내용을 복습해요.",
            [
                {
                    "date": _TODAY,
                    "tasks": [TaskCandidate(title="핵심 개념 복습", due_date=_TODAY)],
                }
            ],
        ),
        goal_tag_response="정보처리기사",
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정보처리기사",
                "deadline": _TODAY,
            }
        ),
        _config(planner, classifier=base),
    )

    assert result["plan"][0]["tasks"][0].title == "핵심 개념 복습"
    assert planner.generate_calls == 1
    assert base.generate_calls == 1


async def test_invalid_plan_json_without_base_uses_safe_plan() -> None:
    """JSON 파싱 실패의 안전 플랜은 semantic judge 재생성을 건너뛴다."""

    llm = _FakeLLM(
        goal_tag_response="철인삼종",
        generate_error=LLMOutputError("non-JSON response"),
    )

    class _RejectingValidator:
        async def validate_plan(self, **_):
            raise AssertionError("안전 플랜은 semantic judge로 다시 보내면 안 된다")

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
                "deadline": date(2026, 9, 30),
                "slots": {"weekly_cadence": "주 3회"},
            }
        ),
        _config(llm, validator=_RejectingValidator()),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    dates = [day["date"] for day in result["plan"]]
    assert "주 3회 실행" in titles
    assert dates[-1] == _TODAY + timedelta(days=29)
    assert date(2026, 9, 30).isoformat() in result["summary_text"]
    assert llm.generate_calls == 1


async def test_database_project_safe_plan_uses_database_steps() -> None:
    """DB 구축 목표의 안전 플랜은 시험/일반 템플릿 대신 DB 작업 흐름을 쓴다."""

    llm = _FakeLLM(
        goal_tag_response="데이터베이스",
        generate_error=LLMOutputError("non-JSON response"),
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "project",
                "goal_text": "데이터베이스 구축",
                "goal_tag": "데이터베이스",
            }
        ),
        _config(llm),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert "ERD 초안 만들기" in titles
    assert "테이블 컬럼 정의" in titles
    assert "핵심 작업 1개" not in titles
    assert "개념 복습 1회" not in titles


async def test_english_title_passes_through_without_blocking() -> None:
    """영어 제목은 post-generation 단계에서 blocking 하지 않는다.

    외국어 차단은 생성 단계(plan_guided_schema/outlines)가 담당하고,
    post-generation 검사는 semantic validator 에 위임한다.
    false positive(Python, GitHub 등)로 인한 deterministic fallback 방지.
    """

    llm = _FakeLLM(
        plan_response=(
            "Prepare for the race",
            [
                {
                    "date": _TODAY,
                    "tasks": [TaskCandidate(title="Running practice", due_date=_TODAY)],
                }
            ],
        )
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "마라톤 완주",
                "goal_tag": "마라톤",
            }
        ),
        _config(llm),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    # 영어 제목이 blocking 없이 그대로 반환된다.
    assert "Running practice" in titles


async def test_deterministic_contamination_falls_back_after_retry() -> None:
    """비시험 플랜의 필기·기출 오염은 사용자에게 반환하지 않고 안전 플랜으로 복구한다."""

    deadline = date(2026, 8, 8)
    contaminated: list[PlanDay] = [
        {
            "date": _TODAY,
            "tasks": [
                TaskCandidate(title="필기 기출 문제 풀이", due_date=_TODAY)
            ],
        }
    ]
    llm = _FakeLLM(plan_response=("시험 준비", contaminated))

    class _Validator:
        async def validate_plan(self, **_):
            return False, ["사용자 목표와 무관한 시험 내용"]

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
                "deadline": deadline,
                "slots": {"activity": "철인 삼종 경기"},
            }
        ),
        _config(llm, validator=_Validator()),
    )

    assert llm.generate_calls == 2
    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert "필기 기출 문제 풀이" not in titles
    assert "기초 체력 30분" in titles


async def test_supported_exam_alias_cannot_leak_into_event_plan() -> None:
    """지원 시험 registry의 별칭이 일반 이벤트 일정에 섞이면 안전 플랜으로 복구한다."""

    contaminated: list[PlanDay] = [
        {
            "date": _TODAY + timedelta(days=index),
            "tasks": [
                TaskCandidate(title="정처기 훈련", due_date=_TODAY + timedelta(days=index))
            ],
        }
        for index in range(4)
    ]
    llm = _FakeLLM(plan_response=("철인 삼종 훈련", contaminated))

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
            }
        ),
        _config(llm),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert all("정처기" not in title for title in titles)
    assert "기초 체력 30분" in titles


async def test_off_topic_symbol_title_falls_back_after_retry() -> None:
    """목표 문맥에 없는 코드형 제목이 섞이면 안전 플랜으로 복구한다."""

    contaminated: list[PlanDay] = [
        {
            "date": _TODAY + timedelta(days=index),
            "tasks": [
                TaskCandidate(
                    title=f"10000BTC BTCUSDT {40 + index * 20}%",
                    due_date=_TODAY + timedelta(days=index),
                )
            ],
        }
        for index in range(2)
    ]
    llm = _FakeLLM(plan_response=("정처기 실기 준비", contaminated))

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정보처리기사",
                "deadline": _TODAY + timedelta(days=20),
                "slots": {"exam_part": "실기"},
            }
        ),
        _config(llm),
    )

    assert llm.generate_calls == 2
    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert all("BTC" not in title and "USDT" not in title for title in titles)
    assert "범위 정리 30분" in titles


async def test_exam_part_mismatch_falls_back_after_retry() -> None:
    """사용자가 실기라고 답했는데 필기 플랜이 나오면 반환하지 않는다."""

    contaminated: list[PlanDay] = [
        {
            "date": _TODAY,
            "tasks": [TaskCandidate(title="오답 정리 1회", due_date=_TODAY)],
        }
    ]
    llm = _FakeLLM(plan_response=("정처기 필기 오답 정리를 진행해요.", contaminated))

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 실기 준비",
                "goal_tag": "정보처리기사",
                "deadline": _TODAY,
                "slots": {"exam_part": "실기"},
            }
        ),
        _config(llm),
    )

    assert llm.generate_calls == 2
    assert "필기" not in result["summary_text"]


async def test_repeated_generic_plan_titles_fall_back() -> None:
    """비루틴 플랜이 같은 제목을 세 번 넘게 반복하면 안전 플랜으로 복구한다."""

    repeated: list[PlanDay] = [
        {
            "date": _TODAY + timedelta(days=index),
            "tasks": [
                TaskCandidate(title="철인삼종 훈련", due_date=_TODAY + timedelta(days=index))
            ],
        }
        for index in range(4)
    ]
    llm = _FakeLLM(plan_response=("철인 삼종 준비", repeated))

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
            }
        ),
        _config(llm),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert titles.count("철인삼종 훈련") == 0
    assert "현재 수준 기록" in titles


async def test_goal_name_plus_generic_action_falls_back() -> None:
    """목표명에 '훈련 계획'만 붙인 제목은 안전 플랜으로 복구한다."""

    plan: list[PlanDay] = [
        {
            "date": _TODAY,
            "tasks": [TaskCandidate(title="철인삼종 훈련 계획", due_date=_TODAY)],
        },
        {
            "date": _TODAY + timedelta(days=1),
            "tasks": [TaskCandidate(title="수영 자세 20분", due_date=_TODAY + timedelta(days=1))],
        },
    ]
    llm = _FakeLLM(
        plan_response=("철인 삼종 준비", plan),
        goal_tag_response="철인삼종",
    )

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "event",
                "goal_text": "철인 삼종 경기 출전",
                "goal_tag": "철인삼종",
            }
        ),
        _config(llm),
    )

    titles = [task.title for day in result["plan"] for task in day["tasks"]]
    assert "철인삼종 훈련 계획" not in titles
    assert "기술 동작 20분" in titles


async def test_semantic_false_positive_is_advisory_after_retry() -> None:
    """judge가 시험 준비를 잘못 요구해도 하드 검증 통과 플랜은 보존한다."""

    plan: list[PlanDay] = [
        {
            "date": _TODAY,
            "tasks": [TaskCandidate(title="대표 요리 연습", due_date=_TODAY)],
        }
    ]
    llm = _FakeLLM(plan_response=("대표 요리를 준비해요.", plan))

    class _Validator:
        async def validate_plan(self, **_):
            return False, ["시험 준비 단계가 누락되어 있습니다"]

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "project",
                "goal_text": "요리 대회 준비",
                "goal_tag": "요리대회",
                "deadline": _TODAY,
                "slots": {"goal": "대표 요리 완성"},
            }
        ),
        _config(llm, validator=_Validator()),
    )

    assert llm.generate_calls == 2
    assert result["plan"][0]["tasks"][0].title == "대표 요리 연습"


async def test_semantic_validator_parse_failure_does_not_block_valid_plan() -> None:
    """소프트 judge의 JSON 파싱 실패가 정상 플랜을 중단시키지 않는다."""

    plan: list[PlanDay] = [
        {
            "date": _TODAY,
            "tasks": [TaskCandidate(title="핵심 개념 복습", due_date=_TODAY)],
        }
    ]
    llm = _FakeLLM(plan_response=("시험 전 핵심 내용을 복습해요.", plan))

    class _BrokenValidator:
        async def validate_plan(self, **_):
            raise LLMOutputError('non-JSON response: {"valid": false')

    result = await plan_generator_node(
        _state(
            {
                "plan_kind": "exam",
                "goal_text": "정보처리기사 필기 준비",
                "goal_tag": "정보처리기사",
                "deadline": _TODAY,
            }
        ),
        _config(llm, validator=_BrokenValidator()),
    )

    assert llm.generate_calls == 1
    assert result["plan"][0]["tasks"][0].title == "핵심 개념 복습"
