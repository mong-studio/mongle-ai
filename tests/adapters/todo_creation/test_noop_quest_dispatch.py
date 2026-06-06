import pytest

from adapters.todo_creation.noop_quest_dispatch import NoOpQuestDispatch


@pytest.mark.asyncio
async def test_dispatch_does_nothing():
    """no-op 디스패치는 아무 동작 없이 None을 반환한다."""
    assert await NoOpQuestDispatch().dispatch(user_id="u1") is None
