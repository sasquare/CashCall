from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.constants import USER_ROLES


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Validated against USER_ROLES constant at application layer
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    # Required for originator and hod; validated against ALL_DEPARTMENTS
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Delegation: notifications go here when user is on leave
    alternate_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Hashed password — only used in dev bypass mode
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    submissions: Mapped[list["Submission"]] = relationship(  # noqa: F821
        "Submission", back_populates="creator", foreign_keys="Submission.created_by"
    )
    audit_entries: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        "AuditLog", back_populates="performer"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"
