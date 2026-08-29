import pytest

from fpb.tco import PowertrainInputs, run

D = PowertrainInputs(500, 0, 906, 40, 15, 0, 0, 60, 30)
E = PowertrainInputs(850, 100, 450, 25, 12, 50, 100, 0, 50)


def test_workbook_totals_reproduced():
    r = run(D, E, 50000, 8)
    assert r.diesel.total_idr_m == pytest.approx(1272.4)
    assert r.ev.total_idr_m == pytest.approx(1426.0)
    assert r.diesel.cost_per_km == pytest.approx(3181, abs=1)
    assert r.ev.cost_per_km == pytest.approx(3565, abs=1)


def test_competitiveness_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.competitiveness.value == pytest.approx(75.85664885256209)


def test_investment_burden_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.investment_burden.value == pytest.approx(50.0)


def test_payback_and_saving_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.operating_saving_pct == pytest.approx(0.4067796610169491)
    assert r.payback_years == pytest.approx(6.127450980392157)
    assert r.break_even_km == pytest.approx(306372.54901960783)
    assert r.recovered_within_horizon is True


def test_symmetric_diesel_formula_counts_diesel_battery_line():
    d2 = PowertrainInputs(500, 0, 906, 40, 15, 0, 35, 60, 30)
    r = run(d2, E, 50000, 8)
    assert r.diesel.total_idr_m == pytest.approx(1307.4)


def test_no_premium_means_no_burden():
    e = PowertrainInputs(400, 100, 450, 25, 12, 0, 0, 0, 0)
    r = run(D, e, 50000, 8)
    assert r.investment_burden.value == 100.0


def test_zero_diesel_net_with_ev_premium_is_zero_burden_score():
    d = PowertrainInputs(0, 0, 906, 40, 15, 0, 0, 0, 0)
    r = run(d, E, 50000, 8)
    assert r.investment_burden.value == 0.0
    assert "diesel net CAPEX zero" in r.investment_burden.detail


def test_payback_beyond_horizon_flagged():
    e = PowertrainInputs(2000, 0, 450, 25, 12, 0, 0, 0, 0)
    r = run(D, e, 50000, 8)
    assert r.payback_years > 8
    assert r.recovered_within_horizon is False


def test_cold_chain_default_applies_to_both():
    r = run(D, E, 50000, 8, cc_capex_idr_m=50, cc_energy_idr_m_yr=25)
    assert r.ev.total_idr_m == pytest.approx(1426.0 + 250)
    assert r.diesel.total_idr_m == pytest.approx(1272.4 + 250)
    ev_only = run(D, E, 50000, 8, cc_capex_idr_m=50, cc_energy_idr_m_yr=25,
                  apply_to=("ev",))
    assert ev_only.diesel.total_idr_m == pytest.approx(1272.4)
