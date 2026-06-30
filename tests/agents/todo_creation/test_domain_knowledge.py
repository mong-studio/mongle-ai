from __future__ import annotations

from agents.todo_creation.domain_knowledge import (
    recommended_task_titles_for_goal,
    resolve_domain_wiki,
)


def test_resolves_part_specific_wiki_from_generic_goal_tag() -> None:
    wiki = resolve_domain_wiki(
        {
            "plan_kind": "exam",
            "goal_text": "정처기 준비",
            "goal_tag": "정보처리기사",
            "slots": {"exam_part": "실기"},
        }
    )

    assert wiki is not None
    assert wiki.label == "정보처리기사 실기"
    assert "SQL 응용 기출풀기" in wiki.content


def test_recommended_titles_come_from_resolved_domain_wiki() -> None:
    titles = recommended_task_titles_for_goal(
        {
            "plan_kind": "exam",
            "goal_text": "정보처리기사 준비",
            "goal_tag": "정보처리기사",
            "slots": {"exam_part": "필기"},
        }
    )

    assert titles[:2] == ["소프트웨어설계 기출풀기", "소프트웨어개발 기출풀기"]


def test_explicit_exam_part_overrides_stale_goal_tag() -> None:
    wiki = resolve_domain_wiki(
        {
            "plan_kind": "exam",
            "goal_text": "정보처리기사 준비",
            "goal_tag": "정처기필기",
            "slots": {"exam_part": "실기"},
        }
    )

    assert wiki is not None
    assert wiki.label == "정보처리기사 실기"
