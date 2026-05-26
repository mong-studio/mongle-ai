from __future__ import annotations

from agents.todo_creation.exceptions import (
    AuthorizationError,
    LLMFailedError,
    LLMOutputError,
    SaveFailedError,
    ThreadNotFoundError,
    TodoCreationError,
    ValidationError,
)


def test_validation_error_has_code_and_message() -> None:
    e = ValidationError(code="A1", message="prompt too long")
    assert e.code == "A1"
    assert e.message == "prompt too long"
    assert "A1" in str(e)
    assert isinstance(e, TodoCreationError)


def test_authorization_error_subclass() -> None:
    assert issubclass(AuthorizationError, TodoCreationError)


def test_llm_errors_subclass() -> None:
    assert issubclass(LLMFailedError, TodoCreationError)
    assert issubclass(LLMOutputError, TodoCreationError)


def test_save_failed_error_subclass() -> None:
    assert issubclass(SaveFailedError, TodoCreationError)


def test_thread_not_found_subclass() -> None:
    assert issubclass(ThreadNotFoundError, TodoCreationError)
    e = ThreadNotFoundError("thread t1 not found")
    assert "t1" in str(e)
