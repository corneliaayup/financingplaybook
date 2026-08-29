import pytest

from fpb.display import (
    band_label,
    fmt_metric,
    fmt_rupiah,
    pct,
    scheme_frame,
    state_badge,
)
from fpb.types import COMPUTED, INSUFFICIENT, NOT_APPLICABLE, Metric


def test_fmt_metric_computed_rounds_one_decimal():
    assert fmt_metric(Metric(80.12458)) == "80.1"


def test_fmt_metric_insufficient_shows_state():
    assert fmt_metric(Metric.insufficient(("a",))) == "Insufficient inputs"


def test_fmt_metric_not_applicable():
    assert fmt_metric(Metric(None, NOT_APPLICABLE)) == "Not applicable"


def test_fmt_rupiah():
    assert fmt_rupiah(1272.4) == "Rp 1,272.4 M"
    assert fmt_rupiah(None) == "—"


def test_pct():
    assert pct(0.5687) == "56.9%"
    assert pct(None) == "—"


def test_band_label():
    bands = {"low": [0, 33], "medium": [34, 66], "high": [67, 100]}
    assert band_label(80.1, bands) == "HIGH"
    assert band_label(None, bands) == "—"


def test_state_badge():
    assert state_badge(COMPUTED) == "computed"
    assert state_badge(INSUFFICIENT) == "insufficient_inputs"
    assert state_badge(NOT_APPLICABLE) == "not_applicable"


def test_scheme_frame_columns_and_order():
    from fpb.types import SchemeResult

    r = SchemeResult(
        scheme_id="5",
        name="Blended Finance / VGF",
        status="active",
        fits={"total": 83.75},
        fit_details={},
        total=83.75,
        rank=1,
        is_primary=True,
        tie_with=None,
    )
    df = scheme_frame([r], {"need": 0.2})
    assert list(df.columns) == ["Rank", "Scheme", "Status", "Fit", "Primary", "Tie"]
    assert df.iloc[0]["Primary"] == "Primary"
    assert df.iloc[0]["Fit"] == 83.75
