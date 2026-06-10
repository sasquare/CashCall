from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
import app.models  # noqa: F401 — registers all ORM models

from app.routers import auth as auth_router
from app.routers import submissions as submissions_router

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

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(auth_router.router)
app.include_router(submissions_router.router)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    session_user = request.session.get("user")
    return templates.TemplateResponse(
        "errors/403.html",
        {"request": request, "user": session_user},
        status_code=403,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    session_user = request.session.get("user")
    return templates.TemplateResponse(
        "errors/404.html",
        {"request": request, "user": session_user},
        status_code=404,
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _create_tables() -> None:
    if settings.is_development:
        Base.metadata.create_all(bind=engine)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.APP_ENV}
