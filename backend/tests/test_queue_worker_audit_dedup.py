"""Idempotency: a retried job must not create a duplicate audit row.

Covers _find_existing_audit_for_request, the guard queue_worker uses before
inserting a new audit.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import queue_worker


class _FakeQuery:
    def __init__(self, result):
        self._result = result
        self.filter_args = None

    def filter(self, *args):
        self.filter_args = args
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, result):
        self._result = result
        self.query_calls = 0

    def query(self, model):
        self.query_calls += 1
        self.queried_model = model
        return _FakeQuery(self._result)


def test_returns_none_without_request_id():
    db = _FakeSession(result=object())
    assert queue_worker._find_existing_audit_for_request(db, 1, None) is None
    # Must not even query when there is no request_id
    assert db.query_calls == 0


def test_returns_existing_audit_when_found():
    sentinel = object()
    db = _FakeSession(result=sentinel)
    found = queue_worker._find_existing_audit_for_request(db, 7, "req-123")
    assert found is sentinel
    assert db.query_calls == 1


def test_returns_none_when_not_found():
    db = _FakeSession(result=None)
    assert queue_worker._find_existing_audit_for_request(db, 7, "req-xyz") is None
    assert db.query_calls == 1
