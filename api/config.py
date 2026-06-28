from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class MissingEnvError(RuntimeError):
    pass


_VALID_QUEST_LLM_PROVIDERS = ("qwen", "runpod", "fake")
_VALID_FEED_LLM_PROVIDERS = ("qwen", "runpod", "fake")
_VALID_LLM_PROVIDERS = ("qwen", "runpod", "fake")
_VALID_STRUCTURED_MODES = ("vllm", "openai")
_VALID_IMAGE_PROVIDERS = ("local", "runpod")
_LOCAL_FASTAPI_QWEN_BASE_URLS = (
    "http://localhost:8000/v1",
    "http://127.0.0.1:8000/v1",
)


def _split_s3_uri(value: str) -> tuple[str, str]:
    if value.startswith("s3://"):
        value = value[len("s3://") :]
    bucket, _, prefix = value.partition("/")
    return bucket.strip("/"), prefix.strip("/")


def _default_local_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "local_storage"


def _default_lora_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "lora"


@dataclass
class AppConfig:
    api_key: str
    storage_backend: str
    storage_prefix: str
    local_storage_root: Path
    aws_region: str | None
    aws_s3_bucket: str | None
    quest_llm_provider: str
    feed_llm_provider: str
    llm_provider: str
    qwen_base_url: str | None = None
    qwen_model: str | None = None
    qwen_persona_model: str | None = None
    qwen_api_key: str = "EMPTY"
    qwen_structured_mode: str = "vllm"
    # planner(계획확장)만 OpenAI 로 분리할 때 쓰는 오버라이드. 비어 있으면 qwen 설정 사용.
    planner_openai_base_url: str | None = None
    planner_openai_model: str | None = None
    planner_openai_api_key: str = "EMPTY"
    lora_dir: str = ""
    image_provider: str = "local"
    runpod_image_endpoint_url: str | None = None
    runpod_api_key: str = "EMPTY"
    runpod_planner_endpoint_url: str | None = None
    runpod_character_endpoint_url: str | None = None

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
        quest_llm_provider = (
            os.environ.get("QUEST_LLM_PROVIDER", "qwen").strip().lower() or "qwen"
        )
        if quest_llm_provider not in _VALID_QUEST_LLM_PROVIDERS:
            raise MissingEnvError(
                f"QUEST_LLM_PROVIDER 는 {'|'.join(_VALID_QUEST_LLM_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {quest_llm_provider!r})"
            )
        feed_llm_provider = (
            os.environ.get("FEED_LLM_PROVIDER", "qwen").strip().lower() or "qwen"
        )
        if feed_llm_provider not in _VALID_FEED_LLM_PROVIDERS:
            raise MissingEnvError(
                f"FEED_LLM_PROVIDER 는 {'|'.join(_VALID_FEED_LLM_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {feed_llm_provider!r})"
            )
        llm_provider = (
            os.environ.get("LLM_PROVIDER", "qwen").strip().lower() or "qwen"
        )
        if llm_provider not in _VALID_LLM_PROVIDERS:
            raise MissingEnvError(
                f"LLM_PROVIDER 는 {'|'.join(_VALID_LLM_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {llm_provider!r})"
            )

        # TODO 생성은 항상 Qwen 전용이므로 qwen 설정은 게이트와 무관하게 항상 읽는다.
        # provider=qwen(또는 quest=qwen)일 때만 부재 시 기동을 실패시킨다.
        qwen_base_url = os.environ.get("QWEN_BASE_URL", "").strip() or None
        qwen_model = os.environ.get("QWEN_MODEL", "").strip() or None
        qwen_api_key = os.environ.get("QWEN_API_KEY", "").strip() or "EMPTY"
        if qwen_base_url and qwen_base_url.rstrip("/") in _LOCAL_FASTAPI_QWEN_BASE_URLS:
            raise MissingEnvError(
                "QWEN_BASE_URL 이 FastAPI 서버(http://localhost:8000/v1)를 가리키고 "
                "있습니다. Qwen/OpenAI 호환 LLM 서버 주소를 사용하세요 "
                "(예: Ollama http://localhost:11434/v1)."
            )
        if (
            quest_llm_provider == "qwen"
            or feed_llm_provider == "qwen"
            or llm_provider == "qwen"
        ):
            if not qwen_base_url:
                missing.append("QWEN_BASE_URL")
            if not qwen_model:
                missing.append("QWEN_MODEL")
        # persona 어댑터를 따로 지정하지 않으면 planning(기본) 모델로 폴백
        qwen_persona_model = (
            os.environ.get("QWEN_PERSONA_MODEL", "").strip() or qwen_model
        )
        # 구조화 출력 방식: vllm(guided_json) | openai(response_format json_schema)
        qwen_structured_mode = (
            os.environ.get("QWEN_STRUCTURED_MODE", "vllm").strip().lower() or "vllm"
        )
        if qwen_structured_mode not in _VALID_STRUCTURED_MODES:
            raise MissingEnvError(
                f"QWEN_STRUCTURED_MODE 는 {'|'.join(_VALID_STRUCTURED_MODES)} 중 "
                f"하나여야 합니다 (현재: {qwen_structured_mode!r})"
            )
        # planner 전용 OpenAI 오버라이드(선택). base/model 둘 다 있어야 활성화.
        planner_openai_base_url = (
            os.environ.get("PLANNER_OPENAI_BASE_URL", "").strip() or None
        )
        planner_openai_model = (
            os.environ.get("PLANNER_OPENAI_MODEL", "").strip() or None
        )
        planner_openai_api_key = (
            os.environ.get("PLANNER_OPENAI_API_KEY", "").strip() or "EMPTY"
        )

        image_provider = (
            os.environ.get("IMAGE_PROVIDER", "local").strip().lower() or "local"
        )
        if image_provider not in _VALID_IMAGE_PROVIDERS:
            raise MissingEnvError(
                f"IMAGE_PROVIDER 는 {'|'.join(_VALID_IMAGE_PROVIDERS)} 중 "
                f"하나여야 합니다 (현재: {image_provider!r})"
            )

        runpod_api_key = os.environ.get("RUNPOD_API_KEY", "").strip() or "EMPTY"

        runpod_image_endpoint_url: str | None = None
        if image_provider == "runpod":
            runpod_image_endpoint_url = (
                os.environ.get("RUNPOD_IMAGE_ENDPOINT_URL", "").strip() or None
            )
            runpod_image_gen_v2_endpoint_id = (
                os.environ.get("RUNPOD_IMAGE_GEN_V2_ENDPOINT_ID", "").strip() or None
            )
            if not runpod_image_endpoint_url and runpod_image_gen_v2_endpoint_id:
                runpod_image_endpoint_url = (
                    f"https://api.runpod.ai/v2/{runpod_image_gen_v2_endpoint_id}"
                )
            if not runpod_image_endpoint_url:
                missing.append("RUNPOD_IMAGE_ENDPOINT_URL or RUNPOD_IMAGE_GEN_V2_ENDPOINT_ID")
            if runpod_api_key == "EMPTY":
                missing.append("RUNPOD_API_KEY")

        runpod_planner_endpoint_url: str | None = None
        runpod_character_endpoint_url: str | None = None
        if llm_provider == "runpod":
            runpod_planner_endpoint_url = need("RUNPOD_PLANNER_ENDPOINT_URL")
        # character(페르소나) 엔드포인트는 캐릭터 생성(llm_provider)·퀘스트(quest_llm_provider)·
        # 피드(feed_llm_provider)가 공유한다.
        if (
            llm_provider == "runpod"
            or quest_llm_provider == "runpod"
            or feed_llm_provider == "runpod"
        ):
            runpod_character_endpoint_url = need("RUNPOD_CHARACTER_ENDPOINT_URL")
            if runpod_api_key == "EMPTY":
                missing.append("RUNPOD_API_KEY")

        lora_dir = os.environ.get("LORA_DIR", "").strip()
        if image_provider == "local" and not lora_dir:
            missing.append("LORA_DIR")

        common = dict(
            api_key=api_key,
            quest_llm_provider=quest_llm_provider,
            feed_llm_provider=feed_llm_provider,
            llm_provider=llm_provider,
            qwen_base_url=qwen_base_url,
            qwen_model=qwen_model,
            qwen_persona_model=qwen_persona_model,
            qwen_api_key=qwen_api_key,
            qwen_structured_mode=qwen_structured_mode,
            planner_openai_base_url=planner_openai_base_url,
            planner_openai_model=planner_openai_model,
            planner_openai_api_key=planner_openai_api_key,
            lora_dir=lora_dir,
            image_provider=image_provider,
            runpod_image_endpoint_url=runpod_image_endpoint_url,
            runpod_api_key=runpod_api_key,
            runpod_planner_endpoint_url=runpod_planner_endpoint_url,
            runpod_character_endpoint_url=runpod_character_endpoint_url,
        )

        if backend == "s3":
            raw_bucket = need("AWS_S3_BUCKET")
            bucket, embedded_prefix = _split_s3_uri(raw_bucket)
            env_prefix = os.environ.get("AWS_S3_PREFIX", "").strip().strip("/")
            prefix = (
                env_prefix
                if env_prefix and (env_prefix != "mongle-village" or not embedded_prefix)
                else embedded_prefix or env_prefix or "mongle-village"
            )
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
