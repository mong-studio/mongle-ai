from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import SplitResult
from agents.todo_creation.todo.state import GenerateGraphState

logger = logging.getLogger(__name__)

MAX_TASKS = 20


def _collapse_repeated_stems(text: str, *, min_run: int = 3, min_stem: int = 2) -> str:
    """같은 어간(앞 min_stem자)을 공유하는 토큰이 min_run개 이상 연속되면 첫 토큰 하나로 압축.

    '건강하고 건강하며 건강한데 또 건강했다가 건강하려다가 건강해야해' 같은 반복 입력이
    base 모델을 루프/파싱붕괴로 몰지 않도록 LLM 호출 전에 신호를 정리한다. 정상 문장은
    같은 어간 토큰이 3개 이상 연속될 일이 드물어 거의 건드리지 않는다.
    """
    # ponytail: 공백 토큰 + 접두 비교만 하는 휴리스틱. 형태소 분석이 필요할 만큼 정밀하진 않다.
    #           오탐이 문제되면 min_run 을 올리거나 형태소 분석기로 교체.
    tokens = text.split()
    if len(tokens) < min_run:
        return text
    out: list[str] = []
    i = 0
    while i < len(tokens):
        stem = tokens[i][:min_stem]
        j = i + 1
        if len(stem) >= min_stem:
            while j < len(tokens) and tokens[j][:min_stem] == stem:
                j += 1
        if j - i >= min_run:
            out.append(tokens[i])  # 반복 런 → 대표 토큰 하나로
        else:
            out.extend(tokens[i:j])
        i = j
    return " ".join(out)


async def _split_or_out_of_scope(
    ports: Any, prompt: str, today: date
) -> SplitResult | None:
    """분해를 시도하되, 모델이 끝내 파싱 가능한 출력을 못 내면(반복·무의미 입력)
    에러로 터뜨리지 않고 None 을 돌려 out_of_scope 안내로 강등한다.
    LLMFailedError(서버 다운/timeout)는 진짜 인프라 장애이므로 그대로 전파한다."""
    try:
        return await ports.llm.split_tasks(prompt=prompt, today=today)
    except LLMOutputError as err:
        logger.info("task_splitter unparseable → out_of_scope: %s", err)
        return None


async def task_splitter_node(
    state: GenerateGraphState, config: RunnableConfig
) -> dict[str, Any]:
    # split_tasks(뉴로-심볼릭)가 task별 when 구문 추출 + 절대날짜 변환(과거 클램프 포함)을
    # 모두 끝낸 TaskCandidate 를 돌려준다. 노드는 분기/한도 검증만 한다.
    ports = get_ports(config)
    today = state["input"].today
    # 반복 어절을 LLM 호출 전에 압축해 루프/파싱붕괴를 줄이고 깔끔한 신호를 준다.
    prompt = _collapse_repeated_stems(state["input"].prompt)

    split = await _split_or_out_of_scope(ports, prompt, today)
    if split is None or split.intent == "out_of_scope":
        return {"intent": "out_of_scope"}

    raw = split.tasks
    if not raw:
        # B2: one retry on empty (plan 인데 비었을 때만)
        split = await _split_or_out_of_scope(ports, prompt, today)
        if split is None or split.intent == "out_of_scope":
            return {"intent": "out_of_scope"}
        raw = split.tasks
        if not raw:
            # 재시도 후에도 빈 결과 = 나눌 수 없는 입력 → 친절 안내로 폴백
            return {"intent": "out_of_scope"}

    if len(raw) > MAX_TASKS:
        # 한 문장에서 20개 초과 = 모델 오동작(입력 문제 아님). 내부 이상 신호로 유지.
        raise LLMOutputError(
            f"task_splitter returned {len(raw)} tasks (max {MAX_TASKS})"
        )

    return {"intent": "plan", "split_tasks": list(raw)}
