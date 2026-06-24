from __future__ import annotations

import inspect

from agents.todo_creation.protocols import LLMPort


def test_llm_port_has_async_methods() -> None:
    names = {n for n, _ in inspect.getmembers(LLMPort, predicate=inspect.isfunction)}
    assert {
        "split_tasks",
        "judge_sufficiency",
        "classify_request",
        "generate_follow_up_question",
        "generate_out_of_scope_reply",
        "generate_plan",
        "generate_goal_tag",
        "tag_plan",
        "validate_plan",
    } <= names


def test_llm_port_methods_are_async() -> None:
    for name in (
        "split_tasks",
        "judge_sufficiency",
        "classify_request",
        "generate_follow_up_question",
        "generate_out_of_scope_reply",
        "generate_plan",
        "generate_goal_tag",
        "tag_plan",
        "validate_plan",
    ):
        method = getattr(LLMPort, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"
