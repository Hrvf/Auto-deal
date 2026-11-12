"""Modèle de données centralisé."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="membre")  # admin | membre
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Listing(Base):
    """Une annonce / un lot, normalisé quelle que soit la plateforme d'origine."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_platform_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(300), default="")

    make: Mapped[str | None] = mapped_column(String(60), index=True, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    engine: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fuel: Mapped[str | None] = mapped_column(String(30), index=True, nullable=True)
    gearbox: Mapped[str | None] = mapped_column(String(30), nullable=True)
    body: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str | None] = mapped_column(String(40), nullable=True)

    year: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    first_registration: Mapped[str | None] = mapped_column(String(10), nullable=True)  # AAAA-MM-JJ
    mileage_km: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    fiscal_hp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_hp: Mapped[int | None] = mapped_column(Integer, nullable=True)

    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(3), index=True, nullable=True)

    price: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    # prix_fixe | enchere_depart | enchere_actuelle | adjuge | estimation
    price_type: Mapped[str] = mapped_column(String(30), default="prix_fixe")
    price_includes_fees: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_recoverable: Mapped[bool] = mapped_column(Boolean, default=False)
    auction_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seller_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pro | particulier | enchere

    damages_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ct_status: Mapped[str] = mapped_column(String(20), default="inconnu")  # ok | a_refaire | contre_visite | inconnu
    is_running: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    maintenance_history: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    photos: Mapped[list] = mapped_column(JSON, default=list)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    market_price_manual: Mapped[int | None] = mapped_column(Integer, nullable=True)  # cote saisie
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="nouveau")  # nouveau | suivi | ecarte | achete
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    analysis: Mapped["Analysis | None"] = relationship(
        back_populates="listing", uselist=False, cascade="all, delete-orphan"
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), unique=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    score: Mapped[int] = mapped_column(Integer, index=True, default=0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)

    resale_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resale_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resale_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resale_confidence: Mapped[str] = mapped_column(String(20), default="aucune")
    resale_method: Mapped[str] = mapped_column(String(200), default="")
    comparables: Mapped[list] = mapped_column(JSON, default=list)

    purchase_fees: Mapped[int] = mapped_column(Integer, default=0)
    costs_breakdown: Mapped[list] = mapped_column(JSON, default=list)
    repairs_low: Mapped[int] = mapped_column(Integer, default=0)
    repairs_high: Mapped[int] = mapped_column(Integer, default=0)
    repairs_items: Mapped[list] = mapped_column(JSON, default=list)

    reliability_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    reliability_alerts: Mapped[list] = mapped_column(JSON, default=list)

    total_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    margin: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_bid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    listing: Mapped[Listing] = relationship(back_populates="analysis")


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))  # csv | json | html | flux | manuel
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | partiel | echec
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)


class ConnectorConfig(Base):
    """Paramètres d'un connecteur (flux autorisé, activation, dernière synchro)."""

    __tablename__ = "connector_configs"

    platform: Mapped[str] = mapped_column(String(40), primary_key=True)
    feed_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    feed_format: Mapped[str] = mapped_column(String(10), default="csv")  # csv | json
    auth_header_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    auth_header_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authorization_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feed_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiToken(Base):
    """Jeton personnel pour l'extension de capture (seul son empreinte SHA-256 est stockée)."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Extension")
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
