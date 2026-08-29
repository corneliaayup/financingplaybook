import pytest

from fpb.scoring import band, financing_need, likert_index, risk_profile
from fpb.types import INSUFFICIENT

BANDS = {"low": (0, 33), "medium": (34, 66), "high": (67, 100)}


def test_likert_index():
    assert likert_index(1) == 0.0
    assert likert_index(3) == 50.0
    assert likert_index(5) == 100.0
    assert likert_index(4.75) == 93.75


def test_band_edges():
    assert band(0, BANDS) == "LOW" and band(33, BANDS) == "LOW"
    assert band(34, BANDS) == "MEDIUM" and band(66, BANDS) == "MEDIUM"
    assert band(67, BANDS) == "HIGH" and band(100, BANDS) == "HIGH"


def test_financing_need_workbook_case(bundle):
    rec = {
        "fn_external_need": 5,
        "fn_cashflow_constraint": 4,
        "fn_payment_preference": 5,
        "fn_support_requirement": 5,
    }
    m = financing_need(rec, bundle.scoring["financing_need"])
    assert m.value == pytest.approx(93.75)
    assert m.state == "computed"


def test_risk_profile_uses_50_50_rule(bundle):
    rec = {
        "rp_ownership": 5,
        "rp_technology": 4,
        "rp_battery": 5,
        "rp_residual": 5,
        "rp_maintenance": 4,
        "rp_downtime": 5,
    }
    m = risk_profile(rec, bundle.scoring["risk_profile"])
    assert m.value == pytest.approx(95.0)


def test_risk_profile_divergent_answers_not_simple_average(bundle):
    rec = {
        "rp_ownership": 5,
        "rp_technology": 1,
        "rp_battery": 1,
        "rp_residual": 1,
        "rp_maintenance": 1,
        "rp_downtime": 1,
    }
    m = risk_profile(rec, bundle.scoring["risk_profile"])
    assert m.value == pytest.approx(50.0)


def test_missing_fields_are_insufficient_not_defaulted(bundle):
    m = financing_need({}, bundle.scoring["financing_need"])
    assert m.state == INSUFFICIENT
    assert set(m.missing) == {
        "fn_external_need",
        "fn_cashflow_constraint",
        "fn_payment_preference",
        "fn_support_requirement",
    }
