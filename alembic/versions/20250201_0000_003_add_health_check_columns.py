"""Adiciona colunas de health check à tabela price_records.

Revision ID: 003
Revises: 002
Create Date: 2025-02-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "price_records",
        sa.Column("health_check_score", sa.String(20), nullable=True),
    )
    op.add_column(
        "price_records",
        sa.Column("health_check_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "price_records",
        sa.Column("diagnostic_s3_key", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_records", "diagnostic_s3_key")
    op.drop_column("price_records", "health_check_reason")
    op.drop_column("price_records", "health_check_score")
