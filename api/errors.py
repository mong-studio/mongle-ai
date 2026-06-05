from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agents.character_creation.exceptions import (
    ImageGenerationFailedError,
)
from agents.character_creation.exceptions import LLMFailedError as CharLLMFailedError
from agents.character_creation.exceptions import (
    S3UploadFailedError as CharS3UploadFailedError,
)
from agents.quest_generation.exceptions import LLMFailedError as QuestLLMFailedError
from agents.todo_creation.exceptions import LLMFailedError as TodoLLMFailedError
from agents.todo_creation.exceptions import SaveFailedError

from api.envelope import Envelope, ErrorBody

# (예외 타입, HTTP status, envelope code)
_MAPPING: list[tuple[type[Exception], int, str]] = [
    (CharLLMFailedError, 502, "llm_failed"),
    (TodoLLMFailedError, 502, "llm_failed"),
    (QuestLLMFailedError, 502, "llm_failed"),
    (CharS3UploadFailedError, 502, "storage_failed"),
    (SaveFailedError, 502, "storage_failed"),
    (ImageGenerationFailedError, 502, "image_generation_failed"),
]


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    env = Envelope(status="error", error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=env.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    """도메인 예외 → HTTP 매핑 핸들러를 앱에 등록한다."""

    def _make_handler(status_code: int, code: str):
        async def handler(_request: Request, exc: Exception) -> JSONResponse:
            return _error_response(status_code, code, str(exc))

        return handler

    for exc_type, status_code, code in _MAPPING:
        app.add_exception_handler(exc_type, _make_handler(status_code, code))

    async def _validation_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "validation_error", "요청 본문이 유효하지 않습니다")

    app.add_exception_handler(RequestValidationError, _validation_handler)

    async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "unauthorized" if exc.status_code == 401 else "http_error"
        return _error_response(exc.status_code, code, str(exc.detail))

    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)

    async def _fallback(_request: Request, _exc: Exception) -> JSONResponse:
        # 민감 정보 노출 방지: 내부 메시지를 응답에 싣지 않는다.
        return _error_response(500, "internal_error", "내부 서버 오류")

    app.add_exception_handler(Exception, _fallback)
