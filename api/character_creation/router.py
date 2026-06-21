from __future__ import annotations

import asyncio
import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from adapters._shared.runpod_warmup import warm_character_endpoints
from agents.character_creation import pipeline as character_pipeline
from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.character_creation.schemas import (
    CharacterCreationInput,
    CharacterEntity,
    SourceImage,
)
from api.character_creation.jobs import CharacterJobStore, JobState
from api.character_creation.schemas import CharacterCreationRequest, CharacterJobRef
from api.config import AppConfig
from api.deps import build_character_ports
from api.deps import fetch_source_bytes as _fetch_source_bytes
from api.deps import get_config
from api.envelope import Envelope, ErrorBody, done
from api.security import require_api_key

log = logging.getLogger(__name__)

# 예열 백그라운드 태스크 참조 보관(GC 방지). 완료 시 콜백으로 제거.
_warmup_tasks: set[asyncio.Task] = set()

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


def get_job_store(request: Request) -> CharacterJobStore:
    """앱 전역 인메모리 잡 스토어. lifespan 이 우회된 테스트에선 지연 생성."""
    store = getattr(request.app.state, "character_jobs", None)
    if store is None:
        store = CharacterJobStore()
        request.app.state.character_jobs = store
    return store


async def _run_job(
    *,
    store: CharacterJobStore,
    job_id: str,
    cfg: AppConfig,
    body: CharacterCreationRequest,
    ports_builder: Callable,
    fetcher: Callable,
) -> None:
    """백그라운드에서 파이프라인을 실행하고 결과를 잡 스토어에 기록한다."""
    try:
        source_image: SourceImage | None = None
        if body.source_image_key:
            content_type = body.source_image_content_type or "image/png"
            data = await fetcher(
                cfg, key=body.source_image_key, content_type=content_type
            )
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
        store.mark_done(job_id, entity)
    except Exception as err:  # noqa: BLE001 - 잡 실패는 폴링으로 전달한다
        log.exception("character generation job failed: job_id=%s", job_id)
        store.mark_error(
            job_id, code="character_generation_failed", message=str(err)
        )


@router.post(
    "/character",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[CharacterJobRef],
)
async def create_character(
    body: CharacterCreationRequest,
    cfg: AppConfig = Depends(get_config),
    ports_builder: Callable = Depends(get_character_ports),
    fetcher: Callable = Depends(fetch_source_bytes),
    store: CharacterJobStore = Depends(get_job_store),
) -> Envelope[CharacterJobRef]:
    """캐릭터 생성을 비동기 잡으로 등록하고 즉시 job_id 를 반환한다.

    이미지 생성이 RunPod Pod 프록시의 100s 타임아웃을 넘기므로,
    실제 생성은 백그라운드 태스크로 분리하고 호출자는 GET 으로 폴링한다.
    """
    job_id = store.create()
    task = asyncio.create_task(
        _run_job(
            store=store,
            job_id=job_id,
            cfg=cfg,
            body=body,
            ports_builder=ports_builder,
            fetcher=fetcher,
        )
    )
    store.track_task(task)
    return Envelope(status="pending", result=CharacterJobRef(job_id=job_id))


@router.get("/character/{job_id}", response_model=Envelope[CharacterEntity])
async def get_character_job(
    job_id: str,
    store: CharacterJobStore = Depends(get_job_store),
) -> Envelope[CharacterEntity]:
    """잡 상태/결과를 폴링한다. 완료 시 result=CharacterEntity(appearance 포함)."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="잡을 찾을 수 없습니다"
        )
    if job.state is JobState.DONE:
        assert job.result is not None
        return done(job.result)
    if job.state is JobState.ERROR:
        return Envelope(
            status="error",
            error=ErrorBody(
                code=job.error_code or "character_generation_failed",
                message=job.error_message or "",
            ),
        )
    return Envelope(status="pending", result=None)


@router.post("/character/warmup", status_code=status.HTTP_202_ACCEPTED)
async def warmup_character(cfg: AppConfig = Depends(get_config)) -> dict[str, str]:
    """캐릭터 생성 화면 진입 시 호출. 콜드인 엔드포인트만 예열하고 즉시 반환한다.

    예열은 best-effort 백그라운드 작업이며 실패해도 무시한다. health-gate 라
    워커가 이미 떠 있거나 꽉 차 있으면 아무 잡도 던지지 않는다.
    """
    task = asyncio.create_task(
        warm_character_endpoints(
            llm_url=cfg.runpod_village_endpoint_url,
            image_url=cfg.runpod_image_endpoint_url,
            api_key=cfg.runpod_api_key,
        )
    )
    _warmup_tasks.add(task)
    task.add_done_callback(_warmup_tasks.discard)
    return {"status": "warming"}
