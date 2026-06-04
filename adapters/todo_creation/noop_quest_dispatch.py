from __future__ import annotations


class NoOpQuestDispatch:
    """QuestDispatchPort no-op 구현.

    무상태 모델(ADR-0004)에서 commit 은 quest 를 직접 디스패치하지 않는다.
    quest_distribution_triggered 플래그만 반환하고, 실제 quest 생성은
    Django 가 /v1/quest/generate 를 이어서 호출해 처리한다.
    """

    async def dispatch(self, *, user_id: str) -> None:
        return None
