from __future__ import annotations

import json

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, now_iso, uid


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    name: Mapped[str]
    contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class BrandKit(Base):
    __tablename__ = "brand_kits"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str]
    palette_json: Mapped[str] = mapped_column(Text, default="[]")
    font_name: Mapped[str] = mapped_column(Text, default="Arial")
    logo_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    intro_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    outro_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)

    @property
    def palette(self) -> list:
        return json.loads(self.palette_json or "[]")

    @palette.setter
    def palette(self, value: list) -> None:
        self.palette_json = json.dumps(value)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    client_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str]
    objective: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class DeliverableReview(Base):
    __tablename__ = "deliverable_reviews"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    deliverable_id: Mapped[str] = mapped_column(Text, index=True)
    reviewer: Mapped[str]
    action: Mapped[str]
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class ScriptRevision(Base):
    __tablename__ = "script_revisions"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(Text, index=True)
    version: Mapped[int] = mapped_column(default=1)
    sections_json: Mapped[str] = mapped_column(Text, default="{}")
    full_text: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[str]
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class NotificationRecord(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(Text, index=True)
    user_email: Mapped[str] = mapped_column(Text, index=True)
    type: Mapped[str]
    title: Mapped[str]
    body: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
