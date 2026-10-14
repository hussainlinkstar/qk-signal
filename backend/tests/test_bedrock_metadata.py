import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import core.bedrock_metadata as bm
import core.bedrock_text as bt
from core.config import settings


def test_build_request_metadata_core_fields(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    md = bm.build_request_metadata("audit_reasoning", tier="smart")
    assert md["app"] == "qiko_signal"
    assert md["use_case"] == "audit_reasoning"
    assert md["role"] == "teacher"
    assert md["tier"] == "smart"
    assert md["env"] == "production"


def test_build_request_metadata_sanitizes_and_caps():
    md = bm.build_request_metadata("audit/expert!seo*", extra={f"k{i}": i for i in range(30)})
    # disallowed chars replaced; '/' and ':' are allowed, '!' and '*' are not.
    assert "!" not in md["use_case"] and "*" not in md["use_case"]
    assert "audit/expert" in md["use_case"]
    assert len(md) <= 16  # Bedrock's 16-entry cap

    long_value = bm.build_request_metadata("x" * 500)
    assert len(long_value["use_case"]) <= 256


def test_bedrock_generate_text_tags_invocation_with_request_metadata(monkeypatch):
    captured: dict = {}

    class _FakeClient:
        def converse(self, **kwargs):
            captured.update(kwargs)
            return {"output": {"message": {"content": [{"text": "ok"}]}}}

    monkeypatch.setattr(settings, "BEDROCK_ENABLED", True)
    # SIGV2-1028: the runtime client is built via the shared region-aware
    # factory in core.bedrock_runtime; patch that seam instead of bt.boto3.
    monkeypatch.setattr(bt, "create_bedrock_runtime_client", lambda *a, **k: _FakeClient())

    out = bt.bedrock_generate_text("sys", "user", tier="fast", use_case="pre_scan")

    assert out == "ok"
    assert captured["requestMetadata"]["use_case"] == "pre_scan"
    assert captured["requestMetadata"]["tier"] == "fast"
    assert captured["requestMetadata"]["role"] == "teacher"
