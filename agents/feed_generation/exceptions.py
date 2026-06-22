from __future__ import annotations


class FeedGenerationError(Exception):
    pass


class InputValidationError(FeedGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImageGenerationError(FeedGenerationError):
    pass


class S3UploadError(FeedGenerationError):
    pass


class CaptionGenerationError(FeedGenerationError):
    pass


class CaptionValidationError(FeedGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PromptGenerationError(FeedGenerationError):
    """피드 프롬프트(action/scene) 생성 실패."""
