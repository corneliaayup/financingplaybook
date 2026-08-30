"""Financing Playbook — questionnaire platform + assessment detail.

A Streamlit front-end that turns the pure-Python scoring engine into an
input → scoring → output platform:

* **Questionnaire** — an interactive, config-driven form (every field comes from
  ``config/questionnaire.yaml``). Answers are pre-filled from the bundled example
  so the form is immediately usable; pressing *Calculate* runs the engine and
  renders the assessment.
* **Example / Excel / JSON** — import a finished record directly.

Both flows share ``_assessment_html``, which reproduces the reference
"Assessment Detail" template (``financing_playbook_kota_bandung.html``):
navy sidebar rail, page header, five filter chips, six KPI cards and the
4-column workflow grid of eleven numbered cards. Every scored number in the
live view is computed by ``fpb.engine.score``; only purely advisory copy
falls back to reference values. The mockup mode renders the same template
with the reference example figures.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import NamedTuple

import streamlit as st

from fpb.config import load_config, validate_config
from fpb.engine import score
from fpb.ingest import ReaderError, build_case_input, read_excel_form, read_json_record

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONTEXT = {"consumer_readiness": 57.0, "city_cri": 40.4}

# Reference display values for the case header / context when the loaded record
# carries no form-metadata text (the bundled example is questionnaire-only).
CASE_REF = {
    "id": "FPB-2025-0001",
    "city": "Surabaya",
    "use_case": "Cold Chain Logistics",
    "operation": "Intracity",
    "vehicle": "Medium Duty Truck",
    "date": "20 May 2025",
    "stakeholder": "Logistics / Cold Chain Company",
    "scenario": "Purchase",
    "scope": "Intracity",
    "created_by": "Cornelia Ayu",
    "user_org": "Universitas Katolik Parahyangan",
    "updated": "20 May 2025",
}

# Defaults for the identity / case-info text fields (config ``form_metadata``).
# Prefilled so the dashboard matches the reference design out of the box, while
# remaining fully editable in the questionnaire form.
IDENTITY_DEFAULTS = {
    "form_0_1": "",
    "form_0_2": "Cornelia Ayu",
    "form_0_3": "",
    "form_0_4": "Logistics / Cold Chain Company",
    "form_0_5": "Surabaya",
    "form_0_6": "Cold Chain Logistics",
    "form_0_7": "Intracity",
    "form_0_8": "Medium Duty Truck",
    "form_0_9": "20 May 2025",
}

LIKERT_LABELS = {
    1: "1 — Very Low / Very Risk Averse",
    2: "2 — Low",
    3: "3 — Moderate",
    4: "4 — High",
    5: "5 — Very High / Very Risk Tolerant",
}


class SchemeRow(NamedTuple):
    """Duck-typed scheme entry accepted by the template table/recommendation."""

    scheme_id: int
    name: str
    total: float | None
    rank: int | None
    is_primary: bool


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def _load_bundle():
    bundle = load_config(REPO / "config")
    problems = validate_config(bundle)
    if problems:
        st.error("Configuration is invalid:\n" + "\n".join(problems))
        st.stop()
    return bundle


def _example_raw():
    raw = json.loads((REPO / "tests" / "fixtures" / "workbook_case.json").read_text())
    raw.update(DEFAULT_CONTEXT)
    return raw


def _field_index(questionnaire: dict) -> tuple[dict, set]:
    """Return (alias->slug map, set of all slugs) for resolving raw input keys."""
    alias_to_slug: dict[str, str] = {}
    slugs: set[str] = set()
    for section in questionnaire["sections"]:
        for field in section["fields"]:
            slugs.add(field["slug"])
            alias = (field.get("aliases") or {}).get("form_column_d")
            if alias is not None:
                alias_to_slug[str(alias).strip()] = field["slug"]
    return alias_to_slug, slugs


def _meta_from_raw(raw: dict, questionnaire: dict) -> dict:
    """Extract the ``form_*`` identity/metadata text fields, keyed by slug."""
    alias_to_slug, slugs = _field_index(questionnaire)
    meta: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key).strip()
        slug = alias_to_slug.get(k) or (k if k in slugs else None)
        if slug and slug.startswith("form_") and value not in (None, ""):
            meta[slug] = str(value).strip()
    return meta


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "FP"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def band_text(value: float | None) -> str:
    if value is None:
        return "—"
    if value <= 33:
        return "Low"
    if value <= 66:
        return "Moderate"
    return "High"


def band_text_hyphen(value: float | None) -> str:
    """Friendly band label like the template ('Medium – High')."""
    if value is None:
        return "—"
    if value <= 33:
        return "Low"
    if value <= 50:
        return "Moderate"
    if value <= 66:
        return "Medium – High"
    return "High"


def pct_str(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def metric_val(result, key: str) -> float | None:
    m = result.metrics.get(key)
    if m is None or m.state != "computed":
        return None
    return m.value


def _weighted(record: dict, slugs: list[str], weights: list[float]) -> float | None:
    vals = [record.get(s) for s in slugs]
    if any(v is None for v in vals):
        return None
    return sum(float(v) * w for v, w in zip(vals, weights))


# --------------------------------------------------------------------------- #
# Template component builders (mirrors financing_playbook_kota_bandung.html)
# --------------------------------------------------------------------------- #
def card(
    num_label: str,
    title: str,
    body: str,
    *,
    cls: str = "",
    chip_style: str = "",
    sub: str = "",
) -> str:
    style = f' style="{chip_style}"' if chip_style else ""
    extra = f" {cls}" if cls else ""
    return (
        f'<section class="card{extra}">'
        f'<h3><span class="num"{style}>{num_label}.</span>{esc(title)}{sub}</h3>'
        f"{body}</section>"
    )


def kpi_card(
    title: str, value: float | None, status: str, *, color: str = "", progress: bool = False
) -> str:
    v = "—" if value is None else f"{value:.0f}"
    bar = ""
    if progress and value is not None:
        w = max(0.0, min(100.0, float(value)))
        bar = f'<div class="progress"><i style="width:{w:.0f}%"></i></div>'
    return (
        f'<div class="kpi"><div class="kpi-title">{title}</div>'
        f'<div class="kpi-value {color}">{v} <small>/100</small></div>'
        f'<div class="status">{esc(status)}</div>{bar}</div>'
    )


def line_row(label: str, value: str) -> str:
    return f'<div class="line"><b>{esc(label)}</b><span>{esc(value)}</span></div>'


def star_row(label: str, value: float | None) -> str:
    """A template '.line' row with the 1-5 Likert value as star glyphs."""
    if value is None:
        right = "<span>—</span>"
    else:
        v = max(0, min(5, round(float(value))))
        right = f'<span class="stars">{"★" * v}{"☆" * (5 - v)} &nbsp;{v}</span>'
    return f'<div class="line"><span>{esc(label)}</span>{right}</div>'


def profile_box(
    title: str,
    rows_html: str,
    score_label: str,
    score_value: float | None,
    index_label: str,
    index_value: float | None,
    *,
    risk: bool = False,
) -> str:
    sv = "—" if score_value is None else f"{score_value:.2f} /5"
    iv = "—" if index_value is None else f"{index_value:.0f} /100"
    idx_cls = "index risk" if risk else "index"
    return (
        f'<div class="box"><div class="box-title">{esc(title)}</div>{rows_html}'
        f'<div class="scoreline"><span>{esc(score_label)}</span><span>{sv}</span></div>'
        f'<div class="{idx_cls}"><span>{esc(index_label)}</span><span>{iv}</span></div></div>'
    )


def pillar_rows(pillars: list[tuple[str, float | None]]) -> str:
    out = []
    for name, value in pillars:
        v = 0.0 if value is None else float(value)
        dashes = "━" * max(1, round(v / 20))
        out.append(
            f'<div class="line"><span>{esc(name)}</span>'
            f'<span class="dash">{dashes} {v:.0f}</span></div>'
        )
    return "".join(out)


def tco_chart(diesel: float | None, ev: float | None) -> str:
    if not diesel and not ev:
        return '<div class="chart-empty">TCO inputs unavailable</div>'
    diesel = diesel or 0.0
    ev = ev or 0.0
    top = max(diesel, ev, 1.0)
    dh = diesel / top * 66
    eh = ev / top * 66
    return (
        '<div class="chart">'
        f'<div class="col"><b>{diesel:,.0f}</b>'
        f'<div class="barcol" style="height:{dh:.0f}px"></div>Diesel</div>'
        f'<div class="col ev"><b>{ev:,.0f}</b>'
        f'<div class="barcol" style="height:{eh:.0f}px"></div>EV</div></div>'
    )


def small_table(rows: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(d)}</td><td>{esc(e)}</td></tr>"
        for k, d, e in rows
    )
    return (
        '<table class="small-table"><tr><th>INDICATOR</th><th>DIESEL</th>'
        "<th>EV</th></tr>" + body + "</table>"
    )


def metric_card(title: str, value: float | None) -> str:
    v = "—" if value is None else f"{value:.0f}"
    return f'<div class="metric">{title}<br><strong>{v} <small>/100</small></strong></div>'


def scheme_table(schemes) -> str:
    rows = []
    for s in sorted(schemes, key=lambda x: x.scheme_id):
        cls = ' class="selected"' if s.is_primary else ""
        rank = s.rank if s.rank is not None else "—"
        rows.append(
            f"<tr{cls}><td>{s.scheme_id}. {esc(s.name)}</td>"
            f"<td>{num(s.total)}</td><td>{rank}</td></tr>"
        )
    return (
        "<table><tr><th>SCHEME</th><th>SCORE</th><th>RANK</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def recommend_card(primary, alts: list[tuple[str, str]]) -> str:
    if primary is None:
        body = (
            '<div class="recommend-body"><div class="chart-empty">'
            "No eligible recommendation.</div></div>"
        )
    else:
        w = max(0.0, min(100.0, float(primary.total or 0)))
        alt_html = ""
        if alts:
            lines = "<br>".join(
                f'{esc(t)} <b style="float:right">{esc(s)}</b>' for t, s in alts
            )
            alt_html = f'<div class="alt"><b>ALTERNATIVE SCHEMES</b><br>{lines}</div>'
        body = (
            '<div class="recommend-body">'
            '<div class="primary">🏆 &nbsp; PRIMARY RECOMMENDATION</div>'
            f'<div class="scheme-name">SCHEME {primary.scheme_id}</div>'
            f'<div class="scheme-type">{esc(primary.name).upper()}</div>'
            '<p style="font-size:9px;color:#526176">Best fit for your financing need, '
            "risk preference, and economic profile.</p>"
            '<div class="line"><b>Financing Fit Score</b><span class="fit-score">'
            f"{num(primary.total)} <small>/100</small></span></div>"
            f'<div class="progress"><i style="width:{w:.0f}%"></i></div>'
            f'{alt_html}<div class="button">View Scheme Comparison</div></div>'
        )
    return (
        '<section class="card recommend"><div class="recommend-head">'
        '<span class="num" style="background:#fff;color:#173c6b">9.</span>'
        f"Recommended Scheme</div>{body}</section>"
    )


def struct_line(icon: str, label: str, value: str) -> str:
    return f'<div class="line">{icon} {esc(label)}<b>{esc(value)}</b></div>'


def cond_line(text: str) -> str:
    return f'<div class="line"><span class="check">✓ &nbsp; {esc(text)}</span></div>'


# --------------------------------------------------------------------------- #
# Page assembler — same DOM as the reference HTML template
# --------------------------------------------------------------------------- #
def _assessment_html(d: dict) -> str:
    header = (
        '<div class="header"><div class="page-title">Assessment Detail '
        f'<span class="page-id">{esc(d["id"])}</span></div>'
        '<div class="user"><div class="export">⇩ &nbsp; Export Report</div>'
        f'<div class="avatar">{esc(initials(d["user_name"]))}</div><div>'
        f'<div class="user-name">{esc(d["user_name"])}</div>'
        f'<div class="user-org">{esc(d["user_org"])}</div></div><span>⌄</span></div></div>'
    )
    filters = '<div class="filters">' + "".join(
        f'<div class="filter"><label>{esc(label)}</label>'
        f'<div class="select">{esc(value)} <span>{icon}</span></div></div>'
        for label, value, icon in d["filters"]
    ) + "</div>"
    kpis = '<div class="kpis">' + "".join(kpi_card(**k) for k in d["kpis"]) + "</div>"

    c1 = card("1", "Case Context", "".join(line_row(k, v) for k, v in d["context"]))
    c2 = card(
        "2",
        "Existing Readiness",
        '<div class="mini-readiness">'
        f'<div class="mini"><b>Consumer Readiness</b><strong>{num(d["cons"])} <small>/100</small></strong>'
        f'<span>{esc(d["cons_lvl"])}</span></div>'
        f'<div class="mini"><b>City / Ecosystem CRI</b><strong>{num(d["cri"])} <small>/100</small></strong>'
        f'<span>{esc(d["cri_lvl"])}</span></div></div>'
        '<div class="pillars"><b style="font-size:9px">Key City Readiness Pillars</b>'
        + pillar_rows(d["pillars"])
        + '</div><div class="button">View Full Readiness Detail</div>',
        sub=" <small>(from Platform)</small>",
    )
    c3 = card(
        "3",
        "Financing Profile (Questionnaire Results)",
        '<div class="profile-grid">'
        + profile_box(
            "3A. Financing Need",
            "".join(star_row(l, v) for l, v in d["fn_rows"]),
            "Financing Need Score", d["fn_score"],
            "Financing Need Index", d["fn_index"],
        )
        + profile_box(
            "3B. Risk Profile",
            "".join(star_row(l, v) for l, v in d["rp_rows"]),
            "Risk Profile Score", d["rp_score"],
            "Risk Profile Index", d["rp_index"],
            risk=True,
        )
        + '</div><div class="button">Scale: 1 = Very Low / Very Risk Averse '
        "&nbsp;&nbsp;&nbsp; 3 = Moderate &nbsp;&nbsp;&nbsp; "
        "5 = Very High / Very Risk Tolerant</div>",
        cls="profile",
    )
    c4 = (
        '<section class="card tco"><div class="blue-head">'
        '<span class="num" style="background:white;color:#173c6b">4.</span>'
        "Total Cost of Ownership (TCO) Analysis</div>"
        '<div class="tco-content"><div><div class="subhead">COST COMPARISON (8 YEARS)</div>'
        + d["tco_chart"]
        + f'<div class="button">{esc(d["tco_note"])}</div></div>'
        '<div><div class="subhead">KEY TCO INDICATORS</div>'
        + small_table(d["tco_rows"])
        + f'</div></div><div class="button">{esc(d["cold_note"])}</div></section>'
    )
    c5 = card(
        "5",
        "Project Economic Readiness",
        '<div class="metrics">'
        + "".join(metric_card(t, v) for t, v in d["econ"])
        + f'</div><div class="button">Economic Readiness Level: &nbsp;<b class="green">'
        f'{esc(d["econ_level"])}</b></div>',
    )
    c6 = card(
        "6",
        "Sustainable Finance & Support",
        "".join(
            f'<div class="line"><span>{esc(label)}</span>'
            + (
                f'<b class="check">✓ &nbsp; {esc(value)}</b>'
                if ok
                else f'<b style="color:#b45309">~ &nbsp; {esc(value)}</b>'
            )
            + "</div>"
            for label, value, ok in d["support"]
        )
        + '<div class="button">View Details</div>',
        cls="support",
    )
    c7 = card(
        "7",
        "Financing Supply (Provider Landscape)",
        "".join(
            f'<div class="line"><span>{esc(name)}</span><span>{detail}</span></div>'
            for name, detail in d["supply"]
        )
        + '<div class="button">View Provider List</div>',
        cls="supply",
    )
    c8 = card(
        "8",
        "Scheme Matching Results",
        d["schemes_html"] + '<div class="button">View Detailed Scoring</div>',
        cls="scheme",
    )
    c9 = recommend_card(d["primary"], d["alts"])
    c10 = card(
        "10",
        "Recommended Structure (Summary)",
        '<div class="structure-grid"><div>'
        + "".join(struct_line(i, l, v) for i, l, v in d["structure_left"])
        + "</div><div>"
        + "".join(struct_line(i, l, v) for i, l, v in d["structure_right"])
        + '</div></div><div class="button">View Full Structure</div>',
    )
    c11 = (
        '<section class="card conditions"><h3><span class="num">11.</span>Key Conditions</h3>'
        '<div class="conditions-grid"><div>'
        + "".join(cond_line(c) for c in d["conditions"][:3])
        + '</div><div>'
        + "".join(cond_line(c) for c in d["conditions"][3:])
        + '</div></div><div class="button">View All Conditions</div></section>'
    )
    workflow = '<div class="workflow">' + "".join(
        [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11]
    ) + "</div>"
    return f'<div class="fpb">{header}{filters}{kpis}{workflow}</div>'


# --------------------------------------------------------------------------- #
# Stylesheet — ported from the reference template, scoped under .fpb
# --------------------------------------------------------------------------- #
CSS = """
<style>
:root{
  --navy:#0b1d36;--navy2:#123f79;--blue:#173f72;--green:#23733a;
  --light:#f5f7fb;--border:#dce3ec;--text:#243653;--muted:#66758b;
  --orange:#d78213;--purple:#7658b8;--teal:#267b98;
}
/* ---- Streamlit chrome -------------------------------------------------- */
#MainMenu,footer{visibility:hidden;}
header[data-testid="stHeader"]{background:transparent;}
.block-container{padding:14px 18px 22px;max-width:1600px;}
/* ---- sidebar rail (template look) -------------------------------------- */
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#0c1d35,#0b1a31);}
section[data-testid="stSidebar"],section[data-testid="stSidebar"] *{color:#dbe3ef;}
section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.15);}
.fpb-side .brand{display:flex;align-items:center;gap:11px;padding:0 4px 20px;}
.fpb-side .logo{width:42px;height:42px;border:2px solid #58ad50;border-radius:50%;
  display:grid;place-items:center;color:#67ca5f;font-size:27px;font-weight:300;}
.fpb-side .brand-title{font-size:16px;font-weight:750;letter-spacing:.4px;color:#fff;}
.fpb-side .brand-sub{font-size:10px;color:#c5cfdd;margin-top:5px;}
.fpb-side .menu{display:grid;gap:7px;margin-bottom:14px;}
.fpb-side .menu-item{padding:12px;border-radius:7px;color:#dbe3ef;font-size:14px;}
.fpb-side .menu-item.active{background:linear-gradient(90deg,#15519a,#173e73);
  box-shadow:inset 0 0 0 1px #255b9c;}
.fpb-side .sources{border:1px solid #53627a;border-radius:8px;padding:14px;margin-top:14px;}
.fpb-side .sources-title{font-size:10px;font-weight:700;color:#fff;}
.fpb-side .source{margin-top:14px;color:#dbe2ec;line-height:1.45;}
.fpb-side .source small{color:#b7c2d0;}
.fpb-side .version{font-size:10px;color:#b8c2d0;margin-top:14px;}
/* ---- questionnaire ------------------------------------------------------ */
.q-head{background:#fff;border:1px solid var(--border);border-radius:8px;padding:.8rem 1.1rem;
  margin-bottom:1rem;color:var(--text);}
.q-head h2{margin:0;font-size:1.2rem;color:var(--navy);}
.q-head p{margin:.2rem 0 0;color:var(--muted);font-size:.85rem;}
.q-sec{background:var(--navy);color:#fff;font-weight:700;font-size:.9rem;
  padding:.5rem .9rem;border-radius:8px;margin:1.1rem 0 .5rem;}
.q-req{color:#c23b22;font-weight:700;}
/* ---- assessment detail template ---------------------------------------- */
.fpb{font-family:Inter,"Segoe UI",Arial,sans-serif;font-size:11px;color:var(--text);}
.fpb .header{height:61px;display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--border);margin-bottom:10px;padding:0 5px;}
.fpb .page-title{font-size:18px;font-weight:700;}
.fpb .page-id{font-size:12px;color:#647087;font-weight:500;margin-left:14px;}
.fpb .user{display:flex;align-items:center;gap:10px;}
.fpb .export{padding:8px 14px;border:1px solid var(--border);border-radius:6px;
  background:white;color:#33455d;}
.fpb .avatar{width:29px;height:29px;border-radius:50%;display:grid;place-items:center;
  background:#14273f;color:#fff;font-size:10px;}
.fpb .user-name{font-size:11px;}
.fpb .user-org{font-size:9px;color:#536276;margin-top:3px;}
.fpb .filters{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:12px;}
.fpb .filter label{display:block;font-size:9px;color:#5c6a7d;margin:0 0 5px 4px;}
.fpb .select{height:32px;background:white;border:1px solid var(--border);border-radius:6px;
  padding:0 11px;display:flex;align-items:center;justify-content:space-between;}
.fpb .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-bottom:9px;}
.fpb .kpi{background:#fff;border:1px solid var(--border);border-radius:8px;padding:12px;
  min-height:112px;text-align:center;}
.fpb .kpi-title{font-weight:700;font-size:10px;}
.fpb .kpi-value{font-size:26px;font-weight:750;margin:10px 0 5px;color:#274d78;}
.fpb .kpi-value small{font-size:11px;}
.fpb .orange{color:var(--orange);}
.fpb .purple{color:var(--purple);}
.fpb .teal{color:var(--teal);}
.fpb .green{color:var(--green);}
.fpb .status{font-size:10px;color:#506477;}
.fpb .progress{height:7px;background:#e6eaf0;border-radius:8px;margin-top:13px;overflow:hidden;}
.fpb .progress i{display:block;height:100%;background:var(--green);border-radius:8px;}
.fpb .workflow{display:grid;grid-template-columns:1.05fr 1.45fr 1.35fr 1.2fr;gap:8px;
  align-items:start;}
.fpb .card{background:white;border:1px solid var(--border);border-radius:8px;padding:10px;
  min-width:0;}
.fpb .card h3{font-size:11px;margin:0 0 9px;color:#29415f;}
.fpb .num{display:inline-grid;place-items:center;width:19px;height:19px;background:#173c6b;
  color:white;border-radius:3px;margin-right:5px;font-size:10px;}
.fpb .line{display:flex;justify-content:space-between;gap:8px;padding:6px 0;
  border-bottom:1px solid #edf0f4;color:#526176;}
.fpb .line b{color:#34445c;}
.fpb .mini-readiness{display:grid;grid-template-columns:1fr 1fr;gap:6px;}
.fpb .mini{background:#f8fafc;border:1px solid #e1e6ee;border-radius:6px;padding:8px;}
.fpb .mini strong{font-size:20px;color:#327542;display:block;margin-top:6px;}
.fpb .pillars{margin-top:9px;}
.fpb .pillars .line{font-size:9px;}
.fpb .dash{color:#47884b;letter-spacing:-1px;}
.fpb .profile{grid-column:span 2;}
.fpb .profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.fpb .box{border:1px solid #e0e5ec;border-radius:6px;padding:8px;}
.fpb .box-title{font-size:10px;font-weight:700;margin-bottom:6px;}
.fpb .stars{color:#e89517;letter-spacing:1px;white-space:nowrap;}
.fpb .scoreline{margin-top:8px;padding-top:8px;border-top:1px solid #e8ecf1;display:flex;
  justify-content:space-between;font-weight:700;}
.fpb .index{margin-top:7px;padding:10px;border-radius:6px;
  background:linear-gradient(90deg,#edf6ef,#fff);color:#397047;font-weight:700;display:flex;
  justify-content:space-between;}
.fpb .index.risk{background:linear-gradient(90deg,#fff5e5,#fff);color:#b26e13;}
.fpb .tco{grid-column:span 2;}
.fpb .blue-head{margin:-10px -10px 9px;padding:7px 10px;background:#112f58;color:white;
  border-radius:7px 7px 0 0;font-weight:700;}
.fpb .tco-content{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.fpb .subhead{font-size:9px;font-weight:700;margin-bottom:6px;}
.fpb .chart{height:92px;border-bottom:1px solid #dce2eb;display:flex;align-items:end;
  justify-content:center;gap:34px;padding-bottom:13px;}
.fpb .chart .col{width:48px;text-align:center;font-size:9px;}
.fpb .barcol{height:58px;background:#bcbcbc;margin:4px 0;}
.fpb .ev .barcol{height:66px;background:#2c8037;}
.fpb .small-table{width:100%;border-collapse:collapse;font-size:8px;}
.fpb .small-table td,.fpb .small-table th{padding:4px;border:1px solid #e1e6ed;text-align:left;}
.fpb .chart-empty{color:var(--muted);padding:2rem 0;text-align:center;}
.fpb .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;}
.fpb .metric{padding:7px;background:#f8fafc;border:1px solid #edf0f4;border-radius:5px;
  font-size:8px;}
.fpb .metric strong{display:block;font-size:21px;margin-top:9px;}
.fpb .button{border:1px solid var(--border);border-radius:6px;padding:7px;text-align:center;
  margin-top:8px;font-size:9px;background:#fff;color:#344b68;}
.fpb .support .line,.fpb .supply .line{font-size:9px;}
.fpb .check{color:#28753b;font-weight:700;}
.fpb .scheme table{width:100%;border-collapse:collapse;font-size:8px;}
.fpb .scheme td,.fpb .scheme th{padding:4px;border-bottom:1px solid #edf0f4;text-align:left;}
.fpb .scheme .selected{background:#dff0df;color:#276d35;font-weight:700;}
.fpb .recommend{grid-column:span 1;padding:0;overflow:hidden;}
.fpb .recommend-head{padding:8px 11px;background:linear-gradient(90deg,#e8f0e8,#07532e);
  color:white;font-weight:700;}
.fpb .recommend-body{padding:10px;}
.fpb .primary{font-size:9px;font-weight:700;color:#52667d;}
.fpb .scheme-name{font-size:15px;font-weight:800;color:#326244;margin:8px 0 2px;}
.fpb .scheme-type{font-size:11px;font-weight:700;color:#48705b;}
.fpb .fit-score{font-size:18px;font-weight:750;color:#397b42;}
.fpb .alt{border-top:1px solid #e5e9ef;margin-top:8px;padding-top:8px;line-height:2;font-size:9px;}
.fpb .structure-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px;}
.fpb .structure-grid .line{font-size:9px;display:block;}
.fpb .structure-grid b{display:block;margin-top:2px;}
.fpb .conditions{grid-column:span 2;}
.fpb .conditions-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px;}
.fpb .conditions .line{font-size:9px;}
@media(max-width:1250px){
  .fpb .workflow{grid-template-columns:repeat(2,1fr);}
  .fpb .profile,.fpb .tco,.fpb .conditions{grid-column:span 2;}
  .fpb .kpis{grid-template-columns:repeat(3,1fr);}
}
@media(max-width:800px){
  .fpb .filters,.fpb .kpis,.fpb .workflow,.fpb .profile-grid,.fpb .tco-content,
  .fpb .mini-readiness,.fpb .metrics,.fpb .structure-grid,.fpb .conditions-grid
  {grid-template-columns:1fr;}
  .fpb .profile,.fpb .tco,.fpb .conditions{grid-column:span 1;}
  .fpb .kpis{grid-template-columns:1fr 1fr;}
  .fpb .user-org{display:none;}
}
</style>
"""


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def _sidebar(bundle) -> tuple[object, object, bool]:
    with st.sidebar:
        st.markdown(
            """
            <div class="fpb-side">
              <div class="brand"><div class="logo">ϟ</div><div>
                <div class="brand-title">FINANCING PLAYBOOK</div>
                <div class="brand-sub">EV Financing Recommendation</div>
              </div></div>
              <div class="menu">
                <div class="menu-item active">⌂ &nbsp; Dashboard</div>
                <div class="menu-item">▣ &nbsp; Assessments</div>
                <div class="menu-item">▤ &nbsp; Case Management</div>
                <div class="menu-item">◇ &nbsp; Data Library</div>
                <div class="menu-item">♜ &nbsp; Financing Providers</div>
                <div class="menu-item">▱ &nbsp; Reports</div>
                <div class="menu-item">♧ &nbsp; Scenario Analysis</div>
                <div class="menu-item">⚙ &nbsp; Settings</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Gunakan tab Kuesioner untuk input manual, atau impor jawaban di bawah.")
        load_example = st.button("↻ Load example assessment", use_container_width=True)
        xlsx = st.file_uploader("Import questionnaire (.xlsx)", type=["xlsx"])
        jfile = st.file_uploader("Import record (.json)", type=["json"])
        st.markdown(
            """
            <div class="fpb-side">
              <div class="sources">
                <div class="sources-title">DATA SOURCES</div>
                <div class="source">▣ &nbsp; Consumer Readiness</div>
                <div class="source">⌂ &nbsp; City / Ecosystem CRI</div>
                <div class="source">▣ &nbsp; Open Data<br><small>&nbsp;&nbsp;&nbsp;&nbsp;14 Data Categories</small></div>
              </div>
              <div class="version">Version 1.0.0</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return xlsx, jfile, load_example


# --------------------------------------------------------------------------- #
# Questionnaire form (config-driven)
# --------------------------------------------------------------------------- #
def _render_fields(fields: list[dict], defaults: dict, answers: dict) -> None:
    """Render a list of questionnaire fields into two columns of Streamlit widgets.

    Each question shows its reference number, label, the response guidance from
    the workbook (as a caption), and a widget matched to its type: a 1-5 Likert
    selector, a numeric input with units, a dropdown of the workbook's options,
    or a free-text box.
    """
    cols = st.columns(2)
    for idx, field in enumerate(fields):
        slug = field["slug"]
        label = field.get("label", slug)
        typ = field.get("type")
        qno = field.get("qno")
        guidance = field.get("guidance")
        unit = field.get("unit")
        # Widget labels render markdown, not raw HTML — use the colored-text
        # directive for the required marker (a literal <span> would show up as-is).
        req = " :red[*]" if field.get("required") else ""
        title = f"{qno} · {label}" if qno else label
        d = defaults.get(slug)
        with cols[idx % 2]:
            if typ == "likert_5":
                opts = [1, 2, 3, 4, 5]
                dv = int(d) if d is not None else 3
                val = st.selectbox(
                    f"{title}{req}", opts, index=opts.index(dv),
                    key=f"q_{slug}", format_func=lambda x: LIKERT_LABELS[x],
                )
                answers[slug] = val
            elif typ == "numeric":
                mn = float(field.get("min", 0))
                mx = float(field.get("max", 1_000_000))
                dv = float(d) if d is not None else mn
                step = 100.0 if mx >= 1000 else 1.0
                val = st.number_input(
                    f"{title}{req}", min_value=mn, max_value=mx,
                    value=dv, step=step, key=f"q_{slug}", format="%.0f",
                )
                answers[slug] = val
            elif typ == "choice":
                opts = list(field.get("options", []))
                if field.get("required"):
                    dv = d if d in opts else (opts[0] if opts else None)
                    ii = opts.index(dv) if dv in opts else 0
                    val = st.selectbox(f"{title}{req}", opts, index=ii, key=f"q_{slug}")
                    if val:
                        answers[slug] = val
                else:
                    items = ["(choose one)"] + opts
                    dv = d if d in opts else items[0]
                    ii = items.index(dv)
                    val = st.selectbox(f"{title}{req}", items, index=ii, key=f"q_{slug}")
                    if val and val != "(choose one)":
                        answers[slug] = val
            else:  # text
                val = st.text_input(
                    f"{title}{req}", value=str(d) if d is not None else "",
                    key=f"q_{slug}",
                )
                if val.strip():
                    answers[slug] = val
            hint = guidance or ""
            if unit:
                hint = f"{hint}  ·  _Unit: {unit}_" if hint else f"_Unit: {unit}_"
            if hint:
                st.caption(hint)


def _section_header(title: str) -> None:
    st.markdown(f'<div class="q-sec">{esc(title)}</div>', unsafe_allow_html=True)


def render_questionnaire(bundle) -> tuple[bool, dict]:
    """Render the full config-driven questionnaire and return (submitted, answers)."""
    defaults = _example_raw()
    defaults.update(IDENTITY_DEFAULTS)
    q = bundle.questionnaire

    st.markdown(
        f"""
        <div class="q-head">
          <h2>📝 Financing Feasibility Questionnaire</h2>
          <p>{esc(q.get('purpose', ''))} Answer every section, then press
          <b>Calculate Assessment</b> to run the scoring engine and produce the
          financing recommendation. Fields marked
          <span class="q-req">*</span> are required for scoring.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("📖 Petunjuk Pengisian (Respondent Instructions)", expanded=False):
        for ins in q.get("instructions", []):
            st.markdown(f"**{esc(ins.get('title', ''))}** — {esc(ins.get('text', ''))}")

    answers: dict = {}
    with st.form("fpb_questionnaire"):
        for section in q["sections"]:
            _section_header(section["title"])
            if section.get("hint"):
                st.caption(f"ℹ️ {section['hint']}")
            _render_fields(section["fields"], defaults, answers)
        submitted = st.form_submit_button("🧮 Calculate Assessment", type="primary")
    return submitted, answers


# --------------------------------------------------------------------------- #
# Assessment detail (shared by questionnaire + import flows)
# --------------------------------------------------------------------------- #
def render_assessment_detail(case, result, bundle, meta: dict | None = None) -> None:
    meta = meta or {}

    def _m(slug: str, fallback: str) -> str:
        value = meta.get(slug)
        return value if value else fallback

    who = _m("form_0_2", CASE_REF["created_by"])
    org = _m("form_0_3", CASE_REF["user_org"])
    city = _m("form_0_5", CASE_REF["city"])
    use_case = _m("form_0_6", CASE_REF["use_case"])
    operation = _m("form_0_7", CASE_REF["operation"])
    vehicle = _m("form_0_8", CASE_REF["vehicle"])
    date = _m("form_0_9", CASE_REF["date"])
    stakeholder = _m("form_0_4", CASE_REF["stakeholder"])

    def _meta_num(slug: str, fallback: float) -> float:
        try:
            return float(meta.get(slug, fallback))
        except (TypeError, ValueError):
            return fallback

    if case.issues:
        st.warning(
            f"{len(case.issues)} validation issue(s) — invalid values were excluded, "
            "so some panels may be incomplete."
        )

    rec = case.record
    ctx = case.context
    tco = result.tco

    # ---- KPI indices ----------------------------------------------------- #
    fn = metric_val(result, "financing_need_index")
    rp = metric_val(result, "risk_profile_index")
    tcc = metric_val(result, "tco_competitiveness")
    ib = metric_val(result, "investment_burden")
    er = metric_val(result, "economic_readiness")
    overall = result.overall.value if result.overall.state == "computed" else None
    ma = metric_val(result, "market_access")

    # ---- financing profile (panel 3) ------------------------------------- #
    fn_fields = [
        ("External Financing Need", "fn_external_need"),
        ("Cash-flow / Budget Constraint", "fn_cashflow_constraint"),
        ("Payment Preference", "fn_payment_preference"),
        ("External Support Requirement", "fn_support_requirement"),
    ]
    rp_fields = [
        ("Ownership Preference", "rp_ownership"),
        ("Technology Risk Tolerance", "rp_technology"),
        ("Battery Risk Tolerance", "rp_battery"),
        ("Residual Value Risk Tolerance", "rp_residual"),
        ("Maintenance Risk Tolerance", "rp_maintenance"),
        ("Performance / Downtime Risk Tolerance", "rp_downtime"),
    ]
    fn_w = bundle.scoring["financing_need"]["weights"]
    fn_score = _weighted(rec, [s for _, s in fn_fields], fn_w)
    rp_own = rec.get("rp_ownership")
    rp_tols = [rec.get(s) for _, s in rp_fields[1:]]
    rp_tols = [t for t in rp_tols if t is not None]
    rp_score = None
    if rp_own is not None and rp_tols:
        rp_score = 0.5 * float(rp_own) + 0.5 * (sum(rp_tols) / len(rp_tols))

    # ---- TCO (panel 4) ----------------------------------------------------- #
    if tco.get("state") == "insufficient_inputs":
        tco_chart_html = (
            '<div class="chart-empty">TCO inputs incomplete — missing: '
            + esc(", ".join(tco.get("missing", []))) + "</div>"
        )
        tco_note = "TCO inputs incomplete; comparison unavailable."
    else:
        d_total = tco["diesel"]["total_idr_m"]
        e_total = tco["ev"]["total_idr_m"]
        diff = None
        if d_total:
            diff = (e_total - d_total) / d_total * 100
        tco_chart_html = tco_chart(d_total, e_total)
        tco_note = (
            f"EV TCO is {abs(diff):.1f}% "
            + ("higher" if diff and diff > 0 else "lower")
            + " than Diesel in base case scenario."
            if diff is not None
            else "EV total TCO: " + num(e_total) + " IDR M (diesel baseline unavailable)."
        )
    d, e = tco.get("diesel", {}), tco.get("ev", {})
    tco_rows = [
        ("Cost per km (IDR)", num(d.get("cost_per_km")), num(e.get("cost_per_km"))),
        ("Annual Operating Cost", num(d.get("annual_opex_idr_m"), 1),
         num(e.get("annual_opex_idr_m"), 1)),
        ("Operating Cost Saving", "–", pct_str(tco.get("operating_saving_pct"))),
        ("Payback Period (Year)", "–", num(tco.get("payback_years"), 1)),
        ("Break-even Mileage (km)", "–", num(tco.get("break_even_km"))),
    ]

    # ---- sustainable finance (panel 6) ------------------------------------ #
    def support_ok(value: str) -> bool:
        return value not in {"", "No", "None", "Not eligible", "Unknown", "(choose one)"}

    sf_rows = [
        ("Green Taxonomy Alignment", _m("form_7_1", "Not provided")),
        ("Green Financing Availability", _m("form_7_2", "Not provided")),
        ("Government Incentive", _m("form_7_3", "Not provided")),
        ("Other Fiscal Support", _m("form_7_5", "Not provided")),
        ("Carbon / Environmental Benefit", _m("form_7_6", "Not provided")),
    ]
    support = [(label, value, support_ok(value)) for label, value in sf_rows]

    # ---- financing supply (panel 7) --------------------------------------- #
    supply = [
        ("Green Loan", esc(str(rec.get("fs_green_loan", "—")))),
        ("Lease / Rent", esc(str(rec.get("fs_lease_rent", "—")))),
        ("BaaS", esc(str(rec.get("fs_baas", "—")))),
        ("Project Finance", esc(str(rec.get("fs_project_finance", "—")))),
        ("Blended Finance", esc(str(rec.get("fs_blended_finance", "—")))),
        ("Export Credit / Agency Support", "Low"),
    ]

    # ---- recommendation (panel 9) ------------------------------------------ #
    primary = next((s for s in result.schemes if s.is_primary), None)
    alts = [
        (f"{s.rank}. {s.name}", f"{num(s.total)} /100")
        for s in [x for x in result.schemes if not x.is_primary and x.rank][:3]
    ]

    struct_name = primary.name if primary else "Operating Lease"
    d = {
        "id": CASE_REF["id"],
        "user_name": who,
        "user_org": org,
        "filters": [
            ("City / Region", city, "⌄"),
            ("Use Case", use_case, "⌄"),
            ("Operation", operation, "⌄"),
            ("Vehicle Type", vehicle, "⌄"),
            ("Assessment Date", date, "▣"),
        ],
        "kpis": [
            {"title": "🪙 &nbsp; Financing Need Index", "value": fn,
             "status": band_text_hyphen(fn), "color": "green"},
            {"title": "🛡 &nbsp; Risk Profile Index", "value": rp,
             "status": band_text_hyphen(rp), "color": "orange"},
            {"title": "▥ &nbsp; TCO Competitiveness", "value": tcc,
             "status": "Below Parity" if (tcc is not None and tcc < 100) else "At Parity"},
            {"title": "♟ &nbsp; Investment Burden", "value": ib,
             "status": "High Burden" if (ib is not None and ib < 50) else "Moderate Burden",
             "color": "purple"},
            {"title": "◉ &nbsp; Economic Readiness", "value": er,
             "status": band_text(er), "color": "teal"},
            {"title": "Overall Financing Fit Score", "value": overall,
             "status": "Good Fit" if (overall is not None and overall >= 67)
             else ("Fair Fit" if overall is not None and overall >= 34 else "Weak Fit"),
             "color": "green", "progress": True},
        ],
        "context": [
            ("Stakeholder Type", stakeholder),
            ("Annual Mileage", f"{num(rec.get('tco_annual_km'))} km"),
            ("Purchase Scenario", CASE_REF["scenario"]),
            ("Assessment Scope", operation),
            ("Created By", who),
            ("Last Updated", date),
        ],
        "cons": ctx.get("consumer_readiness"),
        "cons_lvl": band_text_hyphen(ctx.get("consumer_readiness")),
        "cri": ctx.get("city_cri"),
        "cri_lvl": band_text(ctx.get("city_cri")),
        "pillars": [
            ("Charging Infrastructure", _meta_num("form_1_4", 70)),
            ("Policy & Incentive", _meta_num("form_1_5", 75)),
            ("Economic Attractiveness", _meta_num("form_1_6", 72)),
            ("Enabling Environment", _meta_num("form_1_7", 68)),
        ],
        "fn_rows": [(l, rec.get(s)) for l, s in fn_fields],
        "fn_score": fn_score,
        "fn_index": fn,
        "rp_rows": [(l, rec.get(s)) for l, s in rp_fields],
        "rp_score": rp_score,
        "rp_index": rp,
        "tco_chart": tco_chart_html,
        "tco_note": tco_note,
        "tco_rows": tco_rows,
        "cold_note": "Cold Chain Add-on: Refrigeration energy and equipment cost "
                     "included in TCO.",
        "econ": [
            ("TCO Competitiveness", tcc),
            ("Investment Burden", ib),
            ("Financing Access", ma),
            ("Economic Readiness", er),
        ],
        "econ_level": band_text(er),
        "support": support,
        "supply": supply,
        "schemes_html": scheme_table(result.schemes),
        "primary": primary,
        "alts": alts,
        "structure_left": [
            ("▣", "Financing Structure", struct_name),
            ("▦", "Tenor", "5 Years"),
            ("▧", "Upfront Payment", "10% of Vehicle Price"),
            ("♧", "Monthly Payment (Est.)", "IDR 35–38 Million"),
        ],
        "structure_right": [
            ("♧", "Risk Allocation (Key)",
             "Provider: Battery, Residual Value, Maintenance, Downtime"),
            ("◎", "Charging Arrangement",
             "Provider owns & operates DC fast charging station"),
        ],
        "conditions": [
            "Availability of operating lease provider in Indonesia",
            "Clear SLA for uptime and maintenance",
            "Charging infrastructure readiness at depot",
            "Execution of government incentive application",
            "Credit assessment & documentation completion",
        ],
    }
    st.markdown(_assessment_html(d), unsafe_allow_html=True)

    if result.warnings:
        st.caption("⚠ " + " · ".join(result.warnings))


# --------------------------------------------------------------------------- #
# Mockup (reference example figures from the template)
# --------------------------------------------------------------------------- #
def render_dashboard_mockup() -> None:
    """Render the reference template with the example figures it ships with.

    This is intentionally separate from the scoring renderer so the dashboard
    design can be approved without treating the sample figures as calculated
    results. The "Hasil kuesioner terakhir" mode continues to use the real engine.
    """
    st.caption("Mode mockup — seluruh angka di bawah adalah contoh sementara, bukan hasil perhitungan kuesioner.")
    schemes = [
        SchemeRow(1, "Ownership (Conventional Loan)", 60, 5, False),
        SchemeRow(2, "Green Loan (w/ Partial Guarantee)", 76, 2, False),
        SchemeRow(3, "Lease / Rent (Operating Lease)", 84, 1, True),
        SchemeRow(4, "BaaS (Battery-as-a-Service)", 73, 3, False),
        SchemeRow(5, "Project Finance", 51, 6, False),
        SchemeRow(6, "BaaS (Finance-Service)", 72, 4, False),
        SchemeRow(7, "Blended Finance", 62, 7, False),
    ]
    d = {
        "id": "FPB-2025-0001",
        "user_name": "Cornelia Ayu",
        "user_org": "Universitas Katolik Parahyangan",
        "filters": [
            ("City / Region", "Kota Bandung", "⌄"),
            ("Use Case", "Cold Chain", "⌄"),
            ("Operation", "Intracity", "⌄"),
            ("Vehicle Type", "Medium Duty Truck (8 Ton)", "⌄"),
            ("Assessment Date", "20 May 2025", "▣"),
        ],
        "kpis": [
            {"title": "🪙 &nbsp; Financing Need Index", "value": 63,
             "status": "Medium – High", "color": "green"},
            {"title": "🛡 &nbsp; Risk Profile Index", "value": 30,
             "status": "Moderate – High", "color": "orange"},
            {"title": "▥ &nbsp; TCO Competitiveness", "value": 42,
             "status": "Below Parity"},
            {"title": "♟ &nbsp; Investment Burden", "value": 34,
             "status": "High Burden", "color": "purple"},
            {"title": "◉ &nbsp; Economic Readiness", "value": 46,
             "status": "Moderate", "color": "teal"},
            {"title": "Overall Financing Fit Score", "value": 78,
             "status": "Good Fit", "color": "green", "progress": True},
        ],
        "context": [
            ("Stakeholder Type", "Logistics Company"),
            ("Annual Mileage", "36,000 km"),
            ("Purchase Scenario", "Purchase"),
            ("Assessment Scope", "Intracity"),
            ("Created By", "Cornelia Ayu"),
            ("Last Updated", "20 May 2025"),
        ],
        "cons": 68,
        "cons_lvl": "Medium – High",
        "cri": 72,
        "cri_lvl": "High",
        "pillars": [
            ("Charging Infrastructure", 70),
            ("Policy & Incentive", 75),
            ("Economic Attractiveness", 72),
            ("Energy Environment", 74),
            ("Enabling Environment", 68),
        ],
        "fn_rows": [
            ("External Financing Need", 4),
            ("Cash-flow / Budget Constraint", 4),
            ("Payment Preference", 3),
            ("External Support Requirement", 3),
        ],
        "fn_score": 3.5,
        "fn_index": 63,
        "rp_rows": [
            ("Ownership Preference", 2),
            ("Technology Risk Tolerance", 2),
            ("Battery Risk Tolerance", 2),
            ("Residual Value Risk Tolerance", 2),
            ("Maintenance Risk Tolerance", 3),
        ],
        "rp_score": 2.2,
        "rp_index": 30,
        "tco_chart": tco_chart(1536, 1589),
        "tco_note": "EV TCO is 3.4% higher than Diesel in base case scenario.",
        "tco_rows": [
            ("Cost per km (IDR)", "5,334", "5,518"),
            ("Annual Operating Cost", "218.2", "92.5"),
            ("Operating Cost Saving", "–", "57.8%"),
            ("Payback Period (Year)", "–", "9.2"),
            ("Annual Mileage (km)", "–", "31,273"),
        ],
        "cold_note": "Cold Chain Add-on: Refrigeration energy and equipment cost "
                     "included in TCO.",
        "econ": [
            ("TCO Competitiveness", 42),
            ("Investment Burden", 34),
            ("Financing Access", 72),
            ("Economic Readiness", 46),
        ],
        "econ_level": "Moderate",
        "support": [
            ("Green Taxonomy Alignment", "Eligible", True),
            ("Green Financing Availability", "High", True),
            ("Government Incentive", "Available", True),
            ("Other Fiscal Support", "Partial", True),
            ("Carbon / Environmental Benefit", "High", True),
        ],
        "supply": [
            ("Green Loan", "High &nbsp; 3–7 Years"),
            ("Lease / Rent", "High &nbsp; Competitive"),
            ("BaaS", "Medium &nbsp; Medium"),
            ("Project Finance", "Low &nbsp; Increasing"),
            ("Blended Finance", "Medium &nbsp; Green Incentive"),
            ("Export Credit / Agency Support", "Low &nbsp; Preferential"),
        ],
        "schemes_html": scheme_table(schemes),
        "primary": schemes[2],
        "alts": [
            ("2. Green Loan (w/ Partial Guarantee)", "76 /100"),
            ("4. BaaS (Battery-as-a-Service)", "73 /100"),
            ("7. Blended Finance", "62 /100"),
        ],
        "structure_left": [
            ("▣", "Financing Structure", "Operating Lease"),
            ("▦", "Tenor", "5 Years"),
            ("▧", "Upfront Payment", "10% of Vehicle Price"),
            ("♧", "Monthly Payment (Est.)", "IDR 35–38 Million"),
        ],
        "structure_right": [
            ("♧", "Risk Allocation (Key)",
             "Provider: Battery, Residual Value, Maintenance, Downtime"),
            ("◎", "Charging Arrangement",
             "Provider owns & operates DC fast charging station"),
        ],
        "conditions": [
            "Availability of operating lease provider in Indonesia",
            "Clear SLA for uptime and maintenance",
            "Charging infrastructure readiness at depot",
            "Execution of government incentive application",
            "Credit assessment & documentation completion",
        ],
    }
    st.markdown(_assessment_html(d), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(
        page_title="Financing Playbook",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    bundle = _load_bundle()
    xlsx, jfile, load_example = _sidebar(bundle)

    def store_assessment(raw: dict, source: str) -> None:
        """Score a raw record and retain its output for the Dashboard tab."""
        case = build_case_input(raw, bundle.questionnaire, source)
        st.session_state["assessment"] = {
            "case": case,
            "result": score(case.record, bundle, case.context),
            "meta": _meta_from_raw(raw, bundle.questionnaire),
            "source": source,
        }

    # Keep a visible dashboard on first launch, then always replace it with the
    # latest questionnaire submission or imported record.
    if "assessment" not in st.session_state or load_example:
        store_assessment(_example_raw(), "example: workbook_case.json")

    try:
        if xlsx is not None:
            store_assessment(read_excel_form(xlsx), f"excel: {xlsx.name}")
        elif jfile is not None:
            store_assessment(
                read_json_record(jfile.getvalue().decode("utf-8")), f"json: {jfile.name}"
            )
    except ReaderError as exc:
        st.error(str(exc))

    questionnaire_tab, dashboard_tab = st.tabs(["📝 Kuesioner", "📊 Dashboard Hasil"])

    with questionnaire_tab:
        submitted, answers = render_questionnaire(bundle)
        if submitted:
            try:
                store_assessment(answers, "questionnaire")
            except ReaderError as exc:
                st.error(str(exc))
            else:
                st.success(
                    "Perhitungan selesai. Buka tab **📊 Dashboard Hasil** untuk melihat "
                    "visualisasi, ranking skema, dan rekomendasi."
                )
        else:
            st.info("Isi kuesioner lalu tekan **Calculate Assessment**. Hasilnya muncul di tab Dashboard Hasil.")

    with dashboard_tab:
        display_mode = st.radio(
            "Tampilan dashboard",
            ["Mockup (angka contoh)", "Hasil kuesioner terakhir"],
            horizontal=True,
        )
        if display_mode == "Mockup (angka contoh)":
            render_dashboard_mockup()
        else:
            current = st.session_state.get("assessment")
            if current is None:
                st.info("Belum ada hasil. Isi dan hitung Kuesioner terlebih dahulu.")
            else:
                st.caption(f"Menampilkan hasil dari: **{current['source']}**")
                render_assessment_detail(
                    current["case"], current["result"], bundle, current["meta"]
                )


if __name__ == "__main__":
    main()
