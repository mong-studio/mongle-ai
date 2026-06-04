from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str


class Envelope(BaseModel, Generic[T]):
    status: Literal["done", "pending", "error"] = "done"
    result: T | None = None
    error: ErrorBody | None = None


def done(result: T) -> Envelope[T]:
    """결과를 status=done envelope로 감싼다."""
    return Envelope(status="done", result=result)
