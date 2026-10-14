import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import queue_worker


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.query_called = False

    def query(self, *_args, **_kwargs):
        self.query_called = True
        raise AssertionError("scheduled audit query should be skipped when the table is missing")

    def close(self) -> None:
        self.closed = True


def test_select_due_scheduled_audits_skips_missing_table(monkeypatch):
    fake_session = _FakeSession()
    warnings: list[str] = []

    monkeypatch.setattr(queue_worker, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(queue_worker, "_scheduled_audits_table_exists", lambda _db: False)
    monkeypatch.setattr(
        queue_worker.logger,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )

    previous_availability = queue_worker.scheduled_audits_table_available
    queue_worker.scheduled_audits_table_available = None
    try:
        due_ids = queue_worker._select_due_scheduled_audit_ids()
    finally:
        queue_worker.scheduled_audits_table_available = previous_availability

    assert due_ids == []
    assert fake_session.closed is True
    assert fake_session.query_called is False
    assert warnings == [
        "Skipping scheduled audit sweep because scheduled_audits is unavailable; pending migrations may still be running."
    ]
