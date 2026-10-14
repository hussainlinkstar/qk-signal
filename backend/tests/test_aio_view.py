import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.aio_view import derive_aio


def test_aio_is_mean_of_aeo_geo():
    out = derive_aio({"aeo_score": 40, "geo_score": 60, "summary": "x"})
    assert out["aio_score"] == 50
    assert out["components"] == {"aeo": 40, "geo": 60}
    assert out["scope"] == "website_and_brand"


def test_aio_handles_single_present():
    assert derive_aio({"aeo_score": 42, "geo_score": None})["aio_score"] == 42


def test_aio_none_when_both_missing():
    assert derive_aio({"aeo_score": None, "geo_score": None})["aio_score"] is None
