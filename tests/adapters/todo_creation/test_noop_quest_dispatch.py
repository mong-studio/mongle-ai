import pytest

from adapters.todo_creation.noop_quest_dispatch import NoOpQuestDispatch


@pytest.mark.asyncio
async def test_dispatch_does_nothing():
    assert await NoOpQuestDispatch().dispatch(user_id="u1") is None
