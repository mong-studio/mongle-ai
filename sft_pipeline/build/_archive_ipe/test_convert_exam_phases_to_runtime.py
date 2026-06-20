import json
from datetime import date

from sft_pipeline.build._archive_ipe.convert_exam_phases_to_runtime import convert_sample
from sft_pipeline.build.lib.plan_schemas import check_plan_consistency, parse_plan


def _sample():
    return {
        "messages": [
            {"role": "system", "content": "old schema"},
            {"role": "user", "content": "정보처리기사 필기 계획 세워줘."},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "kind": "plan",
                        "title": "정처기 필기 3일 준비",
                        "deadline": "2026-06-12",
                        "assumptions": [],
                        "phases": [
                            {
                                "phase": "당일 압축",
                                "due_date": "2026-06-09",
                                "tasks": [
                                    {
                                        "title": "합격 기준 확인",
                                        "due_date": "2026-06-09",
                                        "priority": "high",
                                        "tags": ["정처기"],
                                    }
                                ],
                            },
                            {
                                "phase": "기출 회독",
                                "due_date": "2026-06-10",
                                "tasks": [
                                    {
                                        "title": "CBT 기출 풀기",
                                        "due_date": "2026-06-10",
                                        "priority": "medium",
                                        "tags": ["기출"],
                                    }
                                ],
                            },
                        ],
                        "calendar_events": [
                            {
                                "title": "정보처리기사 필기",
                                "due_date": "2026-06-12",
                                "tags": ["시험"],
                            }
                        ],
                        "summary_text": "정보처리기사 필기는 과목당 40점 이상, 평균 60점 이상이 합격 기준입니다.",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "meta": {
            "id": "ipe-convert-test",
            "today": "2026-06-09",
            "provenance": "exam-crawl",
            "source_url": "https://example.com",
            "exam_type": "정보처리기사 필기",
            "exam_part": "written",
            "result": "합격",
            "time_left_days": 3,
        },
    }


def test_convert_phases_to_runtime_plan():
    converted = convert_sample(_sample())
    payload = json.loads(converted["messages"][-1]["content"])
    assert set(payload) == {"summary_text", "todos", "calendar_events"}
    assert payload["todos"][0]["title"] == "합격 기준 확인"
    assert payload["todos"][0]["due_date"] == "2026-06-09"
    assert payload["calendar_events"][0]["title"] == "CBT 기출 풀기"
    assert payload["calendar_events"][1]["title"] == "정보처리기사 필기"
    assert converted["meta"]["output_schema"] == "runtime-plan-v1"


def test_converted_plan_passes_runtime_consistency():
    converted = convert_sample(_sample())
    plan = parse_plan(converted["messages"][-1]["content"])
    errors = check_plan_consistency(plan, today=date(2026, 6, 9), horizon_days=3)
    assert errors == []
