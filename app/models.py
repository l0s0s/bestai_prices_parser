from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    website_url: Mapped[str] = mapped_column(String(1024))
    pricing_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    docs_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    site_alive: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    https_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    domain_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    domain_age_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trust_status: Mapped[str] = mapped_column(String(16), default="yellow")  # green | yellow | red
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    sources: Mapped[List["ProviderSource"]] = relationship(back_populates="provider", cascade="all, delete-orphan")
    prices: Mapped[List["ProviderPrice"]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class ProviderSource(Base):
    __tablename__ = "provider_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    catalog_source: Mapped[str] = mapped_column(String(64))  # apirank | aiapipk | veridrop | ...
    catalog_page_url: Mapped[str] = mapped_column(String(1024))
    catalog_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    catalog_reviews_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    provider: Mapped["Provider"] = relationship(back_populates="sources")


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    source_url: Mapped[str] = mapped_column(String(1024))
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256 hex
    snapshot_path: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProviderPrice(Base):
    __tablename__ = "provider_prices"
    __table_args__ = (
        UniqueConstraint("provider_id", "canonical_model_id", "source_url", name="uq_price_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    canonical_model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_model_name: Mapped[str] = mapped_column(String(255))
    raw_price_text: Mapped[str] = mapped_column(Text)
    raw_currency: Mapped[str] = mapped_column(String(8))
    raw_unit: Mapped[str] = mapped_column(String(32))
    input_price_usd_per_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output_price_usd_per_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    provider: Mapped["Provider"] = relationship(back_populates="prices")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_price_id: Mapped[int] = mapped_column(ForeignKey("provider_prices.id"))
    old_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    new_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
