from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StudentProfile(Base, TimestampMixin):
    __tablename__ = "student_profiles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prn: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(24), nullable=True)
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    skills: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_links: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    onboarding_step: Mapped[int] = mapped_column(default=1)
    readiness: Mapped[int] = mapped_column(default=0)
    is_complete: Mapped[bool] = mapped_column(default=False)
