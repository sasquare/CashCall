"""
Authentication helpers: password verification, session read/write,
Azure AD MSAL flow helpers.
"""

from __future__ import annotations

import bcrypt
import msal
from fastapi import Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User


# ---------------------------------------------------------------------------
# Password (dev bypass only)
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

SESSION_KEY = "user"


def set_session_user(request: Request, user: User) -> None:
    request.session[SESSION_KEY] = {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "department": user.department,
    }


def get_session_user(request: Request) -> dict | None:
    return request.session.get(SESSION_KEY)


def clear_session(request: Request) -> None:
    request.session.clear()


# ---------------------------------------------------------------------------
# Dev bypass login
# ---------------------------------------------------------------------------

def authenticate_dev(email: str, password: str, db: Session) -> User | None:
    """Return the User if credentials are valid, else None."""
    if not settings.DEV_BYPASS_ENABLED or not settings.is_development:
        return None
    user = db.query(User).filter(
        User.email == email.lower().strip(),
        User.is_active == True,  # noqa: E712
    ).first()
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ---------------------------------------------------------------------------
# Azure AD / MSAL helpers
# ---------------------------------------------------------------------------

_AUTHORITY = "https://login.microsoftonline.com/{tenant}"
_SCOPES = ["User.Read"]


def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.AZURE_CLIENT_ID,
        client_credential=settings.AZURE_CLIENT_SECRET,
        authority=_AUTHORITY.format(tenant=settings.AZURE_TENANT_ID),
    )


def get_auth_url(request: Request) -> str:
    """Generate the Azure AD authorisation URL and store state in session."""
    flow = _msal_app().initiate_auth_code_flow(
        scopes=_SCOPES,
        redirect_uri=settings.AZURE_REDIRECT_URI,
    )
    request.session["auth_flow"] = flow
    return flow["auth_uri"]


def handle_auth_callback(request: Request, db: Session) -> User | None:
    """
    Exchange the callback code for a token, look up (or create) the user.
    Returns None if the flow is invalid or the user is inactive.
    """
    flow = request.session.pop("auth_flow", None)
    if not flow:
        return None

    try:
        result = _msal_app().acquire_token_by_auth_code_flow(
            flow, dict(request.query_params)
        )
    except Exception:
        return None

    if "error" in result:
        return None

    claims = result.get("id_token_claims", {})
    email = (claims.get("preferred_username") or claims.get("email") or "").lower()
    display_name = claims.get("name") or email

    if not email:
        return None

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        return None

    return user
