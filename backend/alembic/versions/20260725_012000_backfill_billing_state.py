"""backfill billing state in resumable batches

Revision ID: 20260725_012000
Revises: 20260725_011000
"""

from alembic import op

revision = "20260725_012000"
down_revision = "20260725_011000"
branch_labels = None
depends_on = None


def _batched_update(table: str, predicate: str, assignments: str) -> None:
    op.execute(
        f"""DO $$
        DECLARE changed integer;
        DECLARE remaining boolean;
        DECLARE retries integer := 0;
        BEGIN
          LOOP
            WITH batch AS (
              SELECT ctid FROM {table} WHERE {predicate} LIMIT 1000 FOR UPDATE SKIP LOCKED
            )
            UPDATE {table} target SET {assignments}
            FROM batch WHERE target.ctid = batch.ctid;
            GET DIAGNOSTICS changed = ROW_COUNT;
            IF changed = 0 THEN
              SELECT EXISTS(SELECT 1 FROM {table} WHERE {predicate}) INTO remaining;
              EXIT WHEN NOT remaining;
              retries := retries + 1;
              IF retries > 20 THEN
                RAISE EXCEPTION 'billing backfill blocked by locked rows; retry migration';
              END IF;
              PERFORM pg_sleep(0.25);
            ELSE
              retries := 0;
            END IF;
            COMMIT;
            SET lock_timeout = '5s';
            SET statement_timeout = '5min';
          END LOOP;
        END $$;"""
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '5min'")
        try:
            _batched_update(
                "stripe_event_log",
                "processing_status = 'processing'",
                "processing_status = 'pending', claim_token = NULL, claimed_at = NULL",
            )
            _batched_update(
                "stripe_event_log",
                "processing_status = 'processed' AND processed_at IS NULL",
                "processed_at = event_created_at",
            )
            _batched_update(
                "stripe_event_log",
                "processing_status = 'failed' AND next_attempt_at IS NULL",
                "next_attempt_at = CURRENT_TIMESTAMP",
            )
            _batched_update("stripe_event_log", "attempt_count IS NULL", "attempt_count = 0")
            _batched_update(
                "plan_credit_grants",
                "entitlement_key IS NULL",
                "entitlement_key = 'legacy:' || stripe_invoice_id, stripe_mode = 'legacy', stripe_price_id = 'legacy', period_start = 0, period_end = 0",
            )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    raise RuntimeError("Irreversible migration: billing state backfill must be preserved.")
