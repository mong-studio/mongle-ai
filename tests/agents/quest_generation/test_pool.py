from __future__ import annotations

from uuid import uuid4

import pytest

from agents.quest_generation._pool import CharacterPool
from agents.quest_generation.schemas import Character


def _make(name: str) -> Character:
    return Character(
        character_id=uuid4(),
        name=name,
        personality="x",
        speech_style="y",
        appearance_keywords=[],
    )


def test_empty_characters_raises():
    with pytest.raises(ValueError):
        CharacterPool([])


def test_seed_makes_order_deterministic():
    chars = [_make("A"), _make("B"), _make("C")]
    p1 = CharacterPool(chars, seed=42)
    p2 = CharacterPool(chars, seed=42)
    assert [p1.next().name for _ in range(3)] == [p2.next().name for _ in range(3)]


def test_round_no_duplicate_in_first_round():
    chars = [_make("A"), _make("B"), _make("C")]
    pool = CharacterPool(chars, seed=1)
    first_round = {pool.next().character_id for _ in range(3)}
    assert len(first_round) == 3


def test_pool_resets_after_round_exhausted():
    chars = [_make("A"), _make("B")]
    pool = CharacterPool(chars, seed=0)
    [pool.next() for _ in range(2)]
    next_two = {pool.next().character_id for _ in range(2)}
    assert len(next_two) == 2


def test_five_picks_across_three_rounds():
    chars = [_make("A"), _make("B")]
    pool = CharacterPool(chars, seed=0)
    picks = [pool.next() for _ in range(5)]
    assert len(picks) == 5
    assert picks[0].character_id != picks[1].character_id
    assert picks[2].character_id != picks[3].character_id


def test_seed_none_runs_without_error():
    chars = [_make("A"), _make("B"), _make("C")]
    pool = CharacterPool(chars, seed=None)
    assert pool.next() in chars
