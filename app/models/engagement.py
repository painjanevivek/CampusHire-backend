from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RoadmapTemplate(Base, TimestampMixin):
    __tablename__ = "roadmap_templates"
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_roadmap_template_slug_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(500))
    nodes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="approved", index=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudentRoadmap(Base, TimestampMixin):
    __tablename__ = "student_roadmaps"
    __table_args__ = (UniqueConstraint("student_user_id", name="uq_student_active_roadmap"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("roadmap_templates.id", ondelete="RESTRICT"), index=True
    )


class RoadmapProgress(Base, TimestampMixin):
    __tablename__ = "roadmap_progress"
    __table_args__ = (
        UniqueConstraint("student_roadmap_id", "node_key", name="uq_roadmap_progress_node"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    student_roadmap_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_roadmaps.id", ondelete="CASCADE"), index=True
    )
    node_key: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24), default="in_progress", index=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint("recipient_user_id", "event_key", name="uq_notification_recipient_event"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(180))
    title: Mapped[str] = mapped_column(String(180))
    body: Mapped[str] = mapped_column(Text)
    deep_link: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(24), default="updates")
    related_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("correction_requests.id", ondelete="SET NULL"), nullable=True
    )
    related_application_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
