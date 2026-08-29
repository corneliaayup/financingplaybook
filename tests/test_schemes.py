import pytest

from fpb.schemes import evaluate_scheme, rank_schemes

BANDS = {"low": (0, 33), "medium": (34, 66), "high": (67, 100)}
W = {
    "need": 0.20,
    "risk": 0.20,
    "tco": 0.20,
    "operational": 0.15,
    "payment": 0.10,
    "support": 0.15,
}

# Workbook illustrative case: need 93.75 (HIGH), risk 95.0 (HIGH),
# EV 3565 vs diesel 3181 Rp/km, FN4 = 5
VALS = {
    "financing_need_index": 93.75,
    "risk_profile_index": 95.0,
    "fn_support_requirement": 5,
    "ev_cost_per_km": 3565.0,
    "diesel_cost_per_km": 3181.0,
}

# Sheet 'Scheme Match' H4:H11 — reproduced to the cent in the design phase.
SHEET = {"1": 63.5, "2": 63.0, "3": 75.25, "4": 82.5, "4a/4b": 83.75,
         "5": 92.25, "6": 89.0, "7": 86.75}


def test_all_eight_active_schemes_reproduce_sheet_totals(bundle):
    active = [s for s in bundle.schemes["schemes"] if s["status"] == "active"]
    assert len(active) == 8
    for s in active:
        r = evaluate_scheme(s, VALS, W, BANDS)
        assert r.total == pytest.approx(SHEET[r.scheme_id]), r.scheme_id


def test_rank_order_matches_sheet(bundle):
    active = [s for s in bundle.schemes["schemes"] if s["status"] == "active"]
    by_id = {s["id"]: s for s in active}
    ranked = rank_schemes([evaluate_scheme(s, VALS, W, BANDS) for s in active], by_id)
    order = {r.scheme_id: r.rank for r in ranked}
    assert order == {"5": 1, "6": 2, "7": 3, "4a/4b": 4, "4": 5, "3": 6,
                     "1": 7, "2": 8}
    assert [r.scheme_id for r in ranked if r.is_primary] == ["5"]


def test_fit_details_explain_the_number(bundle):
    s = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    r = evaluate_scheme(s, VALS, W, BANDS)
    assert "financing_need_index" in r.fit_details["need"]
    assert r.fit_details["need"].startswith("financing_need_index=93.75")
    assert "band=HIGH" in r.fit_details["need"]


def test_gap_closer_support_rule(bundle):
    s5 = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    low = dict(VALS, fn_support_requirement=3)
    r = evaluate_scheme(s5, low, W, BANDS)
    assert r.fits["support"] == 70
    assert r.total == pytest.approx(92.25 - 0.15 * 30)


def test_draft_schemes_are_ineligible_but_visible(bundle):
    all_schemes = bundle.schemes["schemes"]
    active = [s for s in all_schemes if s["status"] == "active"]
    drafts = [s for s in all_schemes if s["status"] == "draft"]
    assert {s["id"] for s in drafts} == {"gl", "pf"}
    results = [evaluate_scheme(s, VALS, W, BANDS) for s in active + drafts]
    ranked = rank_schemes(results, {s["id"]: s for s in active + drafts})
    for r in ranked:
        if r.status == "draft":
            assert r.rank == 0 and not r.is_primary


def test_tie_break_is_deterministic_and_visible():
    a = {"id": "a", "name": "A", "status": "active", "library_priority": 1,
         "fit": {d: {"constant": 80} for d in W}
                | {"total": {"weighted_sum": list(W)}}}
    b = dict(a, id="b", name="B", library_priority=2)
    ranked = rank_schemes(
        [evaluate_scheme(a, {}, W, BANDS), evaluate_scheme(b, {}, W, BANDS)],
        {"a": a, "b": b},
    )
    assert [(r.scheme_id, r.rank) for r in ranked] == [("a", 1), ("b", 2)]
    assert ranked[0].is_primary and not ranked[1].is_primary
    assert ranked[0].tie_with == "b" and ranked[1].tie_with == "a"


def test_unavailable_input_yields_none_not_a_default(bundle):
    vals = dict(VALS, ev_cost_per_km=None, diesel_cost_per_km=None)
    s5 = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    r = evaluate_scheme(s5, vals, W, BANDS)
    assert r.fits["tco"] is None and r.total is None
