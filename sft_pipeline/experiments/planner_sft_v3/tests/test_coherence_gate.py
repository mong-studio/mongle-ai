from datetime import date

from sft_pipeline.experiments.planner_sft_v3.coherence_gate import (
    check_structure,
    has_english_leak,
)

TODAY = date(2026, 7, 5)


def _goal(kind="lifestyle", **over):
    goal = {
        "plan_kind": kind,
        "goal_text": "운동과 독서 병행",
        "deadline": "2026-07-20",
        "slots": {"goal": "운동과 독서 병행"},
    }
    goal.update(over)
    return goal


def _plan(days):
    return {"summary_text": "무리하지 않고 진행해요.", "days": days}


def _day(d, *titles):
    return {"date": d, "tasks": [{"title": t, "due_date": d} for t in titles]}


def test_valid_plan_passes():
    plan = _plan([_day("2026-07-06", "가벼운 운동"), _day("2026-07-10", "독서 30분")])
    assert check_structure(plan, _goal(), TODAY) == []


def test_s2_date_out_of_range():
    plan = _plan([_day("2026-09-01", "너무 늦은 일정")])
    issues = check_structure(plan, _goal(), TODAY)
    assert any(i.startswith("S2") for i in issues)


def test_s2_due_date_mismatch():
    plan = {"summary_text": "요약", "days": [
        {"date": "2026-07-06", "tasks": [{"title": "운동", "due_date": "2026-07-08"}]}]}
    assert any(i.startswith("S2") for i in check_structure(plan, _goal(), TODAY))


def test_s3_daily_overload():
    plan = _plan([_day("2026-07-06", "일1", "일2", "일3", "일4")])
    assert any(i.startswith("S3") for i in check_structure(plan, _goal(), TODAY))


def test_s4_exam_leak_in_non_exam_goal():
    plan = _plan([_day("2026-07-06", "기출 문제 풀이")])
    assert any(i.startswith("S4") for i in check_structure(plan, _goal(), TODAY))
    # 시험 목표에서는 허용
    assert check_structure(plan, _goal(kind="exam"), TODAY) == []


def test_s4_english_leak():
    plan = _plan([_day("2026-07-06", "Review the plan")])
    assert any(i.startswith("S4") for i in check_structure(plan, _goal(), TODAY))
    assert has_english_leak("Study session 준비")
    assert not has_english_leak("SQL 응용 기출풀기")  # 연속 2단어 미만 영어는 허용


def test_s5_routine_weekly_count():
    goal = _goal(kind="routine", slots={"goal": "주 3회 근력 운동", "cadence": "주 3회"})
    plan = _plan([_day("2026-07-06", "근력 운동")])  # 첫 주 1회뿐
    assert any(i.startswith("S5") for i in check_structure(plan, goal, TODAY))


def test_duplicate_task_rejected():
    plan = _plan([
        {"date": "2026-07-06", "tasks": [
            {"title": "운동", "due_date": "2026-07-06"},
            {"title": "운동", "due_date": "2026-07-06"},
        ]}
    ])
    assert any("중복" in i for i in check_structure(plan, _goal(), TODAY))
