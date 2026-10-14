import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import models
import routers.external_api_router as ext


def test_serialize_scores_includes_overall_from_report():
    audit = models.Audit(
        geo_score=70,
        seo_score=80,
        aeo_score=60,
        full_report={"scores": {"overall": 88.0}},
    )
    summary = ext._serialize_scores(audit)
    assert summary == {"geo": 70, "seo": 80, "aeo": 60, "overall": 88.0}


def test_serialize_scores_overall_falls_back_to_pillar_mean():
    audit = models.Audit(geo_score=60, seo_score=90, aeo_score=None, full_report=None)
    summary = ext._serialize_scores(audit)
    # mean of the available pillars (60, 90); aeo (None) excluded.
    assert summary["overall"] == 75.0
    assert summary["geo"] == 60 and summary["seo"] == 90


def test_serialize_scores_none_for_missing_audit():
    assert ext._serialize_scores(None) is None
