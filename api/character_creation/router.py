from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Request

from agents.character_creation import pipeline as character_pipeline
from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    SourceImage,
)
from api.config import AppConfig
from api.deps import build_character_ports
from api.deps import fetch_source_bytes as _fetch_source_bytes
from api.deps import get_config
from api.character_creation.schemas import CharacterCreationRequest
from api.envelope import Envelope, done
from api.security import require_api_key

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


def fetch_source_bytes() -> Callable:
    """다운로더 함수를 주입 가능하게 감싼 의존성(테스트 override 지점)."""
    return _fetch_source_bytes


def get_character_ports(request: Request) -> Callable:
    """ports 빌더(source_url 인자를 받는 callable)를 반환. 테스트 override 지점."""

    def _build(source_url: str = "") -> CharacterPorts:
        return build_character_ports(
            request, request.app.state.config, source_url=source_url
        )

    return _build


@router.post("/character", response_model=Envelope[CharacterEntity])
async def create_character(
    body: CharacterCreationRequest,
    cfg: AppConfig = Depends(get_config),
    ports_builder: Callable = Depends(get_character_ports),
    fetcher: Callable = Depends(fetch_source_bytes),
) -> Envelope[CharacterEntity]:
    source_image: SourceImage | None = None
    if body.source_image_key:
        content_type = body.source_image_content_type or "image/png"
        data = await fetcher(cfg, key=body.source_image_key, content_type=content_type)
        source_image = SourceImage(
            filename=body.source_image_key.rsplit("/", 1)[-1],
            content_type=content_type,
            data=data,
        )

    pipeline_input = CharacterCreationInput(
        user_id=body.user_id,
        name=body.name,
        persona=body.persona,
        personality_keywords=body.personality_keywords,
        source_image=source_image,
    )
    ports = ports_builder(body.source_image_url or "")
    entity = await character_pipeline.run(pipeline_input, ports=ports)
    return done(entity)
