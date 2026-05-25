from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date

from openai import AsyncOpenAI

from agents.todo_creation.exceptions import LLMFailedError, LLMOutputError
from agents.todo_creation.multi_turn.tools import TOOL_DEFINITIONS
from agents.todo_creation.schemas import (
    AgentDecision, ChatMessage, ParsedGoal, PlanDraft, PlannerJudgment, TaggedPlan,
)


@dataclass
class OpenAIMultiTurnLLM:
    model: str = "gpt-4o-mini"
    client: AsyncOpenAI | None = None

    def _client(self) -> AsyncOpenAI:
        if self.client is None:
            self.client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return self.client

    async def judge_planner(self, *, history, previous_goal, today) -> PlannerJudgment:
        try:
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"오늘은 {today.isoformat()}. "
                            "사용자 메시지와 이전 goal 로부터 정보 충분성 판단. "
                            "이전 parsed_goal 을 보존하며 새 정보로 갱신. "
                            f"이전 parsed_goal: {previous_goal.model_dump_json() if previous_goal else 'null'}"
                        ),
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
                response_format=PlannerJudgment,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def generate_follow_up(self, *, missing_aspects, history) -> str:
        try:
            resp = await self._client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"한국어 1~2문장의 짧은 꼬리 질문 생성. 부족 정보: {', '.join(missing_aspects)}",
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
            )
            content = resp.choices[0].message.content
            if not content:
                raise LLMOutputError("empty follow_up")
            return content.strip()
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def generate_plan(self, *, parsed_goal, today, edit_instructions) -> PlanDraft:
        try:
            sys_prompt = (
                f"오늘은 {today.isoformat()}. "
                "주어진 parsed_goal 에 맞춰 일자별 플랜 JSON 생성. "
                "summary_text 는 ≤1500자 한국어."
            )
            if edit_instructions:
                sys_prompt += f"\n[수정 지침] {edit_instructions}"
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": parsed_goal.model_dump_json()},
                ],
                response_format=PlanDraft,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def tag_plan(self, *, plan_draft, parsed_goal) -> TaggedPlan:
        try:
            resp = await self._client().beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "plan_draft 의 각 task 에 자유 형식 한국어 태그 부여. "
                            f"목표 컨텍스트: {parsed_goal.model_dump_json()}"
                        ),
                    },
                    {"role": "user", "content": plan_draft.model_dump_json()},
                ],
                response_format=TaggedPlan,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                raise LLMOutputError("parse returned None")
            return parsed
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e

    async def edit_agent_step(self, *, history, current_plan) -> AgentDecision:
        try:
            resp = await self._client().chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "현재 플랜과 사용자 메시지를 보고 적절한 도구 호출. "
                            "사용자 수정 요청 → regenerate_plan(instructions), 확정 의도 → confirm(). "
                            f"\n현재 플랜: {current_plan.model_dump_json()}"
                        ),
                    },
                    *[{"role": m.role, "content": m.content} for m in history],
                ],
                tools=[{"type": "function", "function": t} for t in TOOL_DEFINITIONS],
                tool_choice="required",
            )
            tool_calls = resp.choices[0].message.tool_calls or []
            if not tool_calls:
                raise LLMOutputError("no tool_call returned")
            call = tool_calls[0]
            args = json.loads(call.function.arguments or "{}")
            return AgentDecision(tool_name=call.function.name, tool_args=args)
        except LLMOutputError:
            raise
        except Exception as e:
            raise LLMFailedError(str(e)) from e
