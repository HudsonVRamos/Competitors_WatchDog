"""Criação do schema inicial do Price Watchdog.

Revision ID: 001
Revises: None
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tabela competitors
    op.create_table(
        "competitors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Tabela product_configs
    op.create_table(
        "product_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("competitors.id"),
            nullable=False,
        ),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("page_url", sa.String(2048), nullable=False),
        sa.Column("extraction_strategy", sa.String(50), nullable=False),
        sa.Column("selector_or_pattern", sa.Text(), nullable=False),
        sa.Column("our_price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(10), default="BRL"),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Tabela price_cycles
    op.create_table(
        "price_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("total_products", sa.Integer(), default=0),
        sa.Column("products_succeeded", sa.Integer(), default=0),
        sa.Column("products_failed", sa.Integer(), default=0),
        sa.Column("alerts_triggered", sa.Integer(), default=0),
    )

    # Tabela price_records
    op.create_table(
        "price_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_configs.id"),
            nullable=False,
        ),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("competitors.id"),
            nullable=False,
        ),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_cycles.id"),
            nullable=False,
        ),
        sa.Column("extracted_price", sa.Float(), nullable=True),
        sa.Column("our_price", sa.Float(), nullable=False),
        sa.Column("price_difference", sa.Float(), nullable=True),
        sa.Column("price_difference_pct", sa.Float(), nullable=True),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("screenshot_s3_key", sa.String(512), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
    )

    # Tabela price_alerts
    op.create_table(
        "price_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "price_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_records.id"),
            nullable=False,
        ),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column("actual_difference_pct", sa.Float(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("recipients", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("price_alerts")
    op.drop_table("price_records")
    op.drop_table("price_cycles")
    op.drop_table("product_configs")
    op.drop_table("competitors")
