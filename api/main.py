from __future__ import annotations

from fastapi import FastAPI

from api.deps import lifespan
from api.errors import install_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="Mongle AI Engine", lifespan=lifespan)
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
    return app


app = create_app()
