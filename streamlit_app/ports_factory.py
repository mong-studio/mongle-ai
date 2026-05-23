from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from langchain_openai import ChatOpenAI
from openai import OpenAI

from adapters.character_creation.local_storage import LocalStorage
from adapters.character_creation.memory_repo import InMemoryRepo
from adapters.character_creation.openai_image import OpenAIImageGenerator
from adapters.character_creation.openai_llm import OpenAILLM
from adapters.character_creation.openai_vlm import OpenAIVLM
from agents.character_creation.pipeline import Ports
from agents.character_creation.schemas import LLMPersonaResult, VLMResult


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
            )

        if missing:
            raise MissingEnvError(
                "다음 환경변수가 필요합니다: " + ", ".join(missing)
            )
        return cfg


def build_ports(repo: InMemoryRepo, cfg: AppConfig) -> Ports:
    openai_client = OpenAI(api_key=cfg.openai_api_key)

    chat = ChatOpenAI(model="gpt-4o", api_key=cfg.openai_api_key)
    llm_runnable = chat.with_structured_output(
        LLMPersonaResult, method="json_schema", strict=True
    )
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
        llm=OpenAILLM(runnable=llm_runnable),
        vlm=OpenAIVLM(runnable=vlm_runnable),
        s3=storage,
        image_generator=OpenAIImageGenerator(
            client=openai_client, model="gpt-image-1", size="1024x1024"
        ),
        repository=repo,
    )
