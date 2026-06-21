from __future__ import annotations


class ReplyGenerationError(Exception):
    pass


class InputValidationError(ReplyGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReplyLLMError(ReplyGenerationError):
    pass


class ReplyValidationError(ReplyGenerationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
