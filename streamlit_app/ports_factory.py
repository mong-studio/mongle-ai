from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.lora_image import LoRAImageGenerator
from adapters.character_creation.qwen_llm import QwenLLM as QwenCharacterLLM
from adapters.quest_generation.fake_llm import FakeLLM as FakeQuestLLM
from adapters.quest_generation.memory_repo import (
    MemoryCharacterQueryRepo,
    MemoryQuestPersistenceRepo,
    MemoryTodoQueryRepo,
)
from adapters.quest_generation.qwen_llm import QwenLLM as QwenQuestLLM
from adapters.todo_creation.memory_quest_counter import MemoryQuestCounter
from adapters.todo_creation.memory_repo import MemoryTodoRepository
from adapters.todo_creation.qwen_llm import (
    DEFAULT_QWEN_MODEL,
    QwenLLM as QwenTodoLLM,
)
from adapters.todo_creation.quest_dispatch_adapter import QuestDispatchAdapter
from agents.character_creation.pipeline import Ports
from agents.quest_generation.protocols import LLMPort as QuestLLMPort
from agents.todo_creation.commit.pipeline import CommitPorts
from agents.todo_creation.single_turn.pipeline import GeneratePorts as TodoGeneratePorts

_VALID_QUEST_LLM_PROVIDERS = ("fake", "qwen")


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
    quest_llm_provider: str       # "fake" | "qwen"
    qwen_base_url: str | None     # todo_creation Qwen endpoint
    qwen_model: str               # 기본 Qwen/Qwen2.5-7B-Instruct
    qwen_api_key: str             # vLLM 등은 더미 키 허용 → 기본 "EMPTY"
    qwen_temperature: float
    qwen_max_tokens: int
    lora_dir: str                 # LoRA 가중치 폴더 경로

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
        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()

        quest_llm_provider = (
            os.environ.get("QUEST_LLM_PROVIDER", "qwen").strip().lower() or "qwen"
        )
        if quest_llm_provider not in _VALID_QUEST_LLM_PROVIDERS:
            raise MissingEnvError(
                f"QUEST_LLM_PROVIDER 는 "
                f"{'|'.join(_VALID_QUEST_LLM_PROVIDERS)} 중 하나여야 합니다 "
                f"(현재: {quest_llm_provider!r})"
            )

        qwen_base_url = need("QWEN_BASE_URL")
        qwen_model = os.environ.get("QWEN_MODEL", "").strip() or DEFAULT_QWEN_MODEL
        qwen_api_key = os.environ.get("QWEN_API_KEY", "").strip() or "EMPTY"
        qwen_temperature = float(os.environ.get("QWEN_TEMPERATURE", "0.1"))
        qwen_max_tokens = int(os.environ.get("QWEN_MAX_TOKENS", "800"))

        lora_dir = os.environ.get("LORA_DIR", "").strip()
        if not lora_dir:
            missing.append("LORA_DIR")

        common_qwen = dict(
            quest_llm_provider=quest_llm_provider,
            qwen_base_url=qwen_base_url,
            qwen_model=qwen_model,
            qwen_api_key=qwen_api_key,
            qwen_temperature=qwen_temperature,
            qwen_max_tokens=qwen_max_tokens,
            lora_dir=lora_dir,
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
                **common_qwen,
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
                **common_qwen,
            )

        if missing:
            raise MissingEnvError(
                "다음 환경변수가 필요합니다: " + ", ".join(missing)
            )
        return cfg


def _build_character_llm(cfg: AppConfig) -> QwenCharacterLLM:
    assert cfg.qwen_base_url
    return QwenCharacterLLM(
        base_url=cfg.qwen_base_url,
        model=cfg.qwen_model,
        api_key=cfg.qwen_api_key,
        temperature=cfg.qwen_temperature,
        max_tokens=cfg.qwen_max_tokens,
    )


def build_todo_generate_ports(cfg: AppConfig) -> TodoGeneratePorts:
    assert cfg.qwen_base_url
    llm = QwenTodoLLM(
        base_url=cfg.qwen_base_url,
        model=cfg.qwen_model,
        api_key=cfg.qwen_api_key,
        temperature=cfg.qwen_temperature,
        max_tokens=cfg.qwen_max_tokens,
    )
    return TodoGeneratePorts(llm=llm)


@functools.lru_cache(maxsize=1)
def _get_lora_generator(lora_dir: str) -> LoRAImageGenerator:
    """앱 전체에서 LoRA 모델을 한 번만 로드."""
    return LoRAImageGenerator(lora_dir=lora_dir)


def build_ports(repo: InMemoryRepo, cfg: AppConfig) -> Ports:
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
        s3=storage,
        image_generator=_get_lora_generator(cfg.lora_dir),
        repository=repo,
    )


def _build_quest_llm(cfg: AppConfig | None) -> QuestLLMPort:
    """Pick the quest_generation LLMPort implementation based on config.

    - `cfg is None` → FakeQuestLLM (preserves the prior no-arg dev default).
    - `cfg.quest_llm_provider == "qwen"` → QwenQuestLLM with vLLM-style endpoint.
    - otherwise → FakeQuestLLM.
    """
    if cfg is not None and cfg.quest_llm_provider == "qwen":
        assert cfg.qwen_base_url
        return QwenQuestLLM(
            model=cfg.qwen_model,
            base_url=cfg.qwen_base_url,
            api_key=cfg.qwen_api_key,
            temperature=cfg.qwen_temperature,
            max_tokens=cfg.qwen_max_tokens,
        )
    return FakeQuestLLM()


def build_commit_ports(cfg: AppConfig | None = None) -> CommitPorts:
    """Build commit pipeline ports (dev mode: in-memory repos + quest LLM).

    The `quest_dispatch` slot wires the real `QuestDispatchAdapter` so the
    commit pipeline's fire-and-forget dispatch flows through the
    quest_generation agent. In production, swap the four constructor args
    (todo_repo / character_repo / quest_repo / llm) for DB-backed repos +
    `QwenLLM` configured through the backend environment.

    `cfg` is optional for backward compatibility with no-arg call sites.
    Pass an `AppConfig` to opt into Qwen quest generation via `QWEN_*` env vars.
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
