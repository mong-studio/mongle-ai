import pytest

from api.config import AppConfig, MissingEnvError, _split_s3_uri


# AppConfig.from_env() 가 읽는 선택 변수들. ambient env(셸 export·sft_pipeline 의
# .env 로드 등)가 새어들어 테스트를 오염시키지 않도록 기준선에서 전부 비운다.
_OPTIONAL_ENV = (
    "QWEN_BASE_URL",
    "QWEN_MODEL",
    "QWEN_API_KEY",
    "QWEN_TODO_BASE_URL",
    "QWEN_TODO_MODEL",
    "QWEN_CHARACTER_BASE_URL",
    "QWEN_CHARACTER_MODEL",
    "QWEN_QUEST_BASE_URL",
    "QWEN_QUEST_MODEL",
    "AWS_S3_BUCKET",
    "AWS_S3_PREFIX",
    "AWS_REGION",
    "LOCAL_STORAGE_ROOT",
)


def _base_env(monkeypatch):
    for var in _OPTIONAL_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LORA_DIR", "/tmp/lora")
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    monkeypatch.setenv("STORAGE_BACKEND", "local")


def test_from_env_local_backend(monkeypatch):
    """local 백엔드 환경에서 핵심 설정값이 올바로 로드된다."""
    _base_env(monkeypatch)
    cfg = AppConfig.from_env()
    assert cfg.storage_backend == "local"
    assert cfg.api_key == "secret-key"


def test_qwen_defaults_when_env_unset(monkeypatch):
    """피처별 QWEN_* 가 없으면 모든 피처가 공유 기본값으로 폴백한다."""
    _base_env(monkeypatch)
    for var in ("QWEN_BASE_URL", "QWEN_MODEL", "QWEN_TODO_MODEL", "QWEN_CHARACTER_MODEL"):
        monkeypatch.delenv(var, raising=False)
    cfg = AppConfig.from_env()
    for ep in (cfg.qwen_todo, cfg.qwen_character, cfg.qwen_quest):
        assert ep.base_url == "http://localhost:8000/v1"
        assert ep.model == "Qwen/Qwen2.5-7B-Instruct"
        assert ep.api_key == "EMPTY"


def test_qwen_shared_env_applies_to_all_features(monkeypatch):
    """공유 QWEN_BASE_URL/MODEL/API_KEY 는 모든 피처에 반영된다."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QWEN_BASE_URL", "http://qwen-host:8000/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("QWEN_API_KEY", "tok")
    cfg = AppConfig.from_env()
    for ep in (cfg.qwen_todo, cfg.qwen_character, cfg.qwen_quest):
        assert ep.base_url == "http://qwen-host:8000/v1"
        assert ep.model == "qwen2.5:7b"
        assert ep.api_key == "tok"


def test_qwen_per_feature_model_overrides_shared(monkeypatch):
    """피처별 QWEN_<FEATURE>_MODEL 은 공유 base_url 위에서 model 만 따로 쓴다(멀티 LoRA)."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QWEN_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("QWEN_TODO_MODEL", "todo-planner-lora")
    monkeypatch.setenv("QWEN_CHARACTER_MODEL", "persona-lora")
    cfg = AppConfig.from_env()
    assert cfg.qwen_todo.base_url == "http://vllm:8000/v1"
    assert cfg.qwen_todo.model == "todo-planner-lora"
    assert cfg.qwen_character.model == "persona-lora"
    # quest 는 피처별 설정이 없으니 공유 기본 model 로 폴백
    assert cfg.qwen_quest.model == "Qwen/Qwen2.5-7B-Instruct"


def test_qwen_per_feature_base_url_override(monkeypatch):
    """특정 피처만 독립 엔드포인트로 떼어낼 수 있다(QWEN_<FEATURE>_BASE_URL)."""
    _base_env(monkeypatch)
    monkeypatch.setenv("QWEN_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("QWEN_CHARACTER_BASE_URL", "http://persona-host:8001/v1")
    cfg = AppConfig.from_env()
    assert cfg.qwen_character.base_url == "http://persona-host:8001/v1"
    assert cfg.qwen_todo.base_url == "http://vllm:8000/v1"


def test_missing_required_env_raises(monkeypatch):
    """필수 환경변수가 빠지면 MissingEnvError를 던진다."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LORA_DIR", raising=False)
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
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
