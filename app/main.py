from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine

# Import all models so SQLAlchemy registers them before create_all
import app.models  # noqa: F401

app = FastAPI(
    title=settings.APP_TITLE,
    docs_url="/docs" if settings.is_development else None,
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    https_only=settings.is_production,
    same_site="lax",
)


@app.on_event("startup")
async def _create_tables() -> None:
    # In production use Alembic migrations instead of create_all.
    # create_all is kept here for development convenience only.
    if settings.is_development:
        Base.metadata.create_all(bind=engine)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.APP_ENV}
