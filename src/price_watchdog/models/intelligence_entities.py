"""Entidades SQLAlchemy para inteligência competitiva."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from price_watchdog.models.entities import Base


class CompetitorIntelligenceRecord(Base):
    """Registro de inteligência competitiva por ciclo/concorrente."""

    __tablename__ = "competitor_intelligence_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("price_cycles.id"), nullable=False)
    competitor_id = Column(UUID(as_uuid=True), ForeignKey("competitors.id"), nullable=False)
    extraction_status = Column(String(30), nullable=False)  # success | failed | no_packages_found
    failure_reason = Column(String(500), nullable=True)

    # Comunicação comercial
    commercial_keywords = Column(ARRAY(String(50)), nullable=True)  # até 15 elementos
    home_banner_description = Column(String(500), nullable=True)
    commercial_positioning_summary = Column(String(1000), nullable=True)

    # Métricas
    extraction_latency_ms = Column(Float, nullable=True)
    retry_count = Column(Integer, default=0)

    # Timestamps
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Constraint: 1 registro por (cycle_id, competitor_id)
    __table_args__ = (
        UniqueConstraint("cycle_id", "competitor_id", name="uq_intelligence_cycle_competitor"),
    )

    # Relationships
    packages = relationship(
        "PackageComposition",
        back_populates="intelligence_record",
        cascade="all, delete-orphan",
    )
    competitor = relationship("Competitor")
    cycle = relationship("PriceCycle")


class PackageComposition(Base):
    """Composição de um pacote individual dentro de um registro de inteligência."""

    __tablename__ = "package_compositions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intelligence_record_id = Column(
        UUID(as_uuid=True),
        ForeignKey("competitor_intelligence_records.id"),
        nullable=False,
    )
    plan_name = Column(String(255), nullable=False)
    default_price = Column(Float, nullable=True)
    promotional_price = Column(Float, nullable=True)
    promotional_period_months = Column(Integer, nullable=True)
    linear_channels = Column(Integer, nullable=True)
    simultaneous_screens = Column(Integer, nullable=True)
    has_fiber = Column(Boolean, nullable=True)
    fiber_speed_mbps = Column(Integer, nullable=True)
    has_mobile_internet = Column(Boolean, nullable=True)
    mobile_speed_mbps = Column(Integer, nullable=True)
    bundled_streaming_1 = Column(String(100), nullable=True)
    bundled_streaming_2 = Column(String(100), nullable=True)
    bundled_streaming_3 = Column(String(100), nullable=True)
    bundled_streaming_4 = Column(String(100), nullable=True)
    bundled_streaming_5 = Column(String(100), nullable=True)
    bundled_streaming_6 = Column(String(100), nullable=True)
    bundled_streaming_7 = Column(String(100), nullable=True)

    # Relationship
    intelligence_record = relationship(
        "CompetitorIntelligenceRecord", back_populates="packages"
    )
