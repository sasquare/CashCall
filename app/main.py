import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
import app.models  # noqa: F401 — registers all ORM models

from app.routers import auth as auth_router
from app.routers import submissions as submissions_router
from app.routers import hod as hod_router
from app.routers import finance_qc as finance_qc_router
from app.routers import cfo as cfo_router
from app.routers import ceo as ceo_router
from app.routers import treasury as treasury_router
from app.routers import admin as admin_router

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


# ---------------------------------------------------------------------------
# Simple in-process rate limiter (per IP, per minute)
# ---------------------------------------------------------------------------

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 120       # requests per window
_RATE_WINDOW = 60.0     # seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - _RATE_WINDOW

        hits = _rate_limit_store[ip]
        # Purge old entries
        hits[:] = [t for t in hits if t > window_start]

        if len(hits) >= _RATE_LIMIT:
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        hits.append(now)
        return await call_next(request)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_TITLE,
    docs_url="/docs" if settings.is_development else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.is_development else None,
)

# Middleware — outermost first
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
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
app.include_router(hod_router.router)
app.include_router(finance_qc_router.router)
app.include_router(cfo_router.router)
app.include_router(ceo_router.router)
app.include_router(treasury_router.router)
app.include_router(admin_router.router)


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
