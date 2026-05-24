from __future__ import annotations


class TodoCreationError(Exception):
    pass


class ValidationError(TodoCreationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class AuthorizationError(TodoCreationError):
    pass


class LLMFailedError(TodoCreationError):
    pass


class LLMOutputError(TodoCreationError):
    pass


class SaveFailedError(TodoCreationError):
    pass


class SessionStoreError(TodoCreationError):
    pass


class EditAgentError(TodoCreationError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
