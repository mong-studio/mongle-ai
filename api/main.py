from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import lifespan
from api.errors import install_error_handlers

_DEFAULT_CORS_ORIGINS = (
    "https://mongle-village.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _cors_origins() -> list[str]:
    raw = os.environ.get("MONGLE_CORS_ORIGINS", "").strip()
    if not raw:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    from agents._shared.observability import init_langsmith

    init_langsmith()
    app = FastAPI(title="Mongle AI Engine", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # 피처별 라우터 등록
    from api.todo_creation.router import router as todo_router
    app.include_router(todo_router)
    from api.quest_generation.router import router as quest_router
    app.include_router(quest_router)
    from api.character_creation.router import router as character_router
    app.include_router(character_router)
    from api.feed_generation.router import router as feed_router
    app.include_router(feed_router)
    from api.reply_generation.router import router as reply_router
    app.include_router(reply_router)
    return app


app = create_app()
