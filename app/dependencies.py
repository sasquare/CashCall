"""
Shared FastAPI dependencies.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_session_user


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------

class NotAuthenticatedError(Exception):
    pass


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Reads the logged-in user from the session.
    Raises HTTPException(401) if not authenticated.
    Use require_role() for role-gated routes.
    """
    session_data = get_session_user(request)
    if not session_data:
        # For HTMX requests return 401; for normal requests redirect to login.
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )

    user = db.query(User).filter(
        User.id == session_data["user_id"],
        User.is_active == True,  # noqa: E712
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


# ---------------------------------------------------------------------------
# Role-gating dependency factory
# ---------------------------------------------------------------------------

def require_role(*roles: str) -> Callable:
    """
    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("it_admin"))])

    Or as a dependency that also returns the user:
        async def my_route(user: User = Depends(require_role("cfo", "ceo"))): ...
    """
    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> User:
        user = get_current_user(request, db)
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {', '.join(roles)}.",
            )
        return user
    return dependency
