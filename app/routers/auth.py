from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.auth_service import (
    authenticate_dev,
    clear_session,
    get_auth_url,
    handle_auth_callback,
    set_session_user,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Already logged in → dashboard
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    azure_configured = bool(settings.AZURE_CLIENT_ID)
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "dev_mode": settings.is_development and settings.DEV_BYPASS_ENABLED,
            "show_password_form": not azure_configured or (settings.is_development and settings.DEV_BYPASS_ENABLED),
            "azure_configured": azure_configured,
            "error": request.query_params.get("error"),
        },
    )


# ---------------------------------------------------------------------------
# Dev bypass login (POST)
# ---------------------------------------------------------------------------

@router.post("/login/dev", response_class=HTMLResponse)
async def login_dev(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    azure_configured = bool(settings.AZURE_CLIENT_ID)
    # Allow password login whenever Azure SSO is not configured, or in dev mode
    if azure_configured and not (settings.is_development and settings.DEV_BYPASS_ENABLED):
        return RedirectResponse("/login?error=dev_disabled", status_code=status.HTTP_302_FOUND)

    user = authenticate_dev(email, password, db)
    if not user:
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "dev_mode": settings.is_development and settings.DEV_BYPASS_ENABLED,
                "show_password_form": not azure_configured or (settings.is_development and settings.DEV_BYPASS_ENABLED),
                "azure_configured": azure_configured,
                "error": "Invalid email or password.",
                "prefill_email": email,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    set_session_user(request, user)
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Azure AD — redirect to Microsoft
# ---------------------------------------------------------------------------

@router.get("/login/microsoft")
async def login_microsoft(request: Request):
    if not settings.AZURE_CLIENT_ID:
        return RedirectResponse(
            "/login?error=azure_not_configured",
            status_code=status.HTTP_302_FOUND,
        )
    auth_url = get_auth_url(request)
    return RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Azure AD — callback
# ---------------------------------------------------------------------------

@router.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    user = handle_auth_callback(request, db)
    if not user:
        return RedirectResponse(
            "/login?error=auth_failed",
            status_code=status.HTTP_302_FOUND,
        )
    set_session_user(request, user)
    return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.get("/logout")
async def logout(request: Request):
    clear_session(request)
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile", response_class=HTMLResponse)
async def profile(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "auth/profile.html",
        {"request": request, "user": current_user},
    )


# ---------------------------------------------------------------------------
# Root → redirect
# ---------------------------------------------------------------------------

@router.get("/")
async def root(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse("/login", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Dashboard placeholder (will be replaced in Phase 3+)
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "dashboard/home.html",
        {"request": request, "user": current_user},
    )
