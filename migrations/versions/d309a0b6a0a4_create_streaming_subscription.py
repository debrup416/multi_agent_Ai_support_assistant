"""create streaming_subscription

Revision ID: d309a0b6a0a4
Revises: 8aa820a28c1a
Create Date: 2026-06-13 14:20:39.020557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd309a0b6a0a4'
down_revision: Union[str, Sequence[str], None] = '8aa820a28c1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create streaming_subscription (FK -> customer) and seed customer 1."""
    op.create_table(
        "streaming_subscription",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customer.customer_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_name", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "auto_renew",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Customer-scoped tools filter on customer_id, so index it.
    op.create_index(
        "ix_streaming_subscription_customer_id",
        "streaming_subscription",
        ["customer_id"],
    )
    # Seed >=1 active subscription for customer 1 (MARY SMITH) for local testing/evals.
    op.execute(
        """
        INSERT INTO streaming_subscription
            (customer_id, plan_name, status, start_date, end_date, auto_renew)
        VALUES
            (1, 'Premium', 'active', DATE '2026-01-01', NULL, TRUE)
        """
    )


def downgrade() -> None:
    """Drop streaming_subscription (its index is dropped with the table)."""
    op.drop_table("streaming_subscription")
