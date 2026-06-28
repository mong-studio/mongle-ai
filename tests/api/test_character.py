from __future__ import annotations

import asyncio

import httpx

from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.character_creation.schemas import ImageGenerationResult, LLMPersonaResult
from api.character_creation.jobs import CharacterJobStore
from api.character_creation.router import fetch_source_bytes, get_character_ports
from api.main import create_app
from tests.api.conftest import AUTH, make_config


class _FakeLLM:
    async def generate_persona(self, *, name, persona, keywords):
        return LLMPersonaResult(
            personality="용감", speech_style="반말", background="숲", appearance="둥근 갈색 몸",
            appearance_en="round brown body, big eyes",
        )


class _FakeImage:
    async def generate(self, *, user_id, llm_result, fallback_persona, source_image_bytes):
        return ImageGenerationResult(
            image_bytes=b"\x89PNG generated",
            appearance_payload={"character_type": "bear", "main_colors": ["brown"]},
        )


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
            llm=_FakeLLM(),
            s3=_FakeS3(),
            image_generator=_FakeImage(),
            repository=_FakeRepo(),
        )
    return _build


async def _fake_fetch(cfg, *, key, content_type):
    return b"\x89PNG source"


def _fetch_override():
    return _fake_fetch


def _make_app():
    """단일 이벤트 루프 위에서 백그라운드 잡을 검증하기 위한 앱(테스트용 state 주입)."""
    app = create_app()
    app.state.config = make_config()
    app.state.image_generator = None
    app.state.character_jobs = CharacterJobStore()
    app.dependency_overrides[get_character_ports] = _ports_builder
    app.dependency_overrides[fetch_source_bytes] = _fetch_override
    return app


async def _submit_and_poll(body, *, attempts=100):
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/character", json=body, headers=AUTH)
        assert resp.status_code == 202
        assert resp.json()["status"] == "pending"
        job_id = resp.json()["result"]["job_id"]

        data = {"status": "pending"}
        for _ in range(attempts):
            await asyncio.sleep(0)
            poll = await client.get(f"/v1/character/{job_id}", headers=AUTH)
            data = poll.json()
            if data["status"] != "pending":
                break
        return data


# ---- 동기(즉시 응답) 케이스 ----

def test_character_submit_returns_pending_job_id(api_client):
    """POST /v1/character는 202와 함께 폴링용 job_id를 pending 봉투로 반환한다."""
    api_client.app.dependency_overrides[get_character_ports] = _ports_builder
    api_client.app.dependency_overrides[fetch_source_bytes] = _fetch_override
    resp = api_client.post(
        "/v1/character",
        json={
            "user_id": "u1",
            "name": "몽글이",
            "persona": "용감한 탐험가",
            "personality_keywords": ["용감한"],
        },
        headers=AUTH,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "pending"
    assert data["result"]["job_id"]


def test_character_poll_unknown_job_returns_404(api_client):
    """존재하지 않는 job_id 폴링은 404를 반환한다."""
    resp = api_client.get("/v1/character/does-not-exist", headers=AUTH)
    assert resp.status_code == 404


def test_character_submit_requires_api_key(api_client):
    """API 키 없이 POST 호출 시 401을 반환한다."""
    assert api_client.post("/v1/character", json={}).status_code == 401


def test_character_poll_requires_api_key(api_client):
    """API 키 없이 GET 폴링 호출 시 401을 반환한다."""
    assert api_client.get("/v1/character/whatever").status_code == 401


# ---- 비동기(백그라운드 완료) 케이스 ----

async def test_character_poll_text_only_saves_appearance():
    """텍스트만 입력 → 완료 시 entity에 appearance가 채워진다(visual 소스)."""
    data = await _submit_and_poll(
        {
            "user_id": "u1",
            "name": "몽글이",
            "persona": "용감한 탐험가",
            "personality_keywords": ["용감한"],
        }
    )
    assert data["status"] == "done"
    assert data["result"]["name"] == "몽글이"
    assert data["result"]["image_url"]
    assert data["result"]["appearance"] == "round brown body, big eyes"
    assert data["result"]["source_image_url"] is None


async def test_character_poll_with_image_saves_appearance():
    """이미지까지 입력 → 완료 시 source_image_url과 appearance가 모두 저장된다."""
    data = await _submit_and_poll(
        {
            "user_id": "u1",
            "name": "몽글이",
            "persona": "용감한 탐험가",
            "personality_keywords": ["용감한"],
            "source_image_key": "sources/u1/abc.png",
            "source_image_url": "https://web/src.png",
            "source_image_content_type": "image/png",
        }
    )
    assert data["status"] == "done"
    assert data["result"]["appearance"] == "round brown body, big eyes"
    # 이미지를 보냈으므로 원본 업로드 URL이 채워진다(fake S3는 sources/ 키로 반환).
    assert data["result"]["source_image_url"] is not None
    assert "sources/" in data["result"]["source_image_url"]
