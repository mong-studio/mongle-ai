from __future__ import annotations

import logging
import zlib
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import SplitResult
from agents.todo_creation.todo.state import GenerateGraphState

logger = logging.getLogger(__name__)

MAX_TASKS = 20


# 정보량 게이트: 반복뿐인 입력은 잘 압축돼 ratio 가 낮다. 단일 splitter 입력 길이대(짧음)에서
# 실측상 degenerate≈0.65, 정상≈0.84~1.17 로 갈려 0.75 가 안전한 경계다. 긴 자연어도 잘 압축되므로
# 길이대를 벗어나면 판정하지 않는다(긴 컨텍스트 환각은 그라운딩 검증이 따로 잡는다).
_LOW_INFO_THRESHOLD = 0.75
_LOW_INFO_MIN_BYTES = 30
_LOW_INFO_MAX_BYTES = 400


def _is_low_information(text: str) -> bool:
    """압축률로 입력 정보량을 잰다. 반복뿐이라 정보가 거의 없으면 True."""
    raw = text.encode("utf-8")
    if not (_LOW_INFO_MIN_BYTES <= len(raw) <= _LOW_INFO_MAX_BYTES):
        return False
    return len(zlib.compress(raw, 6)) / len(raw) < _LOW_INFO_THRESHOLD


def _char_bigrams(text: str) -> set[str]:
    s = "".join(text.split())
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _is_grounded(title: str, prompt: str) -> bool:
    """title 내용이 입력에 근거하는지 음절 2-gram 겹침으로 느슨히 본다.

    '입력에 없는 단어 금지'는 base 모델이 어기는 프롬프트 부탁일 뿐이라, 파싱 후 코드로 검증해
    '토익'처럼 입력에 없는(특히 긴 컨텍스트에서 사전확률로 튀어나오는) 환각 task 를 떨군다.
    title 은 어미 제거·명사형으로 정규화돼 입력과 글자 그대로 일치하진 않으므로 2-gram 겹침으로 판정한다.
    """
    # ponytail: 음절 2-gram 겹침 휴리스틱. 어간이 살아남는 한국어 정규화엔 충분하다.
    #           정밀 판정이 필요하면 형태소 분석기로 교체.
    tb = _char_bigrams(title)
    if not tb:
        return True  # 1글자 제목 등 너무 짧으면 보수적으로 통과
    return bool(tb & _char_bigrams(prompt))


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
    prompt = state["input"].prompt

    # 정보량 게이트: 반복뿐이라 정보가 거의 없는 입력은 LLM 을 부르지 않고 out_of_scope 안내로.
    if _is_low_information(prompt):
        return {"intent": "out_of_scope"}

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

    # 출력 그라운딩: 입력에 근거 없는 환각 task(예: 긴 컨텍스트에서 튀어나오는 '토익')를 떨군다.
    grounded = [t for t in raw if _is_grounded(t.title, prompt)]
    if not grounded:
        return {"intent": "out_of_scope"}

    return {"intent": "plan", "split_tasks": grounded}
