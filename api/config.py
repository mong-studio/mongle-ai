from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class MissingEnvError(RuntimeError):
    pass


# 텍스트 LLM 은 qwen 단일 프로바이더(OpenAI 호환 chat completions 엔드포인트).
# 피처별로 다르게 파인튜닝한 LoRA 어댑터를 쓰므로 model 은 피처별로, base_url 은
# 공유(단일 vLLM + 멀티 LoRA)하되 필요한 피처만 따로 떼어낼 수 있게 override 를 둔다.
_DEFAULT_QWEN_BASE_URL = "http://localhost:8000/v1"
_DEFAULT_QWEN_MODEL = "Qwen/Qwen2.5-7B-Instruct"


@dataclass(frozen=True)
class QwenEndpoint:
    """피처 하나가 호출할 qwen 엔드포인트(어댑터 단위)."""

    base_url: str
    model: str
    api_key: str


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
    qwen_todo: QwenEndpoint
    qwen_character: QwenEndpoint
    qwen_quest: QwenEndpoint
    lora_dir: str

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

        qwen_base_url = (
            os.environ.get("QWEN_BASE_URL", "").strip() or _DEFAULT_QWEN_BASE_URL
        )
        qwen_model = os.environ.get("QWEN_MODEL", "").strip() or _DEFAULT_QWEN_MODEL
        qwen_api_key = os.environ.get("QWEN_API_KEY", "").strip() or "EMPTY"

        def _qwen_endpoint(feature: str) -> QwenEndpoint:
            """피처별 QWEN_<FEATURE>_* 가 있으면 그걸, 없으면 공유 기본값으로 폴백."""
            prefix = f"QWEN_{feature}_"
            return QwenEndpoint(
                base_url=os.environ.get(prefix + "BASE_URL", "").strip() or qwen_base_url,
                model=os.environ.get(prefix + "MODEL", "").strip() or qwen_model,
                api_key=qwen_api_key,
            )

        lora_dir = os.environ.get("LORA_DIR", "").strip()
        if not lora_dir:
            missing.append("LORA_DIR")

        common = dict(
            api_key=api_key,
            openai_api_key=openai_api_key,
            qwen_todo=_qwen_endpoint("TODO"),
            qwen_character=_qwen_endpoint("CHARACTER"),
            qwen_quest=_qwen_endpoint("QUEST"),
            lora_dir=lora_dir,
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
