from __future__ import annotations

from .types import INSUFFICIENT, Metric


def market_access(record: dict, cfg: dict) -> Metric:
    scale = {k.lower(): v for k, v in cfg["scale"].items()}
    values, missing = [], []
    for slug in cfg["slugs"]:
        v = record.get(slug)
        if v is None:
            missing.append(slug)
        else:
            values.append(scale[str(v).strip().lower()])
    if missing:
        return Metric.insufficient(tuple(missing))
    return Metric(sum(values) / len(values))


def economic_readiness(
    tco_comp: Metric, burden: Metric, access: Metric, cfg: dict
) -> Metric:
    inputs = {
        "tco_competitiveness": tco_comp,
        "investment_burden": burden,
        "market_access": access,
    }
    missing = tuple(
        s for m in inputs.values() for s in m.missing if m.state == INSUFFICIENT
    )
    if any(m.state == INSUFFICIENT for m in inputs.values()):
        return Metric.insufficient(missing)
    w = cfg["weights"]
    return Metric(
        w["tco_competitiveness"] * tco_comp.value
        + w["investment_burden"] * burden.value
        + w["market_access"] * access.value
    )
