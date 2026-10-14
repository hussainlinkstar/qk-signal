"""Add billing payments table.

Revision ID: 20241105_120000
Revises: 20241015_120000
Create Date: 2024-11-05 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20241105_120000"
down_revision = "20241015_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS billing_payments (
                id SERIAL NOT NULL,
                user_id INTEGER NOT NULL,
                stripe_invoice_id VARCHAR NOT NULL,
                stripe_customer_id VARCHAR NOT NULL,
                stripe_subscription_id VARCHAR,
                amount_paid INTEGER,
                amount_due INTEGER,
                currency VARCHAR,
                status VARCHAR,
                hosted_invoice_url VARCHAR,
                invoice_pdf VARCHAR,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT fk_billing_payments_user_id
                    FOREIGN KEY(user_id) REFERENCES users (id),
                CONSTRAINT uq_billing_payments_stripe_invoice_id
                    UNIQUE (stripe_invoice_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_billing_payments_user_id
            ON billing_payments (user_id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_billing_payments_stripe_invoice_id
            ON billing_payments (stripe_invoice_id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_billing_payments_stripe_customer_id
            ON billing_payments (stripe_customer_id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_billing_payments_stripe_subscription_id
            ON billing_payments (stripe_subscription_id)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_billing_payments_stripe_subscription_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_billing_payments_stripe_customer_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_billing_payments_stripe_invoice_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_billing_payments_user_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS billing_payments"))
