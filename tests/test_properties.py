import random

import pytest

from fpb.engine import score
from fpb.types import COMPUTED, INSUFFICIENT, NOT_APPLICABLE

STATES = {COMPUTED, INSUFFICIENT, NOT_APPLICABLE}
FS = [
    "fs_green_loan",
    "fs_lease_rent",
    "fs_baas",
    "fs_project_finance",
    "fs_blended_finance",
]
FN = [
    "fn_external_need",
    "fn_cashflow_constraint",
    "fn_payment_preference",
    "fn_support_requirement",
]
RP = [
    "rp_ownership",
    "rp_technology",
    "rp_battery",
    "rp_residual",
    "rp_maintenance",
    "rp_downtime",
]


def _record(rng):
    rec = {x: rng.randint(1, 5) for x in FN}
    rec.update({x: rng.randint(1, 5) for x in RP})
    rec["tco_annual_km"] = rng.choice([12000, 36000, 50000, 90000])
    rec["tco_years"] = rng.choice([5, 6, 7, 8, 10])
    for p in ("tco_diesel_", "tco_ev_"):
        rec[f"{p}capex"] = rng.randint(150, 2500)
        rec[f"{p}subsidy"] = rng.choice([0, 0, 50, 100, 200])
        rec[f"{p}energy_idr_km"] = rng.randint(200, 1500)
        rec[f"{p}maintenance_idr_m_yr"] = rng.randint(5, 80)
        rec[f"{p}insurance_idr_m_yr"] = rng.randint(3, 40)
        rec[f"{p}infra_idr_m"] = rng.choice([0, 0, 25, 50, 150])
        rec[f"{p}battery_idr_m"] = rng.choice([0, 0, 60, 120])
        rec[f"{p}residual_idr_m"] = rng.randint(0, 200)
        rec[f"{p}financing_idr_m"] = rng.randint(0, 150)
    rec.update({x: rng.choice(["None", "Low", "Medium", "High"]) for x in FS})
    return rec


def test_invariants_over_200_randomized_cases(bundle):
    for seed in range(200):
        rng = random.Random(seed)
        r = score(
            _record(rng),
            bundle,
            {"consumer_readiness": rng.randint(0, 100), "city_cri": rng.randint(0, 100)},
        )
        for name, m in r.metrics.items():
            assert m.state in STATES, name
            if m.state == COMPUTED:
                assert 0.0 <= m.value <= 100.0, (name, m.value)
            else:
                assert m.value is None, name

        eligible = [s for s in r.schemes if s.status == "active" and s.total is not None]
        assert sum(1 for s in eligible if s.is_primary) <= 1
        ranks = sorted(s.rank for s in eligible)
        assert ranks == list(range(1, len(eligible) + 1))
        ordered = sorted(eligible, key=lambda s: s.rank)
        totals = [s.total for s in ordered]
        assert totals == sorted(totals, reverse=True)
        for i in range(len(totals) - 1):
            if totals[i] == totals[i + 1]:
                assert ordered[i].rank < ordered[i + 1].rank


def test_weights_sum_to_one(bundle):
    s = bundle.scoring
    assert sum(s["financing_need"]["weights"]) == pytest.approx(1.0)
    assert sum(s["risk_profile"]["weights"]) == pytest.approx(1.0)
    assert sum(s["economic_readiness"]["weights"].values()) == pytest.approx(1.0)
    assert sum(s["overall_fit"]["weights"].values()) == pytest.approx(1.0)
    assert sum(bundle.schemes["weights"].values()) == pytest.approx(1.0)


def test_raising_a_fit_dimension_raises_the_total(bundle):
    from copy import deepcopy
    from types import SimpleNamespace

    from fpb.engine import score as _score

    base = _score(
        _record(random.Random(7)), bundle, {"consumer_readiness": 60, "city_cri": 50}
    )
    bumped_schemes = deepcopy(bundle.schemes)
    five = next(x for x in bumped_schemes["schemes"] if x["id"] == "5")
    five["fit"]["operational"]["constant"] = 100

    class AltBundle:  # duck-type ConfigBundle with only the fields the engine touches
        spec_version = bundle.spec_version
        config_version = bundle.config_version
        questionnaire = bundle.questionnaire
        scoring = bundle.scoring
        schemes = bumped_schemes

    alt = _score(
        _record(random.Random(7)), AltBundle, {"consumer_readiness": 60, "city_cri": 50}
    )
    b = next(x for x in base.schemes if x.scheme_id == "5")
    a = next(x for x in alt.schemes if x.scheme_id == "5")
    if b.total is not None and b.fits["operational"] is not None:
        assert a.total > b.total
