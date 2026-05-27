from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_openai import ChatOpenAI
from openai import OpenAI

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.midm_llm import MidmLLM as MidmCharacterLLM
from adapters.character_creation.openai_image import OpenAIImageGenerator
from adapters.character_creation.openai_llm import OpenAILLM as OpenAICharacterLLM
from adapters.character_creation.openai_vlm import OpenAIVLM
from adapters.quest_generation.fake_llm import FakeLLM as FakeQuestLLM
from adapters.quest_generation.memory_repo import (
    MemoryCharacterQueryRepo,
    MemoryQuestPersistenceRepo,
    MemoryTodoQueryRepo,
)
from adapters.quest_generation.midm_llm import MidmLLM as MidmQuestLLM
from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from adapters.todo_creation.midm_llm import MidmLLM as MidmTodoLLM
from adapters.todo_creation.openai_llm import OpenAILLM as OpenAITodoLLM
from adapters.todo_creation.quest_dispatch_adapter import QuestDispatchAdapter
from agents.character_creation.pipeline import Ports
from agents.character_creation.schemas import LLMPersonaResult, VLMResult
from agents.quest_generation.protocols import LLMPort as QuestLLMPort
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.single_turn.pipeline import GeneratePorts as TodoGeneratePorts

_VALID_QUEST_LLM_PROVIDERS = ("fake", "midm")
_VALID_LLM_PROVIDERS = ("openai", "midm")


class MissingEnvError(RuntimeError):
    pass


def _split_s3_uri(value: str) -> tuple[str, str]:
    """Accept either a bare bucket name or an ``s3://bucket/prefix/...`` URI.

    Returns ``(bucket, prefix)`` where ``prefix`` is "" if none was embedded.
    """
    if value.startswith("s3://"):
        value = value[len("s3://") :]
    bucket, _, prefix = value.partition("/")
    return bucket.strip("/"), prefix.strip("/")


def _default_local_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "local_storage"


@dataclass
class AppConfig:
    openai_api_key: str
    storage_backend: str          # "local" | "s3"
    storage_prefix: str           # 키 prefix (양쪽 백엔드 공통)
    local_storage_root: Path
    aws_region: str | None
    aws_s3_bucket: str | None
    # Quest LLM provider 토글. character_creation / commit pipeline 의
    # 일반 OpenAI 경로는 영향 없음.
    quest_llm_provider: str       # "fake" | "midm"
    llm_provider: str             # "openai" | "midm" — todo + character 공통
    midm_base_url: str | None     # llm_provider/quest_llm_provider == "midm" 일 때 필수
    midm_model: str | None        # 동일
    midm_api_key: str             # vLLM 등은 더미 키 허용 → 기본 "EMPTY"

    @classmethod
    def from_env(cls) -> AppConfig:
        missing: list[str] = []

        def need(key: str) -> str:
            val = os.environ.get(key, "").strip()
            if not val:
                missing.append(key)
            return val

        backend = (
            os.environ.get("STORAGE_BACKEND", "local").strip().lower() or "local"
        )
        openai_api_key = need("OPENAI_API_KEY")

        quest_llm_provider = (
            os.environ.get("QUEST_LLM_PROVIDER", "fake").strip().lower() or "fake"
        )
        if quest_llm_provider not in _VALID_QUEST_LLM_PROVIDERS:
            raise MissingEnvError(
                f"QUEST_LLM_PROVIDER 는 "
                f"{'|'.join(_VALID_QUEST_LLM_PROVIDERS)} 중 하나여야 합니다 "
                f"(현재: {quest_llm_provider!r})"
            )
        llm_provider = (
            os.environ.get("LLM_PROVIDER", "openai").strip().lower() or "openai"
        )
        if llm_provider not in _VALID_LLM_PROVIDERS:
            raise MissingEnvError(
                f"LLM_PROVIDER 는 "
                f"{'|'.join(_VALID_LLM_PROVIDERS)} 중 하나여야 합니다 "
                f"(현재: {llm_provider!r})"
            )
        midm_base_url: str | None = None
        midm_model: str | None = None
        midm_api_key = os.environ.get("MIDM_API_KEY", "").strip() or "EMPTY"
        if quest_llm_provider == "midm" or llm_provider == "midm":
            midm_base_url = need("MIDM_BASE_URL")
            midm_model = need("MIDM_MODEL")

        common_midm = dict(
            quest_llm_provider=quest_llm_provider,
            llm_provider=llm_provider,
            midm_base_url=midm_base_url,
            midm_model=midm_model,
            midm_api_key=midm_api_key,
        )

        if backend == "s3":
            raw_bucket = need("AWS_S3_BUCKET")
            bucket, embedded_prefix = _split_s3_uri(raw_bucket)
            env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
            prefix = env_prefix or embedded_prefix or "mongle-village"
            cfg = cls(
                openai_api_key=openai_api_key,
                storage_backend="s3",
                storage_prefix=prefix,
                local_storage_root=_default_local_root(),
                aws_region=need("AWS_REGION"),
                aws_s3_bucket=bucket,
                **common_midm,
            )
        else:
            env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
            prefix = env_prefix or "mongle-village"
            root_str = os.environ.get("LOCAL_STORAGE_ROOT", "").strip()
            root = Path(root_str) if root_str else _default_local_root()
            cfg = cls(
                openai_api_key=openai_api_key,
                storage_backend="local",
                storage_prefix=prefix,
                local_storage_root=root,
                aws_region=None,
                aws_s3_bucket=None,
                **common_midm,
            )

        if missing:
            raise MissingEnvError(
                "다음 환경변수가 필요합니다: " + ", ".join(missing)
            )
        return cfg


def _build_character_llm(cfg: AppConfig) -> OpenAICharacterLLM | MidmCharacterLLM:
    if cfg.llm_provider == "midm":
        assert cfg.midm_base_url and cfg.midm_model
        return MidmCharacterLLM(
            model=cfg.midm_model,
            base_url=cfg.midm_base_url,
            api_key=cfg.midm_api_key,
        )
    chat = ChatOpenAI(model="gpt-4o", api_key=cfg.openai_api_key)
    runnable = chat.with_structured_output(LLMPersonaResult, method="json_schema", strict=True)
    return OpenAICharacterLLM(runnable=runnable)


def build_todo_generate_ports(cfg: AppConfig) -> TodoGeneratePorts:
    if cfg.llm_provider == "midm":
        assert cfg.midm_base_url and cfg.midm_model
        llm = MidmTodoLLM(
            model=cfg.midm_model,
            base_url=cfg.midm_base_url,
            api_key=cfg.midm_api_key,
        )
    else:
        llm = OpenAITodoLLM()
    return TodoGeneratePorts(llm=llm)


def build_ports(repo: InMemoryRepo, cfg: AppConfig) -> Ports:
    openai_client = OpenAI(api_key=cfg.openai_api_key)

    chat = ChatOpenAI(model="gpt-4o", api_key=cfg.openai_api_key)
    vlm_runnable = chat.with_structured_output(
        VLMResult, method="json_schema", strict=True
    )

    if cfg.storage_backend == "s3":
        # boto3 import 비용을 local 모드에서 피하려고 지연 import.
        import boto3

        from adapters.character_creation.s3_storage import S3Storage

        s3_client = boto3.client("s3", region_name=cfg.aws_region)
        storage = S3Storage(
            client=s3_client,
            bucket=cfg.aws_s3_bucket or "",
            prefix=cfg.storage_prefix,
        )
    else:
        storage = LocalStorage(
            root=cfg.local_storage_root,
            prefix=cfg.storage_prefix,
        )

    return Ports(
        llm=_build_character_llm(cfg),
        vlm=OpenAIVLM(runnable=vlm_runnable),
        s3=storage,
        image_generator=OpenAIImageGenerator(
            client=openai_client, model="gpt-image-1", size="1024x1024"
        ),
        repository=repo,
    )


def _build_quest_llm(cfg: AppConfig | None) -> QuestLLMPort:
    """Pick the quest_generation LLMPort implementation based on config.

    - `cfg is None` → FakeQuestLLM (preserves the prior no-arg dev default).
    - `cfg.quest_llm_provider == "midm"` → MidmQuestLLM with vLLM-style endpoint.
    - otherwise → FakeQuestLLM.

    OpenAI quest LLM wiring is intentionally omitted from this PR; add it
    here later when an `OPENAI_QUEST_*` env scheme is defined.
    """
    if cfg is not None and cfg.quest_llm_provider == "midm":
        assert cfg.midm_base_url and cfg.midm_model, (
            "midm provider requires MIDM_BASE_URL and MIDM_MODEL"
        )
        return MidmQuestLLM(
            model=cfg.midm_model,
            base_url=cfg.midm_base_url,
            api_key=cfg.midm_api_key,
        )
    return FakeQuestLLM()


def build_commit_ports(cfg: AppConfig | None = None) -> CommitPorts:
    """Build commit pipeline ports (dev mode: in-memory repos + quest LLM).

    The `quest_dispatch` slot wires the real `QuestDispatchAdapter` so the
    commit pipeline's fire-and-forget dispatch flows through the
    quest_generation agent. In production, swap the four constructor args
    (todo_repo / character_repo / quest_repo / llm) for DB-backed repos +
    `OpenAILLM` built from `ChatOpenAI(...).with_structured_output(...)`.

    `cfg` is optional for backward compatibility with no-arg call sites.
    Pass an `AppConfig` to opt into the Mi:dm provider switch via
    `QUEST_LLM_PROVIDER=midm` + `MIDM_BASE_URL` + `MIDM_MODEL` env vars.
    """
    quest_dispatch = QuestDispatchAdapter(
        todo_repo=MemoryTodoQueryRepo(),
        character_repo=MemoryCharacterQueryRepo(),
        quest_repo=MemoryQuestPersistenceRepo(),
        llm=_build_quest_llm(cfg),
        today_fn=date.today,
    )
    return CommitPorts(
        repository=MemoryTodoRepository(),
        quest_counter=MemoryQuestCounter(),
        quest_dispatch=quest_dispatch,
    )
