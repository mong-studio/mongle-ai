from __future__ import annotations

import pytest

from agents.character_creation.exceptions import (
    CharacterCreationError,
    ExternalServiceError,
    ImageGenerationFailedError,
    LLMFailedError,
    S3UploadFailedError,
    ValidationFailedError,
)


def test_validation_error_is_subclass_of_creation_error() -> None:
    err = ValidationFailedError(code="C1", message="보유 캐릭터 ≥ 10")
    assert isinstance(err, CharacterCreationError)
    assert err.code == "C1"
    assert "C1" in str(err)


@pytest.mark.parametrize(
    "exc_cls",
    [LLMFailedError, S3UploadFailedError, ImageGenerationFailedError],
)
def test_external_errors_subclass_external_service_error(exc_cls: type) -> None:
    err = exc_cls("upstream timeout")
    assert isinstance(err, ExternalServiceError)
    assert isinstance(err, CharacterCreationError)
