from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class MissingEnvError(RuntimeError):
    pass


_VALID_QUEST_LLM_PROVIDERS = ("fake", "qwen")
_VALID_LLM_PROVIDERS = ("openai", "qwen")
_VALID_IMAGE_PROVIDERS = ("local", "runpod")


def _split_s3_uri(value: str) -> tuple[str, str]:
    if value.startswith("s3://"):
        value = value[len("s3://") :]
    bucket, _, prefix = value.partition("/")
    return bucket.strip("/"), prefix.strip("/")


def _default_local_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "local_storage"


@dataclass
class AppConfig:
    api_key: str
    openai_api_key: str
    storage_backend: str
    storage_prefix: str
    local_storage_root: Path
    aws_region: str | None
    aws_s3_bucket: str | None
    quest_llm_provider: str
    llm_provider: str
    qwen_base_url: str | None
    qwen_model: str | None
    qwen_persona_model: str | None
    qwen_api_key: str
    lora_dir: str
    image_provider: str = "local"
    runpod_image_endpoint_url: str | None = None
    runpod_api_key: str = "EMPTY"

    @classmethod
    def from_env(cls) -> "AppConfig":
        missing: list[str] = []

        def need(key: str) -> str:
            val = os.environ.get(key, "").strip()
            if not val:
                missing.append(key)
            return val

        backend = os.environ.get("STORAGE_BACKEND", "local").strip().lower() or "local"
        api_key = need("MONGLE_API_KEY")
        openai_api_key = need("OPENAI_API_KEY")

        quest_llm_provider = (
            os.environ.get("QUEST_LLM_PROVIDER", "fake").strip().lower() or "fake"
        )
        if quest_llm_provider not in _VALID_QUEST_LLM_PROVIDERS:
            raise MissingEnvError(
                f"QUEST_LLM_PROVIDER 는 {'|'.join(_VALID_QUEST_LLM_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {quest_llm_provider!r})"
            )
        llm_provider = (
            os.environ.get("LLM_PROVIDER", "openai").strip().lower() or "openai"
        )
        if llm_provider not in _VALID_LLM_PROVIDERS:
            raise MissingEnvError(
                f"LLM_PROVIDER 는 {'|'.join(_VALID_LLM_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {llm_provider!r})"
            )

        qwen_base_url: str | None = None
        qwen_model: str | None = None
        qwen_persona_model: str | None = None
        qwen_api_key = os.environ.get("QWEN_API_KEY", "").strip() or "EMPTY"
        if quest_llm_provider == "qwen" or llm_provider == "qwen":
            qwen_base_url = need("QWEN_BASE_URL")
            qwen_model = need("QWEN_MODEL")
            # persona 어댑터를 따로 지정하지 않으면 planning(기본) 모델로 폴백
            qwen_persona_model = (
                os.environ.get("QWEN_PERSONA_MODEL", "").strip() or qwen_model
            )

        image_provider = (
            os.environ.get("IMAGE_PROVIDER", "local").strip().lower() or "local"
        )
        if image_provider not in _VALID_IMAGE_PROVIDERS:
            raise MissingEnvError(
                f"IMAGE_PROVIDER 는 {'|'.join(_VALID_IMAGE_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {image_provider!r})"
            )

        runpod_image_endpoint_url: str | None = None
        runpod_api_key = "EMPTY"
        if image_provider == "runpod":
            runpod_image_endpoint_url = need("RUNPOD_IMAGE_ENDPOINT_URL")
            runpod_api_key = need("RUNPOD_API_KEY")

        lora_dir = os.environ.get("LORA_DIR", "").strip()
        if image_provider == "local" and not lora_dir:
            missing.append("LORA_DIR")

        common = dict(
            api_key=api_key,
            openai_api_key=openai_api_key,
            quest_llm_provider=quest_llm_provider,
            llm_provider=llm_provider,
            qwen_base_url=qwen_base_url,
            qwen_model=qwen_model,
            qwen_persona_model=qwen_persona_model,
            qwen_api_key=qwen_api_key,
            lora_dir=lora_dir,
            image_provider=image_provider,
            runpod_image_endpoint_url=runpod_image_endpoint_url,
            runpod_api_key=runpod_api_key,
        )

        if backend == "s3":
            raw_bucket = need("AWS_S3_BUCKET")
            bucket, embedded_prefix = _split_s3_uri(raw_bucket)
            env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
            prefix = env_prefix or embedded_prefix or "mongle-village"
            cfg = cls(
                storage_backend="s3",
                storage_prefix=prefix,
                local_storage_root=_default_local_root(),
                aws_region=need("AWS_REGION"),
                aws_s3_bucket=bucket,
                **common,
            )
        else:
            env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
            prefix = env_prefix or "mongle-village"
            root_str = os.environ.get("LOCAL_STORAGE_ROOT", "").strip()
            root = Path(root_str) if root_str else _default_local_root()
            cfg = cls(
                storage_backend="local",
                storage_prefix=prefix,
                local_storage_root=root,
                aws_region=None,
                aws_s3_bucket=None,
                **common,
            )

        if missing:
            raise MissingEnvError("다음 환경변수가 필요합니다: " + ", ".join(missing))
        return cfg
