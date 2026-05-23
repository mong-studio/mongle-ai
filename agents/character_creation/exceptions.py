from __future__ import annotations


class CharacterCreationError(Exception):
    pass


class ValidationFailedError(CharacterCreationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ExternalServiceError(CharacterCreationError):
    pass


class LLMFailedError(ExternalServiceError):
    pass


class VLMFailedError(ExternalServiceError):
    pass


class S3UploadFailedError(ExternalServiceError):
    pass


class ImageGenerationFailedError(ExternalServiceError):
    pass
