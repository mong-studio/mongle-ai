from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.openai_llm import OpenAILLM as OpenAICharacterLLM
from adapters.character_creation.passthrough_s3 import PassthroughSourceS3
from adapters.character_creation.qwen_llm import QwenLLM as QwenCharacterLLM
from adapters.quest_generation.fake_llm import FakeLLM as FakeQuestLLM
from adapters.quest_generation.qwen_llm import QwenLLM as QwenQuestLLM
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from adapters.todo_creation.noop_quest_dispatch import NoOpQuestDispatch
from adapters.todo_creation.openai_llm import OpenAILLM as OpenAITodoLLM
from adapters.todo_creation.qwen_llm import QwenLLM as QwenTodoLLM
from adapters.todo_creation.request_quest_counter import RequestQuestCounter
from agents.character_creation.pipeline import Ports as CharacterPorts
from agents.character_creation.schemas import LLMPersonaResult
from agents.quest_generation.pipeline import Ports as QuestPorts
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.multi_turn.pipeline import MultiTurnPorts
from agents.todo_creation.single_turn.pipeline import GeneratePorts

from api.config import AppConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 설정 1회 로드. LoRA 는 첫 character 요청에서 지연 로드."""
    app.state.config = AppConfig.from_env()
    app.state.lora_generator = None
    yield


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def _build_character_llm(cfg: AppConfig):
    if cfg.llm_provider == "qwen":
        assert cfg.qwen_base_url and cfg.qwen_model
        return QwenCharacterLLM(
            model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
        )
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(model="gpt-4o", api_key=cfg.openai_api_key)
    runnable = chat.with_structured_output(
        LLMPersonaResult, method="json_schema", strict=True
    )
    return OpenAICharacterLLM(runnable=runnable)


def _build_todo_llm(cfg: AppConfig):
    if cfg.llm_provider == "qwen":
        assert cfg.qwen_base_url and cfg.qwen_model
        return QwenTodoLLM(
            model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
        )
    return OpenAITodoLLM(api_key=cfg.openai_api_key)


def _build_quest_llm(cfg: AppConfig):
    if cfg.quest_llm_provider == "qwen":
        assert cfg.qwen_base_url and cfg.qwen_model
        return QwenQuestLLM(
            model=cfg.qwen_model, base_url=cfg.qwen_base_url, api_key=cfg.qwen_api_key
        )
    return FakeQuestLLM()


def _get_lora_generator(request: Request):
    """LoRA 모델을 앱 전체에서 한 번만 로드(지연)."""
    if request.app.state.lora_generator is None:
        from adapters.character_creation.lora_image import LoRAImageGenerator

        cfg: AppConfig = request.app.state.config
        request.app.state.lora_generator = LoRAImageGenerator(lora_dir=cfg.lora_dir)
    return request.app.state.lora_generator


def _build_storage(cfg: AppConfig):
    if cfg.storage_backend == "s3":
        import boto3

        from adapters.character_creation.s3_storage import S3Storage

        client = boto3.client("s3", region_name=cfg.aws_region)
        return S3Storage(
            client=client, bucket=cfg.aws_s3_bucket or "", prefix=cfg.storage_prefix
        )
    return LocalStorage(root=cfg.local_storage_root, prefix=cfg.storage_prefix)


# ---- 피처별 ports 빌더 (순수 함수, 테스트에서 직접 호출 가능) ----

def build_todo_generate_ports(cfg: AppConfig) -> GeneratePorts:
    return GeneratePorts(llm=_build_todo_llm(cfg))


def build_todo_multiturn_ports(cfg: AppConfig) -> MultiTurnPorts:
    return MultiTurnPorts(llm=_build_todo_llm(cfg))


def build_quest_ports(cfg: AppConfig) -> QuestPorts:
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
        image_generator=_get_lora_generator(request),
        repository=InMemoryRepo(),
    )


async def fetch_source_bytes(cfg: AppConfig, *, key: str, content_type: str) -> bytes:
    """S3(또는 로컬 스토리지)에서 소스 이미지 bytes 를 가져온다."""
    if cfg.storage_backend == "s3":
        import boto3

        client = boto3.client("s3", region_name=cfg.aws_region)
        obj = client.get_object(Bucket=cfg.aws_s3_bucket, Key=key)
        return obj["Body"].read()
    return (cfg.local_storage_root / key).read_bytes()


# ---- FastAPI 의존성 ----

def get_todo_generate_ports(cfg: AppConfig = Depends(get_config)) -> GeneratePorts:
    return build_todo_generate_ports(cfg)


def get_todo_multiturn_ports(cfg: AppConfig = Depends(get_config)) -> MultiTurnPorts:
    return build_todo_multiturn_ports(cfg)


def get_quest_ports(cfg: AppConfig = Depends(get_config)) -> QuestPorts:
    return build_quest_ports(cfg)
