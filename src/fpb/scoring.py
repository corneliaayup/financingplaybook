from __future__ import annotations

from .types import Metric


def likert_index(score: float) -> float:
    return (score - 1) / 4 * 100


def band(index: float, bands: dict) -> str:
    for name, (lo, hi) in bands.items():
        if lo <= index <= hi:
            return name.upper()
    raise ValueError(f"index {index} outside bands {bands}")


def _gather(record: dict, slugs: list[str]) -> tuple[list[float], tuple[str, ...]]:
    values, missing = [], []
    for slug in slugs:
        v = record.get(slug)
        if v is None:
            missing.append(slug)
        else:
            values.append(float(v))
    return values, tuple(missing)


def financing_need(record: dict, cfg: dict) -> Metric:
    values, missing = _gather(record, cfg["slugs"])
    if missing:
        return Metric.insufficient(missing)
    weights = cfg["weights"]
    return Metric(likert_index(sum(v * w for v, w in zip(values, weights))))


def risk_profile(record: dict, cfg: dict) -> Metric:
    own = record.get(cfg["ownership_slug"])
    tols, missing = _gather(record, cfg["tolerance_slugs"])
    if own is None:
        missing = (cfg["ownership_slug"],) + missing
    if missing:
        return Metric.insufficient(missing)
    w_own, w_tol = cfg["weights"]
    score = w_own * float(own) + w_tol * (sum(tols) / len(tols))
    return Metric(likert_index(score))
