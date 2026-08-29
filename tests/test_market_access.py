import pytest

from fpb.market_access import economic_readiness, market_access
from fpb.types import INSUFFICIENT, Metric

LABELS = {
    "fs_green_loan": "High",
    "fs_lease_rent": "High",
    "fs_baas": "Medium",
    "fs_project_finance": "Low",
    "fs_blended_finance": "Medium",
}


def test_market_access_reference_labels(bundle):
    m = market_access(LABELS, bundle.scoring["market_access"])
    assert m.value == pytest.approx(73.0)


def test_market_access_case_insensitive_labels(bundle):
    m = market_access(
        {k: v.lower() for k, v in LABELS.items()}, bundle.scoring["market_access"]
    )
    assert m.value == pytest.approx(73.0)


def test_market_access_missing_field_is_insufficient(bundle):
    m = market_access({}, bundle.scoring["market_access"])
    assert m.state == INSUFFICIENT
    assert len(m.missing) == 5


def test_economic_readiness_workbook_case(bundle):
    er = economic_readiness(
        Metric(75.85664885256209), Metric(50.0), Metric(73.0),
        bundle.scoring["economic_readiness"],
    )
    assert er.value == pytest.approx(68.67832442628105)


def test_economic_readiness_propagates_insufficient(bundle):
    er = economic_readiness(
        Metric.insufficient(("tco_x",)), Metric(50.0), Metric(73.0),
        bundle.scoring["economic_readiness"],
    )
    assert er.state == INSUFFICIENT
    assert "tco_x" in er.missing
