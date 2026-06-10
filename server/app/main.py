from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.routers import assets, auth, devices, search


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        # Swagger/OpenAPI docs are only exposed in development.
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url=None,
    )

    app.include_router(auth.router)
    app.include_router(devices.router)
    app.include_router(assets.router)
    app.include_router(search.router)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
        }

    return app


app = create_app()
