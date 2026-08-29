import json
from pathlib import Path

import pytest

from fpb.engine import score
from fpb.types import COMPUTED, INSUFFICIENT

REPO = Path(__file__).resolve().parents[1]
WORKBOOK = json.loads((REPO / "tests/fixtures/workbook_case.json").read_text())
CTX = {"consumer_readiness": 57, "city_cri": 40.4}


def test_workbook_case_end_to_end(bundle):
    r = score(WORKBOOK, bundle, CTX)
    m = r.metrics
    assert m["financing_need_index"].value == pytest.approx(93.75)
    assert m["risk_profile_index"].value == pytest.approx(95.0)
    assert m["tco_competitiveness"].value == pytest.approx(75.85664885256209)
    assert m["investment_burden"].value == pytest.approx(50.0)
    assert m["market_access"].value == pytest.approx(73.0)
    assert m["economic_readiness"].value == pytest.approx(68.67832442628105)
    assert r.overall.value == pytest.approx(80.12458110657028)
    assert r.primary_id == "5"
    assert r.spec_version == "2026-01" and r.config_version == "2026-01"


def test_tco_totals_match_sheet(bundle):
    r = score(WORKBOOK, bundle, CTX)
    assert r.tco["diesel"]["total_idr_m"] == pytest.approx(1272.4)
    assert r.tco["ev"]["total_idr_m"] == pytest.approx(1426.0)
    assert r.tco["diesel"]["cost_per_km"] == pytest.approx(3181, abs=1)
    assert r.tco["recovered_within_horizon"] is True


def test_missing_tco_degrades_specific_metrics_not_all(bundle):
    rec = {k: v for k, v in WORKBOOK.items() if not k.startswith(("tco_", "cc_"))}
    r = score(rec, bundle, CTX)
    assert r.metrics["financing_need_index"].state == COMPUTED
    assert r.metrics["risk_profile_index"].state == COMPUTED
    assert r.metrics["tco_competitiveness"].state == INSUFFICIENT
    assert r.metrics["economic_readiness"].state == INSUFFICIENT
    assert r.overall.state == INSUFFICIENT
    assert "tco_ev_capex" in r.overall.missing
    assert r.primary_id is None
    # active schemes need TCO to score; draft schemes use constant placeholders and
    # stay computable-but-ineligible (that is their design: visible, not ranked)
    assert all(s.total is None for s in r.schemes if s.status == "active")
    assert all(s.total is not None for s in r.schemes if s.status == "draft")
    assert all(not s.is_primary for s in r.schemes)


def test_missing_readiness_context_is_reported(bundle):
    r = score(WORKBOOK, bundle, {"consumer_readiness": None, "city_cri": 40.4})
    assert r.metrics["readiness_context"].state == INSUFFICIENT
    assert "consumer_readiness" in r.metrics["readiness_context"].missing
    assert r.overall.state == INSUFFICIENT


def test_draft_schemes_never_primary(bundle):
    r = score(WORKBOOK, bundle, CTX)
    ids = {s.scheme_id for s in r.schemes}
    assert {"gl", "pf"} <= ids
    assert all(not s.is_primary for s in r.schemes if s.status == "draft")


def test_versions_are_stamped(bundle):
    r = score(WORKBOOK, bundle, CTX)
    assert r.spec_version and r.config_version
