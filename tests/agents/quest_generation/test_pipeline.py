from __future__ import annotations

from uuid import uuid4

from agents.quest_generation.pipeline import Ports, run
from agents.quest_generation.schemas import (
    Character,
    QuestGenerationInput,
    TodoRef,
)
from tests.agents.quest_generation.fakes import FakeLLM


def _char(name: str = "X") -> Character:
    return Character(
        character_id=uuid4(),
        name=name,
        personality="p",
        speech_style="s",
        appearance_keywords=[],
    )


def _todo() -> TodoRef:
    return TodoRef(todo_id=uuid4())


async def test_empty_todos_short_circuits():
    inp = QuestGenerationInput(
        todos=[],
        characters=[_char()],
        remaining_daily_quota=5,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert result.generated == []
    assert result.skipped == []
    assert llm.calls == []


async def test_empty_characters_short_circuits():
    inp = QuestGenerationInput(
        todos=[_todo()],
        characters=[],
        remaining_daily_quota=5,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert result.generated == []
    assert result.skipped == []
    assert llm.calls == []


async def test_zero_quota_short_circuits():
    inp = QuestGenerationInput(
        todos=[_todo()],
        characters=[_char()],
        remaining_daily_quota=0,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert result.generated == []
    assert llm.calls == []


async def test_cap_min_of_todos_and_quota():
    # 5 todos, quota 2 → process only 2
    inp = QuestGenerationInput(
        todos=[_todo() for _ in range(5)],
        characters=[_char("A")],
        remaining_daily_quota=2,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert len(result.generated) == 2
    assert len(result.skipped) == 0
    assert len(llm.calls) == 2


async def test_one_to_one_to_one_mapping_within_round():
    chars = [_char("A"), _char("B"), _char("C")]
    todos = [_todo() for _ in range(3)]
    inp = QuestGenerationInput(
        todos=todos,
        characters=chars,
        remaining_daily_quota=10,
        shuffle_seed=0,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert len(result.generated) == 3
    used_char_ids = {g.character_id for g in result.generated}
    assert len(used_char_ids) == 3
    assert {g.todo_id for g in result.generated} == {t.todo_id for t in todos}


async def test_round_reset_after_pool_exhaustion():
    # 2 characters, 3 todos → one character used twice across rounds
    chars = [_char("A"), _char("B")]
    inp = QuestGenerationInput(
        todos=[_todo() for _ in range(3)],
        characters=chars,
        remaining_daily_quota=10,
        shuffle_seed=0,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert len(result.generated) == 3
    char_counts: dict = {}
    for g in result.generated:
        char_counts[g.character_id] = char_counts.get(g.character_id, 0) + 1
    assert sorted(char_counts.values()) == [1, 2]


async def test_c5_isolation_llm_receives_only_character():
    inp = QuestGenerationInput(
        todos=[_todo() for _ in range(2)],
        characters=[_char("A")],
        remaining_daily_quota=10,
    )
    llm = FakeLLM()
    await run(inp, ports=Ports(llm=llm))
    # FakeLLM.generate_quest only accepts `character=...` kwarg.
    # If pipeline tried to pass a TodoRef the call would TypeError.
    for c in llm.calls:
        assert isinstance(c, Character)


async def test_partial_failure_skipped_separated():
    # LLM fails for first 3 attempts (exhausts retries on first todo),
    # then succeeds. So first todo is skipped, second is generated.
    inp = QuestGenerationInput(
        todos=[_todo(), _todo()],
        characters=[_char("A")],
        remaining_daily_quota=10,
    )
    llm = FakeLLM(fail_times=3)
    result = await run(inp, ports=Ports(llm=llm))
    assert len(result.generated) == 1
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "llm_failure"
    assert result.skipped[0].todo_id == inp.todos[0].todo_id
    assert result.generated[0].todo_id == inp.todos[1].todo_id


async def test_processes_todos_in_input_order():
    todos = [_todo() for _ in range(4)]
    inp = QuestGenerationInput(
        todos=todos,
        characters=[_char("A")],
        remaining_daily_quota=10,
    )
    llm = FakeLLM()
    result = await run(inp, ports=Ports(llm=llm))
    assert [g.todo_id for g in result.generated] == [t.todo_id for t in todos]
