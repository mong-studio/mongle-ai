from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from agents.todo_creation.exceptions import LLMFailedError
from agents.todo_creation.schemas import (
    AgentDecision,
    ChatMessage,
    ParsedGoal,
    PlanDraft,
    PlannerJudgment,
    TaggedPlan,
)


@dataclass
class FakeMultiTurnLLM:
    """Scripted MultiTurnLLMPort for tests.

    Response lists are FIFO queues. `fail_times_<method>` raises LLMFailedError
    that many times before any response is popped.
    """

    judge_responses: list[PlannerJudgment] = field(default_factory=list)
    follow_up_responses: list[str] = field(default_factory=list)
    plan_responses: list[PlanDraft] = field(default_factory=list)
    tag_responses: list[TaggedPlan] = field(default_factory=list)
    agent_decisions: list[AgentDecision] = field(default_factory=list)

    fail_times_judge: int = 0
    fail_times_follow_up: int = 0
    fail_times_plan: int = 0
    fail_times_tag: int = 0
    fail_times_agent: int = 0

    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_plan_edit_instructions: list[str | None] = field(default_factory=list)

    async def judge_planner(
        self, *, history: list[ChatMessage], previous_goal: ParsedGoal | None, today: date
    ) -> PlannerJudgment:
        self.calls["judge_planner"] += 1
        if self.fail_times_judge > 0:
            self.fail_times_judge -= 1
            raise LLMFailedError("simulated judge failure")
        assert self.judge_responses, "unexpected judge_planner call"
        return self.judge_responses.pop(0)

    async def generate_follow_up(
        self, *, missing_aspects: list[str], history: list[ChatMessage]
    ) -> str:
        self.calls["generate_follow_up"] += 1
        if self.fail_times_follow_up > 0:
            self.fail_times_follow_up -= 1
            raise LLMFailedError("simulated follow_up failure")
        assert self.follow_up_responses, "unexpected generate_follow_up call"
        return self.follow_up_responses.pop(0)

    async def generate_plan(
        self,
        *,
        parsed_goal: ParsedGoal,
        today: date,
        edit_instructions: str | None,
    ) -> PlanDraft:
        self.calls["generate_plan"] += 1
        self.last_plan_edit_instructions.append(edit_instructions)
        if self.fail_times_plan > 0:
            self.fail_times_plan -= 1
            raise LLMFailedError("simulated plan failure")
        assert self.plan_responses, "unexpected generate_plan call"
        return self.plan_responses.pop(0)

    async def tag_plan(
        self, *, plan_draft: PlanDraft, parsed_goal: ParsedGoal
    ) -> TaggedPlan:
        self.calls["tag_plan"] += 1
        if self.fail_times_tag > 0:
            self.fail_times_tag -= 1
            raise LLMFailedError("simulated tag failure")
        assert self.tag_responses, "unexpected tag_plan call"
        return self.tag_responses.pop(0)

    async def edit_agent_step(
        self, *, history: list[ChatMessage], current_plan: TaggedPlan
    ) -> AgentDecision:
        self.calls["edit_agent_step"] += 1
        if self.fail_times_agent > 0:
            self.fail_times_agent -= 1
            raise LLMFailedError("simulated agent failure")
        assert self.agent_decisions, "unexpected edit_agent_step call"
        return self.agent_decisions.pop(0)
