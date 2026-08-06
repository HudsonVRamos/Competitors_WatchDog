"""Entidades SQLAlchemy para o Price Watchdog."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base declarativa para todos os modelos."""
    pass


class Competitor(Base):
    """Concorrente monitorado pelo sistema."""

    __tablename__ = "competitors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    base_url = Column(String(2048), nullable=False)
    is_active = Column(Boolean, default=True)
    intelligence_enabled = Column(Boolean, default=False)
    intelligence_home_url = Column(String(2048), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product_configs = relationship("ProductConfig", back_populates="competitor")


class ProductConfig(Base):
    """Configuração de um produto a ser monitorado em um concorrente."""

    __tablename__ = "product_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id = Column(UUID(as_uuid=True), ForeignKey("competitors.id"), nullable=False)
    product_name = Column(String(255), nullable=False)
    page_url = Column(String(2048), nullable=False)
    extraction_strategy = Column(String(50), nullable=False)
    selector_or_pattern = Column(Text, nullable=False)
    our_price = Column(Float, nullable=False)
    currency = Column(String(10), default="BRL")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    competitor = relationship("Competitor", back_populates="product_configs")
    price_records = relationship("PriceRecord", back_populates="product_config")


class PriceCycle(Base):
    """Ciclo de monitoramento de preços."""

    __tablename__ = "price_cycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")
    total_products = Column(Integer, default=0)
    products_succeeded = Column(Integer, default=0)
    products_failed = Column(Integer, default=0)
    alerts_triggered = Column(Integer, default=0)
    intelligence_attempted = Column(Integer, default=0)
    intelligence_succeeded = Column(Integer, default=0)
    intelligence_failed = Column(Integer, default=0)

    price_records = relationship("PriceRecord", back_populates="cycle")


class PriceRecord(Base):
    """Registro individual de preço extraído."""

    __tablename__ = "price_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_config_id = Column(UUID(as_uuid=True), ForeignKey("product_configs.id"), nullable=False)
    competitor_id = Column(UUID(as_uuid=True), ForeignKey("competitors.id"), nullable=False)
    cycle_id = Column(UUID(as_uuid=True), ForeignKey("price_cycles.id"), nullable=False)
    extracted_price = Column(Float, nullable=True)
    our_price = Column(Float, nullable=False)
    price_difference = Column(Float, nullable=True)
    price_difference_pct = Column(Float, nullable=True)
    extraction_status = Column(String(20), nullable=False)
    failure_reason = Column(Text, nullable=True)
    screenshot_s3_key = Column(String(512), nullable=True)
    extracted_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    product_config = relationship("ProductConfig", back_populates="price_records")
    cycle = relationship("PriceCycle", back_populates="price_records")
    alert = relationship("PriceAlert", back_populates="price_record", uselist=False)


class PriceAlert(Base):
    """Alerta gerado por variação significativa de preço."""

    __tablename__ = "price_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    price_record_id = Column(UUID(as_uuid=True), ForeignKey("price_records.id"), nullable=False)
    alert_type = Column(String(50), nullable=False)
    threshold_pct = Column(Float, nullable=False)
    actual_difference_pct = Column(Float, nullable=False)
    notified_at = Column(DateTime, nullable=True)
    recipients = Column(Text, nullable=False)

    price_record = relationship("PriceRecord", back_populates="alert")
