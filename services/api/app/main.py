from fastapi import FastAPI

from app.api.activities import router as activities_router
from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.core.config import settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title=settings.app_name)

register_exception_handlers(app)

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(activities_router)


@app.on_event("shutdown")
async def _dispose_engine() -> None:
    await engine.dispose()
