from __future__ import annotations

from dataclasses import asdict

from .config import ConfigBundle
from .market_access import economic_readiness, market_access
from .schemes import evaluate_scheme, rank_schemes
from .scoring import financing_need, risk_profile
from .tco import PowertrainInputs, run as run_tco
from .types import INSUFFICIENT, AssessmentResult, Metric


def _f(record: dict, slug: str) -> float | None:
    v = record.get(slug)
    return None if v is None else float(v)


def score(record: dict, bundle: ConfigBundle, context: dict) -> AssessmentResult:
    s = bundle.scoring
    warnings: list[str] = []
    metrics: dict[str, Metric] = {
        "financing_need_index": financing_need(record, s["financing_need"]),
        "risk_profile_index": risk_profile(record, s["risk_profile"]),
        "market_access": market_access(record, s["market_access"]),
    }

    t = s["tco"]
    needed = (
        [f"{p}{f}" for p in (t["diesel_prefix"], t["ev_prefix"]) for f in t["fields"]]
        + [t["annual_km_slug"], t["years_slug"]]
    )
    missing = sorted(x for x in needed if record.get(x) is None)
    if missing:
        tco_block = {"state": INSUFFICIENT, "missing": missing}
        comp = burden = Metric.insufficient(tuple(missing))
    else:
        cc = s["cold_chain"]
        res = run_tco(
            PowertrainInputs(*[_f(record, t["diesel_prefix"] + f) for f in t["fields"]]),
            PowertrainInputs(*[_f(record, t["ev_prefix"] + f) for f in t["fields"]]),
            _f(record, t["annual_km_slug"]),
            _f(record, t["years_slug"]),
            _f(record, cc["capex_slug"]) or 0.0,
            _f(record, cc["energy_slug"]) or 0.0,
            tuple(cc["apply_to"]),
        )
        tco_block = {
            "diesel": asdict(res.diesel),
            "ev": asdict(res.ev),
            "operating_saving_pct": res.operating_saving_pct,
            "payback_years": res.payback_years,
            "break_even_km": res.break_even_km,
            "recovered_within_horizon": res.recovered_within_horizon,
            "cold_chain_apply_to": list(cc["apply_to"]),
        }
        comp, burden = res.competitiveness, res.investment_burden
        if not res.recovered_within_horizon:
            warnings.append(
                "EV CAPEX premium is not recovered within the assessment horizon"
            )
    metrics["tco_competitiveness"] = comp
    metrics["investment_burden"] = burden

    consumer = (
        _f(context, "consumer_readiness")
        if context.get("consumer_readiness") is not None
        else None
    )
    cri = _f(context, "city_cri") if context.get("city_cri") is not None else None
    if consumer is None or cri is None:
        miss = tuple(
            x for x, v in (("consumer_readiness", consumer), ("city_cri", cri)) if v is None
        )
        readiness = Metric.insufficient(miss)
    else:
        readiness = Metric((consumer + cri) / 2)
    metrics["readiness_context"] = readiness

    metrics["economic_readiness"] = economic_readiness(
        comp, burden, metrics["market_access"], s["economic_readiness"]
    )

    values = {
        "financing_need_index": metrics["financing_need_index"].value,
        "risk_profile_index": metrics["risk_profile_index"].value,
        "fn_support_requirement": _f(record, "fn_support_requirement"),
        "ev_cost_per_km": (tco_block.get("ev") or {}).get("cost_per_km"),
        "diesel_cost_per_km": (tco_block.get("diesel") or {}).get("cost_per_km"),
    }
    weights = bundle.schemes["weights"]
    by_id = {x["id"]: x for x in bundle.schemes["schemes"]}
    evaluated = [
        evaluate_scheme(x, values, weights, s["bands"]) for x in by_id.values()
    ]
    ranked = rank_schemes(evaluated, by_id)
    primary = next((r for r in ranked if r.is_primary), None)

    inputs = {
        "primary_scheme_fit": (
            Metric(primary.total) if primary else Metric.insufficient(("primary_scheme_fit",))
        ),
        "economic_readiness": metrics["economic_readiness"],
        "financing_need_index": metrics["financing_need_index"],
        "readiness_context": readiness,
    }
    if primary is None and any(s.total is None for s in ranked):
        warnings.append("no scheme could be fully scored; recommendation withheld")
    gap = tuple(sorted({m for mt in inputs.values() for m in mt.missing}))
    overall = (
        Metric.insufficient(gap)
        if gap
        else Metric(
            sum(w * inputs[k].value for k, w in s["overall_fit"]["weights"].items())
        )
    )
    metrics["overall_financing_fit"] = overall

    return AssessmentResult(
        bundle.spec_version,
        bundle.config_version,
        metrics,
        tco_block,
        ranked,
        overall,
        primary.scheme_id if primary else None,
        warnings,
    )
