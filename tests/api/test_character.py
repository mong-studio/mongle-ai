from __future__ import annotations

import pytest

from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.character_creation.schemas import LLMPersonaResult
from api.character_creation.router import fetch_source_bytes, get_character_ports
from tests.api.conftest import AUTH


class _FakeLLM:
    async def generate_persona(self, *, persona, keywords):
        return LLMPersonaResult(personality="용감", speech_style="반말", background="숲")


class _FakeImage:
    async def generate(self, *, user_id, llm_result, fallback_persona, source_image_bytes):
        return b"\x89PNG generated"


class _FakeS3:
    async def put_object(self, *, key, body, content_type):
        return f"https://s3/{key}"

    async def delete_object(self, *, key):
        return None


class _FakeRepo:
    async def increment(self, user_id):
        return 1

    async def save(self, entity):
        return None


def _ports_builder():
    def _build(source_url=""):
        return CharacterPorts(
            llm=_FakeLLM(), s3=_FakeS3(), image_generator=_FakeImage(), repository=_FakeRepo()
        )
    return _build


async def _fake_fetch(cfg, *, key, content_type):
    return b"\x89PNG source"


def _fetch_override():
    return _fake_fetch


def test_character_returns_entity_envelope(api_client):
    api_client.app.dependency_overrides[get_character_ports] = _ports_builder
    api_client.app.dependency_overrides[fetch_source_bytes] = _fetch_override
    body = {
        "user_id": "u1",
        "name": "몽글이",
        "persona": "용감한 탐험가",
        "personality_keywords": ["용감한"],
        "source_image_key": "sources/u1/abc.png",
        "source_image_url": "https://web/src.png",
        "source_image_content_type": "image/png",
    }
    resp = api_client.post("/v1/character", json=body, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["name"] == "몽글이"
    assert data["result"]["image_url"]


def test_character_requires_api_key(api_client):
    assert api_client.post("/v1/character", json={}).status_code == 401
