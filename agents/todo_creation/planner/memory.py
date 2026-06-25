"""대화 history 롤링 요약 — 무한 증가 방지 + memory_summary 배선.

follow_up 으로 history 가 길어지면 오래된 턴을 LLM 요약 한 줄로 접어
(요약 1턴 + 최근 턴) 형태로 bounded 하게 유지한다. 요약이 불가능하거나
실패하면 단순 절단으로 폴백해 그래프는 항상 진행한다.

memory_summary state 필드는 이 요약 텍스트를 보관한다(관찰/디버그용).
"""

from __future__ import annotations

from typing import Any

from agents.todo_creation.state import Turn

# ponytail: 그래프가 follow_up 을 최대 2라운드(=4턴)로 제한하므로 trigger 는
# 그 안에서 도달 가능해야 한다(6 이면 영영 안 접혀 memory_summary 가 inert).
# 2회 되묻기(4턴) > 3 → fold 발동, 마지막 Q&A 1쌍만 원문 유지.
_KEEP_RECENT = 2  # 최근 턴은 원문 유지
_FOLD_TRIGGER = 3  # history 가 이보다 길면 오래된 부분을 요약으로 접는다
_SUMMARY_PREFIX = "[이전 대화 요약] "
_MAX_SUMMARY_CHARS = 1000


async def fold_history(
    history: list[Turn] | None,
    memory_summary: dict | None,
    *,
    llm: Any,
) -> tuple[list[Turn], dict | None]:
    """길어진 history 를 (요약 1턴 + 최근 턴) 으로 접는다.

    trigger 이하이면 그대로 돌려준다. 반환: (new_history, memory_summary).
    """
    turns: list[Turn] = list(history or [])
    if len(turns) <= _FOLD_TRIGGER:
        return turns, memory_summary

    recent = turns[-_KEEP_RECENT:]
    older = turns[:-_KEEP_RECENT]

    summary_text = await _summarize(older, llm)
    if not summary_text:
        # 요약 불가/실패 → 오래된 턴은 버리고 최근만 유지(메모리는 여전히 bounded).
        return recent, memory_summary

    folded: list[Turn] = [
        {"role": "assistant", "content": _SUMMARY_PREFIX + summary_text},
        *recent,
    ]
    return folded, {"text": summary_text}


async def _summarize(turns: list[Turn], llm: Any) -> str:
    summarize = getattr(llm, "summarize_history", None)
    if summarize is None:
        return ""
    try:
        text = await summarize(turns=turns)
    except Exception:  # noqa: BLE001 - 요약 실패는 절단으로 폴백
        return ""
    return str(text or "").strip()[:_MAX_SUMMARY_CHARS]
