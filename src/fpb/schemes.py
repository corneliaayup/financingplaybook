from __future__ import annotations

from dataclasses import replace

from .scoring import band
from .types import SchemeResult


def eval_fit(
    rule: dict, values: dict, bands: dict, scheme: dict
) -> tuple[float | None, str]:
    prim = next(iter(rule))
    arg = rule[prim]

    if prim == "constant":
        return float(arg), f"constant {arg}"

    if prim == "target_band":
        v = values.get(arg["source"])
        if v is None:
            return None, f"{arg['source']} unavailable"
        b = band(v, bands)
        hit = b == arg["target"]
        score = arg["match"] if hit else arg["mismatch"]
        return float(score), (
            f"{arg['source']}={v:g} band={b} target={arg['target']} -> {score}"
        )

    if prim == "parity_or_gap":
        ev = values.get("ev_cost_per_km")
        dz = values.get("diesel_cost_per_km")
        if ev is None or dz is None:
            return None, "TCO cost/km unavailable"
        if ev <= dz:
            return float(arg["match"]), (
                f"EV {ev:g} <= diesel {dz:g} Rp/km -> {arg['match']}"
            )
        if scheme.get("closes_financing_gap"):
            return float(arg["gap_group"]), (
                f"EV {ev:g} > diesel {dz:g}; closes financing gap -> {arg['gap_group']}"
            )
        return float(arg["else"]), (
            f"EV {ev:g} > diesel {dz:g}; no gap closure -> {arg['else']}"
        )

    if prim == "support_fit":
        gc = arg["gap_closer"]
        if scheme.get("support_gap_closer"):
            v = values.get(gc["metric"])
            if v is None:
                return None, f"{gc['metric']} unavailable"
            hit = v >= gc["ge"]
            score = gc["then"] if hit else gc["else"]
            return float(score), (
                f"gap-closer {gc['metric']}={v:g} >= {gc['ge']}? {hit} -> {score}"
            )
        if scheme.get("green_eligible"):
            return float(arg["green_eligible"]), (
                f"green-eligible channel -> {arg['green_eligible']}"
            )
        return float(arg["default"]), f"default channel -> {arg['default']}"

    raise ValueError(f"unknown fit primitive: {prim}")


def evaluate_scheme(
    scheme: dict, values: dict, weights: dict, bands: dict
) -> SchemeResult:
    fits: dict[str, float | None] = {}
    details: dict[str, str] = {}
    for dim, rule in scheme["fit"].items():
        if dim == "total":
            continue
        fits[dim], details[dim] = eval_fit(rule, values, bands, scheme)
    if any(v is None for v in fits.values()):
        total = None
        details["total"] = "one or more fit dimensions unavailable"
    else:
        total = sum(fits[k] * weights[k] for k in weights)
        details["total"] = "weighted_sum(" + ", ".join(
            f"{k}*{weights[k]}" for k in weights
        ) + ")"
    return SchemeResult(
        scheme["id"], scheme["name"], scheme["status"], fits, details, total
    )


def rank_schemes(
    results: list[SchemeResult], schemes_by_id: dict
) -> list[SchemeResult]:
    eligible = [r for r in results if r.status == "active" and r.total is not None]
    order = sorted(
        eligible,
        key=lambda r: (-r.total, schemes_by_id[r.scheme_id]["library_priority"]),
    )
    ranked = []
    for i, r in enumerate(order):
        tied = [o.scheme_id for o in order if o is not r and o.total == r.total]
        ranked.append(
            replace(
                r,
                rank=i + 1,
                is_primary=(i == 0),
                tie_with=",".join(sorted(tied)) or None,
            )
        )
    for r in results:
        if r not in eligible:
            ranked.append(replace(r, rank=0, is_primary=False))
    return ranked
