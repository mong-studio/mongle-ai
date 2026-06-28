import pytest

from api.config import AppConfig, MissingEnvError, _split_s3_uri


def _base_env(monkeypatch):
    monkeypatch.setenv("LORA_DIR", "/tmp/lora")
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "qwen")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host/v1")
    monkeypatch.setenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    monkeypatch.delenv("AWS_S3_PREFIX", raising=False)


def test_from_env_local_backend(monkeypatch):
    """local 백엔드 환경에서 핵심 설정값이 올바로 로드된다."""
    _base_env(monkeypatch)
    cfg = AppConfig.from_env()
    assert cfg.storage_backend == "local"
    assert cfg.api_key == "secret-key"
    assert cfg.llm_provider == "qwen"


def test_missing_required_env_raises(monkeypatch):
    """필수 환경변수가 빠지면 MissingEnvError를 던진다."""
    # config.py 가 import 시 .env 를 load_dotenv 하므로, 개발용 .env 오염에
    # 흔들리지 않게 provider 들을 명시 고정한 뒤 필수값 하나를 비운다.
    _base_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "local")
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


def test_missing_api_key_raises(monkeypatch):
    """MONGLE_API_KEY가 없으면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.delenv("MONGLE_API_KEY", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# S3 backend branch
# ---------------------------------------------------------------------------

def test_from_env_s3_backend(monkeypatch):
    """s3 백엔드에서 버킷·리전이 로드되고 프리픽스는 기본값을 쓴다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_S3_BUCKET", "my-bucket")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    cfg = AppConfig.from_env()
    assert cfg.storage_backend == "s3"
    assert cfg.aws_s3_bucket == "my-bucket"
    assert cfg.aws_region == "ap-northeast-2"
    assert cfg.storage_prefix == "mongle-village"  # default prefix


def test_from_env_s3_backend_with_prefix_in_bucket(monkeypatch):
    """버킷 값에 s3:// URI로 프리픽스가 박혀 있으면 분리해서 읽는다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_S3_BUCKET", "s3://my-bucket/custom-prefix")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    cfg = AppConfig.from_env()
    assert cfg.aws_s3_bucket == "my-bucket"
    assert cfg.storage_prefix == "custom-prefix"


def test_from_env_s3_backend_env_prefix_overrides(monkeypatch):
    """AWS_S3_PREFIX env var takes precedence over prefix embedded in bucket."""
    _base_env(monkeypatch)
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_S3_BUCKET", "s3://my-bucket/embedded-prefix")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_S3_PREFIX", "explicit-prefix")
    cfg = AppConfig.from_env()
    assert cfg.storage_prefix == "explicit-prefix"


# ---------------------------------------------------------------------------
# Invalid LLM_PROVIDER branch
# ---------------------------------------------------------------------------

def test_invalid_llm_provider_raises(monkeypatch):
    """알 수 없는 LLM_PROVIDER 값이면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(MissingEnvError, match="LLM_PROVIDER"):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# Invalid QUEST_LLM_PROVIDER branch
# ---------------------------------------------------------------------------

def test_invalid_quest_llm_provider_raises(monkeypatch):
    """알 수 없는 QUEST_LLM_PROVIDER 값이면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "notvalid")
    with pytest.raises(MissingEnvError, match="QUEST_LLM_PROVIDER"):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# qwen provider branch
# ---------------------------------------------------------------------------

def test_llm_provider_qwen_missing_vars_raises(monkeypatch):
    """qwen 프로바이더인데 QWEN_* 변수가 없으면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_MODEL", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


def test_llm_provider_qwen_with_vars_succeeds(monkeypatch):
    """qwen 프로바이더에 QWEN_* 변수가 갖춰지면 설정이 로드된다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host/v1")
    monkeypatch.setenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    cfg = AppConfig.from_env()
    assert cfg.llm_provider == "qwen"
    assert cfg.qwen_base_url == "http://qwen-host/v1"
    assert cfg.qwen_model == "Qwen/Qwen2.5-7B-Instruct"


def test_qwen_base_url_must_not_point_to_fastapi(monkeypatch):
    """QWEN_BASE_URL 이 FastAPI 앱을 가리키면 /chat/completions 404 를 만들므로 차단한다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QWEN_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    with pytest.raises(MissingEnvError, match="QWEN_BASE_URL"):
        AppConfig.from_env()


def test_qwen_persona_model_defaults_to_qwen_model(monkeypatch):
    """QWEN_PERSONA_MODEL 미설정이면 persona 모델은 QWEN_MODEL 로 폴백한다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host/v1")
    monkeypatch.setenv("QWEN_MODEL", "planning-adapter")
    monkeypatch.delenv("QWEN_PERSONA_MODEL", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.qwen_persona_model == "planning-adapter"


def test_qwen_persona_model_override(monkeypatch):
    """QWEN_PERSONA_MODEL 이 있으면 persona 어댑터명을 별도로 읽는다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host/v1")
    monkeypatch.setenv("QWEN_MODEL", "planning-adapter")
    monkeypatch.setenv("QWEN_PERSONA_MODEL", "persona-adapter")
    cfg = AppConfig.from_env()
    assert cfg.qwen_model == "planning-adapter"
    assert cfg.qwen_persona_model == "persona-adapter"


def test_quest_llm_provider_qwen_with_vars_succeeds(monkeypatch):
    """quest용 qwen 프로바이더에 QWEN_* 변수가 갖춰지면 설정이 로드된다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host/v1")
    monkeypatch.setenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    cfg = AppConfig.from_env()
    assert cfg.quest_llm_provider == "qwen"
    assert cfg.qwen_base_url == "http://qwen-host/v1"


# ---------------------------------------------------------------------------
# IMAGE_PROVIDER branch
# ---------------------------------------------------------------------------

def test_image_provider_defaults_to_local(monkeypatch):
    """IMAGE_PROVIDER 미설정이면 local 이고 LORA_DIR 이 필수다."""
    _base_env(monkeypatch)
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.image_provider == "local"
    assert cfg.lora_dir == "/tmp/lora"


def test_image_provider_local_missing_lora_dir_raises(monkeypatch):
    """local 프로바이더인데 LORA_DIR 이 없으면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "local")  # .env(load_dotenv)의 runpod 누수 차단
    monkeypatch.delenv("LORA_DIR", raising=False)
    with pytest.raises(MissingEnvError, match="LORA_DIR"):
        AppConfig.from_env()


def test_image_provider_runpod_loads_endpoint(monkeypatch):
    """runpod 프로바이더면 엔드포인트·API 키가 로드되고 LORA_DIR 은 불필요하다."""
    _base_env(monkeypatch)
    monkeypatch.delenv("LORA_DIR", raising=False)
    monkeypatch.setenv("IMAGE_PROVIDER", "runpod")
    monkeypatch.setenv("RUNPOD_IMAGE_ENDPOINT_URL", "https://api.runpod.ai/v2/ep-1")
    monkeypatch.setenv("RUNPOD_API_KEY", "rp-key")
    cfg = AppConfig.from_env()
    assert cfg.image_provider == "runpod"
    assert cfg.runpod_image_endpoint_url == "https://api.runpod.ai/v2/ep-1"
    assert cfg.runpod_api_key == "rp-key"
    assert cfg.lora_dir == ""


def test_image_provider_runpod_builds_url_from_endpoint_id(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "runpod")
    monkeypatch.delenv("RUNPOD_IMAGE_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("RUNPOD_IMAGE_ENDPOINT_ID", "ep-from-id")
    monkeypatch.setenv("RUNPOD_API_KEY", "rp-key")

    cfg = AppConfig.from_env()

    assert cfg.runpod_image_endpoint_url == "https://api.runpod.ai/v2/ep-from-id"


def test_image_provider_runpod_missing_vars_raises(monkeypatch):
    """runpod 프로바이더인데 RUNPOD_* 변수가 없으면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "runpod")
    monkeypatch.delenv("RUNPOD_IMAGE_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("RUNPOD_IMAGE_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_IMAGE_GEN_V2_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


def test_invalid_image_provider_raises(monkeypatch):
    """알 수 없는 IMAGE_PROVIDER 값이면 MissingEnvError를 던진다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "bogus")
    with pytest.raises(MissingEnvError, match="IMAGE_PROVIDER"):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# _split_s3_uri pure function
# ---------------------------------------------------------------------------

def test_split_s3_uri_with_prefix():
    """s3:// URI에서 버킷과 프리픽스를 분리한다."""
    bucket, prefix = _split_s3_uri("s3://my-bucket/some/prefix")
    assert bucket == "my-bucket"
    assert prefix == "some/prefix"


def test_split_s3_uri_bare_bucket():
    """프리픽스 없는 버킷명만 주면 프리픽스는 빈 문자열이다."""
    bucket, prefix = _split_s3_uri("my-bucket")
    assert bucket == "my-bucket"
    assert prefix == ""


def test_split_s3_uri_no_scheme_with_prefix():
    """s3:// 스킴 없이 버킷/프리픽스 형태도 분리한다."""
    bucket, prefix = _split_s3_uri("my-bucket/path/to/prefix")
    assert bucket == "my-bucket"
    assert prefix == "path/to/prefix"


def test_split_s3_uri_strips_slashes():
    """뒤따르는 슬래시는 제거되어 프리픽스가 빈 문자열이 된다."""
    bucket, prefix = _split_s3_uri("s3://my-bucket/")
    assert bucket == "my-bucket"
    assert prefix == ""
