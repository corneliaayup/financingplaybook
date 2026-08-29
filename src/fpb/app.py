from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from fpb.config import load_config, validate_config
from fpb.display import band_label, fmt_metric, fmt_rupiah, pct, scheme_frame
from fpb.engine import score
from fpb.ingest import ReaderError, build_case_input, read_excel_form, read_json_record

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONTEXT = {"consumer_readiness": 57.0, "city_cri": 40.4}


def _load_bundle():
    bundle = load_config(REPO / "config")
    problems = validate_config(bundle)
    if problems:
        st.error("Configuration is invalid:\n" + "\n".join(problems))
        st.stop()
    return bundle


def _example_input():
    raw = json.loads((REPO / "tests" / "fixtures" / "workbook_case.json").read_text())
    raw.update(DEFAULT_CONTEXT)  # context slugs feed the readiness context
    return raw, "example"


def main() -> None:
    st.set_page_config(page_title="Financing Playbook", layout="wide")
    bundle = _load_bundle()
    st.title("Financing Playbook")

    with st.sidebar:
        st.header("Input")
        mode = st.radio("Source", ["Example", "Excel form", "JSON record"])
        xlsx = (
            st.file_uploader("Respondent questionnaire (.xlsx)", type=["xlsx"])
            if mode == "Excel form"
            else None
        )
        jfile = (
            st.file_uploader("Record (.json)", type=["json"])
            if mode == "JSON record"
            else None
        )

    try:
        if mode == "Excel form":
            if xlsx is None:
                st.info("Upload the respondent questionnaire Excel form to start.")
                return
            raw = read_excel_form(xlsx)
            source = f"excel: {xlsx.name}"
        elif mode == "JSON record":
            if jfile is None:
                st.info("Upload a JSON record to start.")
                return
            raw = read_json_record(jfile.getvalue().decode("utf-8"))
            source = f"json: {jfile.name}"
        else:
            raw, mode = _example_input()
            source = "example: workbook_case.json"

        case = build_case_input(raw, bundle.questionnaire, source)
        result = score(case.record, bundle, case.context)
    except ReaderError as exc:
        st.error(str(exc))
        return

    st.caption(
        f"Source: {source}  ·  spec {result.spec_version}  ·  config {result.config_version}"
    )

    if case.issues:
        st.warning(
            f"{len(case.issues)} validation issue(s) found — invalid values were "
            "excluded, so some panels may be incomplete."
        )
        for issue in case.issues:
            st.warning(f"**{issue.label}** ({issue.slug}): {issue.message}")
    else:
        st.success("Record validated — all fields accepted.")

    st.header("Overall Financing Fit")
    c1, c2 = st.columns(2)
    c1.metric(
        "Overall Financing Fit",
        fmt_metric(result.overall),
        band_label(result.overall.value, bundle.scoring["bands"]),
    )
    if result.primary_id:
        primary = next(s for s in result.schemes if s.scheme_id == result.primary_id)
        c2.metric(
            "Primary scheme",
            f"{primary.scheme_id}. {primary.name}",
            f"{primary.total:.1f}" if primary.total is not None else "—",
        )
    else:
        c2.metric("Primary scheme", "—", "No eligible recommendation")

    st.subheader("Indices and market access")
    cards = st.columns(4)
    for col, key in zip(
        cards,
        [
            "financing_need_index",
            "risk_profile_index",
            "market_access",
            "readiness_context",
        ],
    ):
        metric = result.metrics[key]
        col.metric(
            key.replace("_", " ").title(),
            fmt_metric(metric),
            band_label(metric.value, bundle.scoring["bands"]),
        )

    st.subheader("TCO comparison")
    t = result.tco
    if t.get("state") == "insufficient_inputs":
        st.info("TCO inputs incomplete — missing: " + ", ".join(t.get("missing", [])))
    else:
        d, e = t["diesel"], t["ev"]
        col1, col2, col3 = st.columns(3)
        col1.metric("Diesel total / year", fmt_rupiah(d["total_idr_m"]))
        col2.metric("EV total / year", fmt_rupiah(e["total_idr_m"]))
        col3.metric("Operating saving", pct(t["operating_saving_pct"]))
        b1, b2, b3 = st.columns(3)
        b1.metric(
            "Payback",
            f"{t['payback_years']:.1f} yrs"
            if t["payback_years"] is not None
            else "—",
        )
        b2.metric(
            "Break-even",
            f"{t['break_even_km']:,.0f} km"
            if t["break_even_km"] is not None
            else "—",
        )
        b3.metric(
            "Recovered in horizon",
            "Yes" if t["recovered_within_horizon"] else "No",
        )

    st.subheader("Scheme ranking")
    st.dataframe(
        scheme_frame(result.schemes, bundle.schemes["weights"]),
        width="stretch",
        hide_index=True,
    )

    if result.warnings:
        st.warning("\n".join(result.warnings))


if __name__ == "__main__":
    main()
