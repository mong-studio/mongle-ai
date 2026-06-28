from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.todo_creation.config_utils import get_ports
from agents.todo_creation.exceptions import LLMOutputError
from agents.todo_creation.schemas import SplitResult
from agents.todo_creation.todo.state import GenerateGraphState

logger = logging.getLogger(__name__)

MAX_TASKS = 30


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _is_grounded(title: str, prompt: str) -> bool:
    """title 단어 중 하나라도 입력 어절에 근거하면 통과(환각 task 만 떨군다).

    '입력에 없는 단어 금지'는 프롬프트 부탁일 뿐이라, 파싱 후 코드로 '토익'처럼 입력에 없는
    환각 task 를 떨군다. title 은 어미 제거·명사형으로 정규화돼 조사가 떨어져 나가므로
    (예: '밥을 먹어야지' → '밥 먹기') 글자 n-gram 으론 입력과 어긋난다. 그래서 어절 접두
    매칭으로 본다: 입력 어절이 title 단어로 시작하거나(밥←밥을) 그 반대거나, 공통 접두 2자
    이상(건강하기~건강하고)이면 근거 있다고 본다.
    """
    # ponytail: 어절 접두 매칭 휴리스틱. 1글자 노이즈 매칭을 약간 허용(키워-드롭). 정밀 판정 필요하면 형태소 분석기로.
    words = title.split()
    if not words:
        return True  # 빈 제목 등은 보수적으로 통과
    input_words = prompt.split()
    return any(
        iw.startswith(w) or w.startswith(iw) or _common_prefix_len(w, iw) >= 2
        for w in words
        for iw in input_words
    )


# 한자·가나 등 비한국어 CJK — base 모델이 희귀 음절을 깨뜨릴 때 새는 스크립트.
_CJK_RE = re.compile("[぀-ヿ㄀-ㄯ㐀-䶿一-鿿豈-﫿]")


def _best_input_match(word: str, input_words: list[str]) -> str | None:
    """word 와 가장 닮은 입력 어절을 고른다(없으면 None).
    손상은 보통 첫 음절을 보존하므로 공통 접두(가중치 2배) + 공통 글자수로 점수."""
    best, best_score = None, 0
    wset = set(word)
    for iw in input_words:
        lcp = 0
        for a, b in zip(word, iw):
            if a != b:
                break
            lcp += 1
        score = lcp * 2 + len(wset & set(iw))
        if score > best_score:
            best, best_score = iw, score
    return best


def _repair_title(title: str, prompt: str) -> str:
    """base 모델이 깬 희귀어(예: '두쫀쿠'→'두啭iku')를 입력의 표면형으로 되돌린다.

    디코딩 제약으론 못 고친다 — 모델이 올바른 한국어 토큰에 확률이 없어, 마스킹하면 다른
    garbage 로 갈 뿐(POC 3종으로 확인: char-class·CJK밴 모두 실패). 그래서 사후에, CJK가
    섞인 깨진 어절만 입력의 가장 가까운 어절로 치환해 사용자가 친 글자를 복원한다.
    손상 없는 어절(정규화된 한국어)은 그대로 둔다.
    """
    # ponytail: 어절 단위 char-overlap 정렬 휴리스틱(첫음절 보존 가정). 형태소 분석은 안 한다.
    if not _CJK_RE.search(title):
        return title
    input_words = prompt.split()
    return " ".join(
        (_best_input_match(w, input_words) or w) if _CJK_RE.search(w) else w
        for w in title.split()
    )


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
        # 200자 입력에 들어갈 수 있는 task 는 최대 ~25개라, 30개 초과 = 모델 오동작
        # (입력 문제 아님). 내부 이상 신호로 유지.
        raise LLMOutputError(
            f"task_splitter returned {len(raw)} tasks (max {MAX_TASKS})"
        )

    # 손상 복원: base 모델이 깬 희귀어(두啭iku)를 입력 표면형(두쫀쿠)으로 되돌린다.
    #   디코딩 제약으론 불가(모델이 올바른 토큰에 확률 0, POC 3종 확인) → 사후 복원.
    repaired = [
        t.model_copy(update={"title": _repair_title(t.title, prompt)}) for t in raw
    ]

    # 출력 그라운딩: 입력에 근거 없는 환각 task(예: 긴 컨텍스트에서 튀어나오는 '토익')를 떨군다.
    grounded = [t for t in repaired if _is_grounded(t.title, prompt)]
    if not grounded:
        return {"intent": "out_of_scope"}

    # 중복 제거: 모델이 반복 입력을 같은 task 로 여러 번 쪼개는 경우(밥 먹기 ×3)를 하나로.
    deduped = list({(t.title, t.due_date): t for t in grounded}.values())

    return {"intent": "plan", "split_tasks": deduped}
