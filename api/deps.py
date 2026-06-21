from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.passthrough_s3 import PassthroughSourceS3
from adapters.character_creation.qwen_llm import QwenLLM as QwenCharacterLLM
from adapters.feed_generation.qwen_llm import QwenLLM as QwenFeedLLM
from adapters.feed_generation.s3_adapter import FeedS3Adapter
from adapters.quest_generation.fake_llm import FakeLLM as FakeQuestLLM
from adapters.quest_generation.qwen_llm import QwenLLM as QwenQuestLLM
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from adapters.todo_creation.qwen_llm import QwenLLM as QwenTodoLLM
from adapters.todo_creation.noop_quest_dispatch import NoOpQuestDispatch
from adapters.todo_creation.request_quest_counter import RequestQuestCounter
from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.feed_generation.pipeline import Ports as FeedPorts
from agents.quest_generation.pipeline import Ports as QuestPorts
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.planner.pipeline import PlannerPorts
from agents.todo_creation.todo.pipeline import GeneratePorts

from api.character_creation.jobs import CharacterJobStore
from api.config import AppConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 설정 1회 로드. 이미지 생성기는 첫 character 요청에서 지연 생성."""
    app.state.config = AppConfig.from_env()
    app.state.image_generator = None
    app.state.character_jobs = CharacterJobStore()
    yield


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def _build_character_llm(cfg: AppConfig):
    if cfg.llm_provider == "runpod":
        from adapters.character_creation.runpod_llm import RunPodQwenLLM as RunPodCharacterLLM

        if not cfg.runpod_character_endpoint_url:
            raise RuntimeError(
                "LLM_PROVIDER=runpod 인데 RUNPOD_CHARACTER_ENDPOINT_URL 이 없습니다"
            )
        return RunPodCharacterLLM(
            endpoint_url=cfg.runpod_character_endpoint_url,
            api_key=cfg.runpod_api_key,
            adapter="character",
        )
    if cfg.llm_provider == "qwen":
        assert cfg.qwen_base_url and cfg.qwen_persona_model
        return QwenCharacterLLM(
            model=cfg.qwen_persona_model,
            base_url=cfg.qwen_base_url,
            api_key=cfg.qwen_api_key,
        )
    raise RuntimeError("character LLM 은 Qwen 또는 RunPod 전용입니다 — LLM_PROVIDER=qwen|runpod 으로 설정하세요")


def _build_translator(cfg: AppConfig):
    """appearance(한국어)→영어 번역기. base Qwen(no-LoRA)을 쓴다."""
    if cfg.llm_provider == "runpod":
        from adapters.character_creation.runpod_translator import RunPodTranslator

        if not cfg.runpod_planner_endpoint_url:
            raise RuntimeError(
                "LLM_PROVIDER=runpod 인데 RUNPOD_PLANNER_ENDPOINT_URL 이 없습니다"
            )
        return RunPodTranslator(
            endpoint_url=cfg.runpod_planner_endpoint_url, api_key=cfg.runpod_api_key
        )
    from adapters.character_creation.qwen_translator import QwenTranslator

    if not (cfg.qwen_base_url and cfg.qwen_model):
        raise RuntimeError(
            "appearance 번역은 Qwen 또는 RunPod 필요 — QWEN_BASE_URL/QWEN_MODEL 을 설정하세요"
        )
    return QwenTranslator(
        model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
    )


def _build_todo_llm(cfg: AppConfig, *, adapter: str = "planner"):
    if cfg.llm_provider == "runpod":
        from adapters.todo_creation.runpod_llm import RunPodQwenLLM as RunPodTodoLLM

        if not cfg.runpod_planner_endpoint_url:
            raise RuntimeError(
                "LLM_PROVIDER=runpod 인데 RUNPOD_PLANNER_ENDPOINT_URL 이 없습니다"
            )
        return RunPodTodoLLM(
            endpoint_url=cfg.runpod_planner_endpoint_url,
            api_key=cfg.runpod_api_key,
            adapter=adapter,
        )
    if not (cfg.qwen_base_url and cfg.qwen_model):
        raise RuntimeError(
            "TODO 생성은 Qwen 전용입니다 — QWEN_BASE_URL/QWEN_MODEL 이 필요합니다"
        )
    return QwenTodoLLM(
        model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
    )


def _build_quest_llm(cfg: AppConfig):
    if cfg.quest_llm_provider == "runpod":
        from adapters.quest_generation.runpod_llm import RunPodQwenLLM as RunPodQuestLLM

        if not cfg.runpod_planner_endpoint_url:
            raise RuntimeError(
                "QUEST_LLM_PROVIDER=runpod 인데 RUNPOD_PLANNER_ENDPOINT_URL 이 없습니다"
            )
        return RunPodQuestLLM(
            endpoint_url=cfg.runpod_planner_endpoint_url,
            api_key=cfg.runpod_api_key,
            adapter="quest",
        )
    assert cfg.qwen_base_url and cfg.qwen_model
    return QwenQuestLLM(
        model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
    )


def _get_image_generator(request: Request):
    """이미지 생성기를 앱 전체에서 한 번만 만들어 재사용(지연).

    runpod: 원격 RunPod Serverless 워커 호출 (GPU 불필요)
    local: 로컬 LoRA 디퓨전 파이프라인 로드 (GPU 권장)
    """
    if request.app.state.image_generator is None:
        cfg: AppConfig = request.app.state.config
        if cfg.image_provider == "runpod":
            from adapters.character_creation.runpod_image import RunPodImageGenerator

            if not cfg.runpod_image_endpoint_url:
                raise RuntimeError(
                    "IMAGE_PROVIDER=runpod 인데 RUNPOD_IMAGE_ENDPOINT_URL 이 없습니다"
                )
            request.app.state.image_generator = RunPodImageGenerator(
                endpoint_url=cfg.runpod_image_endpoint_url,
                api_key=cfg.runpod_api_key,
            )
        else:
            from adapters.character_creation.lora_image import LoRAImageGenerator

            request.app.state.image_generator = LoRAImageGenerator(
                lora_dir=cfg.lora_dir
            )
    return request.app.state.image_generator


def _s3_client(cfg: AppConfig):
    """리전 엔드포인트를 명시한 boto3 S3 client.

    endpoint_url 없이 client 를 만들면 presigned URL 이 글로벌 엔드포인트
    (s3.amazonaws.com)로 생성되고, GET 시 S3 가 리전 엔드포인트로 307 리다이렉트
    하면서 Host 가 바뀌어 SigV4 서명(SignedHeaders=host)이 깨지고 403 이 난다.
    리전 엔드포인트를 명시해 presigned host 를 리전형으로 고정한다.
    """
    import boto3

    endpoint_url = (
        f"https://s3.{cfg.aws_region}.amazonaws.com" if cfg.aws_region else None
    )
    return boto3.client("s3", region_name=cfg.aws_region, endpoint_url=endpoint_url)


def _build_storage(cfg: AppConfig):
    if cfg.storage_backend == "s3":
        from adapters.character_creation.s3_storage import S3Storage

        return S3Storage(
            client=_s3_client(cfg),
            bucket=cfg.aws_s3_bucket or "",
            prefix=cfg.storage_prefix,
        )
    return LocalStorage(root=cfg.local_storage_root, prefix=cfg.storage_prefix)


# ---- 피처별 ports 빌더 (순수 함수, 테스트에서 직접 호출 가능) ----

def build_todo_generate_ports(cfg: AppConfig) -> GeneratePorts:
    # 단일 TODO 분해(splitter)는 planner LoRA(계획 확장 성향)가 아니라
    # base 모델을 써서 명시된 할 일만 그대로 추출한다. planner 는 /chat 전용.
    return GeneratePorts(llm=_build_todo_llm(cfg, adapter="base"))


def build_todo_planner_ports(cfg: AppConfig) -> PlannerPorts:
    return PlannerPorts(llm=_build_todo_llm(cfg, adapter="planner"))


def build_quest_ports(cfg: AppConfig) -> QuestPorts:
    if cfg.quest_llm_provider == "fake":
        return QuestPorts(llm=FakeQuestLLM())
    return QuestPorts(llm=_build_quest_llm(cfg))


def build_commit_ports(cfg: AppConfig, *, remaining_daily_quota: int) -> CommitPorts:
    return CommitPorts(
        repository=MemoryTodoRepository(),
        quest_counter=RequestQuestCounter(remaining=remaining_daily_quota),
        quest_dispatch=NoOpQuestDispatch(),
    )


def build_character_ports(
    request: Request, cfg: AppConfig, *, source_url: str
) -> CharacterPorts:
    inner_s3 = _build_storage(cfg)
    return CharacterPorts(
        llm=_build_character_llm(cfg),
        s3=PassthroughSourceS3(inner=inner_s3, source_url=source_url),
        image_generator=_get_image_generator(request),
        repository=InMemoryRepo(),
        translator=_build_translator(cfg),
    )


async def fetch_source_bytes(cfg: AppConfig, *, key: str, content_type: str) -> bytes:
    """S3(또는 로컬 스토리지)에서 소스 이미지 bytes 를 가져온다."""
    if cfg.storage_backend == "s3":
        client = _s3_client(cfg)
        obj = client.get_object(Bucket=cfg.aws_s3_bucket, Key=key)
        return obj["Body"].read()
    return (cfg.local_storage_root / key).read_bytes()


# ---- FastAPI 의존성 ----

def get_todo_generate_ports(cfg: AppConfig = Depends(get_config)) -> GeneratePorts:
    return build_todo_generate_ports(cfg)


def get_todo_planner_ports(cfg: AppConfig = Depends(get_config)) -> PlannerPorts:
    return build_todo_planner_ports(cfg)


def get_quest_ports(cfg: AppConfig = Depends(get_config)) -> QuestPorts:
    return build_quest_ports(cfg)


def build_feed_ports(request: Request, cfg: AppConfig) -> FeedPorts:
    return FeedPorts(
        llm=QwenFeedLLM(
            model=cfg.qwen_model or "",
            base_url=cfg.qwen_base_url or "",
            api_key=cfg.qwen_api_key,
        ),
        image_generator=_get_image_generator(request),
        s3=FeedS3Adapter(_build_storage(cfg)),
    )


def get_feed_ports(
    request: Request,
    cfg: AppConfig = Depends(get_config),
) -> FeedPorts:
    return build_feed_ports(request, cfg)
