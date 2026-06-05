import pytest

from api.config import AppConfig, MissingEnvError, _split_s3_uri


def _base_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LORA_DIR", "/tmp/lora")
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "fake")
    monkeypatch.setenv("STORAGE_BACKEND", "local")


def test_from_env_local_backend(monkeypatch):
    _base_env(monkeypatch)
    cfg = AppConfig.from_env()
    assert cfg.storage_backend == "local"
    assert cfg.api_key == "secret-key"
    assert cfg.llm_provider == "openai"


def test_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LORA_DIR", raising=False)
    monkeypatch.setenv("MONGLE_API_KEY", "secret-key")
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


def test_missing_api_key_raises(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("MONGLE_API_KEY", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# S3 backend branch
# ---------------------------------------------------------------------------

def test_from_env_s3_backend(monkeypatch):
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
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(MissingEnvError, match="LLM_PROVIDER"):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# Invalid QUEST_LLM_PROVIDER branch
# ---------------------------------------------------------------------------

def test_invalid_quest_llm_provider_raises(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "notvalid")
    with pytest.raises(MissingEnvError, match="QUEST_LLM_PROVIDER"):
        AppConfig.from_env()


# ---------------------------------------------------------------------------
# midm provider branch
# ---------------------------------------------------------------------------

def test_llm_provider_midm_missing_vars_raises(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "midm")
    monkeypatch.delenv("MIDM_BASE_URL", raising=False)
    monkeypatch.delenv("MIDM_MODEL", raising=False)
    with pytest.raises(MissingEnvError):
        AppConfig.from_env()


def test_llm_provider_midm_with_vars_succeeds(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "midm")
    monkeypatch.setenv("MIDM_BASE_URL", "http://midm-host/v1")
    monkeypatch.setenv("MIDM_MODEL", "midm-bilingual-instruct")
    cfg = AppConfig.from_env()
    assert cfg.llm_provider == "midm"
    assert cfg.midm_base_url == "http://midm-host/v1"
    assert cfg.midm_model == "midm-bilingual-instruct"


def test_quest_llm_provider_midm_with_vars_succeeds(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("QUEST_LLM_PROVIDER", "midm")
    monkeypatch.setenv("MIDM_BASE_URL", "http://midm-host/v1")
    monkeypatch.setenv("MIDM_MODEL", "midm-bilingual-instruct")
    cfg = AppConfig.from_env()
    assert cfg.quest_llm_provider == "midm"
    assert cfg.midm_base_url == "http://midm-host/v1"


# ---------------------------------------------------------------------------
# _split_s3_uri pure function
# ---------------------------------------------------------------------------

def test_split_s3_uri_with_prefix():
    bucket, prefix = _split_s3_uri("s3://my-bucket/some/prefix")
    assert bucket == "my-bucket"
    assert prefix == "some/prefix"


def test_split_s3_uri_bare_bucket():
    bucket, prefix = _split_s3_uri("my-bucket")
    assert bucket == "my-bucket"
    assert prefix == ""


def test_split_s3_uri_no_scheme_with_prefix():
    bucket, prefix = _split_s3_uri("my-bucket/path/to/prefix")
    assert bucket == "my-bucket"
    assert prefix == "path/to/prefix"


def test_split_s3_uri_strips_slashes():
    bucket, prefix = _split_s3_uri("s3://my-bucket/")
    assert bucket == "my-bucket"
    assert prefix == ""
