"""Adiciona tabelas e campos para inteligência competitiva.

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Alterações na tabela competitors ---
    op.add_column(
        "competitors",
        sa.Column("intelligence_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "competitors",
        sa.Column("intelligence_home_url", sa.String(2048), nullable=True),
    )

    # --- Alterações na tabela price_cycles ---
    op.add_column(
        "price_cycles",
        sa.Column("intelligence_attempted", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "price_cycles",
        sa.Column("intelligence_succeeded", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "price_cycles",
        sa.Column("intelligence_failed", sa.Integer(), server_default="0", nullable=False),
    )

    # --- Nova tabela competitor_intelligence_records ---
    op.create_table(
        "competitor_intelligence_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "competitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("competitors.id"),
            nullable=False,
        ),
        sa.Column("extraction_status", sa.String(30), nullable=False),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("commercial_keywords", postgresql.ARRAY(sa.String(50)), nullable=True),
        sa.Column("home_banner_description", sa.String(500), nullable=True),
        sa.Column("commercial_positioning_summary", sa.String(1000), nullable=True),
        sa.Column("extraction_latency_ms", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cycle_id", "competitor_id", name="uq_intelligence_cycle_competitor"),
    )

    # --- Nova tabela package_compositions ---
    op.create_table(
        "package_compositions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "intelligence_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("competitor_intelligence_records.id"),
            nullable=False,
        ),
        sa.Column("plan_name", sa.String(255), nullable=False),
        sa.Column("default_price", sa.Float(), nullable=True),
        sa.Column("promotional_price", sa.Float(), nullable=True),
        sa.Column("promotional_period_months", sa.Integer(), nullable=True),
        sa.Column("linear_channels", sa.Integer(), nullable=True),
        sa.Column("simultaneous_screens", sa.Integer(), nullable=True),
        sa.Column("has_fiber", sa.Boolean(), nullable=True),
        sa.Column("fiber_speed_mbps", sa.Integer(), nullable=True),
        sa.Column("has_mobile_internet", sa.Boolean(), nullable=True),
        sa.Column("mobile_speed_mbps", sa.Integer(), nullable=True),
        sa.Column("bundled_streaming_1", sa.String(100), nullable=True),
        sa.Column("bundled_streaming_2", sa.String(100), nullable=True),
        sa.Column("bundled_streaming_3", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("package_compositions")
    op.drop_table("competitor_intelligence_records")
    op.drop_column("price_cycles", "intelligence_failed")
    op.drop_column("price_cycles", "intelligence_succeeded")
    op.drop_column("price_cycles", "intelligence_attempted")
    op.drop_column("competitors", "intelligence_home_url")
    op.drop_column("competitors", "intelligence_enabled")
