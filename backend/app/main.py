from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.crossings import router as crossings_router
from backend.app.api.health import router as health_router
from backend.app.api.predictions import router as predictions_router
from backend.app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(crossings_router, prefix="/api")
    app.include_router(predictions_router, prefix="/api")

    if settings.frontend_dir.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app


app = create_app()

