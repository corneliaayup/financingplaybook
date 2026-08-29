from __future__ import annotations

import pandas as pd

from .types import COMPUTED, Metric, SchemeResult


def fmt_metric(m: Metric) -> str:
    if m.state == COMPUTED and m.value is not None:
        return f"{m.value:.1f}"
    if m.state == "insufficient_inputs":
        return "Insufficient inputs"
    if m.state == "not_applicable":
        return "Not applicable"
    return m.state


def fmt_rupiah(value: float | None) -> str:
    if value is None:
        return "—"
    return f"Rp {value:,.1f} M"


def pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def band_label(value: float | None, bands: dict) -> str:
    if value is None:
        return "—"
    for name, (lo, hi) in bands.items():
        if lo <= value <= hi:
            return name.upper()
    return "—"


def state_badge(state: str) -> str:
    return state


def scheme_frame(results: list[SchemeResult], weights: dict) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append(
            {
                "Rank": r.rank if r.rank else pd.NA,
                "Scheme": f"{r.scheme_id}. {r.name}",
                "Status": r.status,
                "Fit": r.total,
                "Primary": "Primary" if r.is_primary else "",
                "Tie": r.tie_with or "",
            }
        )
    df = pd.DataFrame(
        rows, columns=["Rank", "Scheme", "Status", "Fit", "Primary", "Tie"]
    )
    df["Rank"] = df["Rank"].astype("Int64")
    return df
