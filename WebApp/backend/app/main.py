from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.crossings import router as crossings_router
from backend.app.api.health import router as health_router
from backend.app.api.predictions import router as predictions_router
from backend.app.api.system import router as system_router
from backend.app.config import get_settings
from backend.app.dependencies import get_station_graph_service


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    try:
        await get_station_graph_service().warm_runtime_caches()
    except Exception:
        pass
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=app_lifespan)
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
    app.include_router(system_router, prefix="/api")

    if settings.frontend_dir.exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")

    return app


app = create_app()

