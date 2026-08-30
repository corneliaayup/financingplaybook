"""Financing Playbook — questionnaire platform + assessment detail.

A Streamlit front-end that turns the pure-Python scoring engine into an
input → scoring → output platform:

* **Questionnaire** — an interactive, config-driven form (every field comes from
  ``config/questionnaire.yaml``). Answers are pre-filled from the bundled example
  so the form is immediately usable; pressing *Calculate* runs the engine and
  renders the assessment.
* **Example / Excel / JSON** — import a finished record directly.

Both flows share ``render_assessment_detail``, which reproduces the reference
"Assessment Detail" design (navy rail, index cards, panels 1–11). Every scored
number is computed by ``fpb.engine.score``; only purely decorative elements
(sparklines, advisory copy) fall back to reference values.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

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

SOURCES = ["Questionnaire", "Example case", "Excel form", "JSON record"]


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
    """Friendly band label like the mockup ('Medium - High')."""
    if value is None:
        return "—"
    if value <= 33:
        return "Low"
    if value <= 50:
        return "Moderate"
    if value <= 66:
        return "Medium - High"
    return "High"


def stars(value: float | None, filled_color: str = "#f59e0b") -> str:
    """Render a 1-5 Likert value as five star glyphs."""
    if value is None:
        return '<span class="stars">—</span>'
    v = max(0.0, min(5.0, float(value)))
    out = []
    for i in range(1, 6):
        cls = "star-on" if i <= round(v) else "star-off"
        out.append(f'<span class="{cls}">★</span>')
    return '<span class="stars">' + "".join(out) + f'</span><span class="star-val">{v:g}</span>'


def progress_bar(pct_value: float | None, color: str) -> str:
    if pct_value is None:
        pct_value = 0.0
    w = max(0.0, min(100.0, pct_value))
    return (
        f'<div class="pbar"><div class="pbar-fill" '
        f'style="width:{w:.0f}%;background:{color}"></div></div>'
    )


def metric_val(result, key: str) -> float | None:
    m = result.metrics.get(key)
    if m is None or m.state != "computed":
        return None
    return m.value


# --------------------------------------------------------------------------- #
# HTML component builders
# --------------------------------------------------------------------------- #
def index_card(
    *, label: str, value: float | None, descriptor: str, icon: str,
    accent: str, big: bool = False,
) -> str:
    cls = "idx-card idx-card--hero" if big else "idx-card"
    v = "—" if value is None else f"{value:.0f}"
    return f"""
    <div class="{cls}" style="--accent:{accent}">
      <div class="idx-icon">{icon}</div>
      <div class="idx-body">
        <div class="idx-label">{esc(label)}</div>
        <div class="idx-value">{v}<span class="idx-denom"> /100</span></div>
        <div class="idx-desc" style="color:{accent}">{esc(descriptor)}</div>
        {progress_bar(value, accent) if big else ""}
      </div>
    </div>"""


def panel(title: str, body: str, *, tone: str = "navy", num: str | None = None) -> str:
    head = f"{num}. {title}" if num else title
    return f"""
    <section class="panel panel--{tone}">
      <div class="panel-head"><span>{esc(head)}</span></div>
      <div class="panel-body">{body}</div>
    </section>"""


def kv_row(icon: str, label: str, value: str) -> str:
    return (
        f'<div class="kv"><span class="kv-ic">{icon}</span>'
        f'<span class="kv-k">{esc(label)}</span>'
        f'<span class="kv-v">{esc(value)}</span></div>'
    )


def likert_row(label: str, value: float | None) -> str:
    return (
        f'<div class="lk"><span class="lk-k">{esc(label)}</span>'
        f'<span class="lk-s">{stars(value)}</span></div>'
    )


def bar_chart(diesel: float | None, ev: float | None) -> str:
    if not diesel and not ev:
        return '<div class="chart-empty">TCO inputs unavailable</div>'
    diesel = diesel or 0.0
    ev = ev or 0.0
    top = max(diesel, ev, 1.0)
    # scale to a 200px plot area
    dh = diesel / top * 180
    eh = ev / top * 180
    return f"""
    <div class="chart">
      <div class="chart-grid">
        <span>2,000</span><span>1,500</span><span>1,000</span><span>500</span><span>0</span>
      </div>
      <div class="chart-bars">
        <div class="bar-col">
          <div class="bar-val">{diesel:,.0f}</div>
          <div class="bar bar--diesel" style="height:{dh:.0f}px"></div>
          <div class="bar-x">Diesel</div>
        </div>
        <div class="bar-col">
          <div class="bar-val">{ev:,.0f}</div>
          <div class="bar bar--ev" style="height:{eh:.0f}px"></div>
          <div class="bar-x">EV</div>
        </div>
      </div>
    </div>"""


def tco_indicator_rows(tco: dict) -> str:
    d, e = tco.get("diesel", {}), tco.get("ev", {})
    rows = [
        ("Cost per km (IDR)", num(d.get("cost_per_km")), num(e.get("cost_per_km"))),
        (
            "Annual Operating Cost (IDR M)",
            num(d.get("annual_opex_idr_m"), 1),
            num(e.get("annual_opex_idr_m"), 1),
        ),
        (
            "Operating Cost Saving",
            "—",
            pct_str(tco.get("operating_saving_pct")),
        ),
        ("Payback Period (Year)", "—", num(tco.get("payback_years"), 1)),
        ("Break-even Mileage (km)", "—", num(tco.get("break_even_km"))),
    ]
    body = "".join(
        f"<tr><td>{esc(k)}</td><td class='num'>{esc(dv)}</td>"
        f"<td class='num ev'>{esc(ev)}</td></tr>"
        for k, dv, ev in rows
    )
    return (
        "<table class='tbl'><thead><tr><th>Indicator</th>"
        "<th class='num'>Diesel</th><th class='num'>EV</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def pct_str(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def scheme_table(schemes, weights: dict) -> str:
    dims = ["need", "risk", "tco", "operational", "payment", "support"]
    head = "".join(
        f"<th class='num'>{d.title()}<br><span class='sub'>{int(weights[d]*100)}%</span></th>"
        for d in dims
    )
    rows = []
    for s in schemes:
        cells = "".join(
            f"<td class='num'>{num(s.fits.get(d))}</td>" for d in dims
        )
        total_txt = num(s.total)
        rank_txt = str(s.rank) if s.rank else "—"
        cls = "row-primary" if s.is_primary else ""
        name = f"{s.scheme_id}. {s.name}"
        rows.append(
            f"<tr class='{cls}'><td class='sc-name'>{esc(name)}</td>{cells}"
            f"<td class='num total'>{total_txt}</td>"
            f"<td class='num rank'>{rank_txt}</td></tr>"
        )
    return (
        f"<table class='tbl tbl--schemes'><thead><tr><th>Scheme</th>{head}"
        f"<th class='num'>Total</th><th class='num'>Rank</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def sparkline() -> str:
    return (
        "<svg class='spark' viewBox='0 0 100 28' preserveAspectRatio='none'>"
        "<polyline fill='none' stroke='#16a34a' stroke-width='2' "
        "points='0,22 12,18 24,20 36,12 48,14 60,8 72,11 84,5 100,7'/></svg>"
    )


def render_dashboard_mockup() -> None:
    """Render a presentation mockup with temporary example figures.

    This is intentionally separate from the scoring renderer so the dashboard
    design can be approved without treating the sample figures as calculated
    results. The "Hasil kuesioner terakhir" mode continues to use the real engine.
    """
    st.caption("Mode mockup — seluruh angka di bawah adalah contoh sementara, bukan hasil perhitungan kuesioner.")
    st.markdown(
        """
        <div class="fpb-head">
          <div style="display:flex;align-items:baseline;"><h2>Assessment Detail</h2><span class="code">FPB-2025-0001</span></div>
          <div class="right"><span class="btn-export">⬇ Export Report</span>
            <div class="user"><div class="av">CA</div><div><b style="font-size:.85rem;">Cornelia Ayu</b></div></div>
          </div>
        </div>
        <div class="filters">
          <div class="field"><label>City / Region</label><div class="sel">Surabaya</div></div>
          <div class="field"><label>Use Case</label><div class="sel">Cold Chain Logistics</div></div>
          <div class="field"><label>Operation</label><div class="sel">Intracity</div></div>
          <div class="field"><label>Vehicle Type</label><div class="sel">Medium Duty Truck</div></div>
          <div class="field"><label>Assessment Date</label><div class="sel">20 May 2025 📅</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cards = "".join([
        index_card(label="Financing Need Index", value=63, descriptor="Medium - High", icon="💰", accent="var(--green)"),
        index_card(label="Risk Profile Index", value=30, descriptor="Moderate - High", icon="🛡️", accent="var(--amber)"),
        index_card(label="TCO Competitiveness", value=42, descriptor="Below Parity", icon="📊", accent="var(--blue)"),
        index_card(label="Investment Burden", value=34, descriptor="High Burden", icon="💵", accent="var(--purple)"),
        index_card(label="Economic Readiness", value=46, descriptor="Moderate", icon="🎯", accent="var(--teal)"),
        index_card(label="Overall Financing Fit Score", value=78, descriptor="Good Fit", icon="🏆", accent="var(--green)", big=True),
    ])
    st.markdown(f'<div class="idx-row">{cards}</div>', unsafe_allow_html=True)

    p1 = panel("Case Context", "".join([
        kv_row("🏢", "Stakeholder Type", "Logistics / Cold Chain Company"),
        kv_row("🛣️", "Annual Mileage", "36,000 km"),
        kv_row("🛒", "Purchase Scenario", "Purchase"),
        kv_row("📍", "Assessment Scope", "Intracity"),
        kv_row("👤", "Created By", "Cornelia Ayu"),
        kv_row("🕑", "Last Updated", "20 May 2025"),
    ]), num="1")
    p3 = panel("Financing Profile (Questionnaire Results)", """
      <div class="tco-grid"><div><h4>3A. Financing Need</h4>
        <div class="lk"><span class="lk-k">External Financing Need</span><span class="lk-s">★★★★<span class="star-off">★</span><b>4</b></span></div>
        <div class="lk"><span class="lk-k">Cash-flow / Budget Constraint</span><span class="lk-s">★★★★<span class="star-off">★</span><b>4</b></span></div>
        <div class="lk"><span class="lk-k">Payment Preference</span><span class="lk-s">★★★<span class="star-off">★★</span><b>3</b></span></div>
        <div class="lk"><span class="lk-k">External Support Requirement</span><span class="lk-s">★★★<span class="star-off">★★</span><b>3</b></span></div>
        <div class="idx-badge green"><span>Financing Need Index</span><span class="n">63 <small>/100</small></span></div></div>
        <div><h4>3B. Risk Profile</h4>
        <div class="lk"><span class="lk-k">Ownership Preference</span><span class="lk-s">★★<span class="star-off">★★★</span><b>2</b></span></div>
        <div class="lk"><span class="lk-k">Technology Risk Tolerance</span><span class="lk-s">★★<span class="star-off">★★★</span><b>2</b></span></div>
        <div class="lk"><span class="lk-k">Battery Risk Tolerance</span><span class="lk-s">★★<span class="star-off">★★★</span><b>2</b></span></div>
        <div class="lk"><span class="lk-k">Residual Value Risk Tolerance</span><span class="lk-s">★★<span class="star-off">★★★</span><b>2</b></span></div>
        <div class="idx-badge amber"><span>Risk Profile Index</span><span class="n">30 <small>/100</small></span></div></div></div>
        <div class="scale-note">Scale: 1 = Very Low / Very Risk Averse &nbsp; 3 = Moderate &nbsp; 5 = Very High / Very Risk Tolerant</div>
    """, num="3")
    p4 = panel("Total Cost of Ownership (TCO) Analysis", f"""
      <div class="tco-grid"><div><h4>Cost Comparison (8 Years)</h4>{bar_chart(1536, 1589)}
      <div class="callout">EV TCO is 3.4% higher than Diesel in the base case scenario.</div></div>
      <div><h4>Key TCO Indicators</h4><table class="tbl"><thead><tr><th>Indicator</th><th class="num">Diesel</th><th class="num">EV</th></tr></thead><tbody>
      <tr><td>Cost per km (IDR)</td><td class="num">5,334</td><td class="num ev">5,518</td></tr>
      <tr><td>Annual Operating Cost (IDR M)</td><td class="num">218.2</td><td class="num ev">92.5</td></tr>
      <tr><td>Operating Cost Saving</td><td class="num">—</td><td class="num ev">57.8%</td></tr>
      <tr><td>Payback Period (Year)</td><td class="num">—</td><td class="num ev">9.2</td></tr>
      <tr><td>Break-even Mileage (km)</td><td class="num">—</td><td class="num ev">331,273</td></tr>
      </tbody></table></div></div>
    """, num="4")
    p9 = panel("Recommended Scheme", """
      <div class="rec-hero"><div class="tag">PRIMARY RECOMMENDATION</div><div class="trophy">🏆</div>
      <div class="scheme">SCHEME 3<br>LEASE / RENT</div><div class="sub">(Operating Lease)</div>
      <div class="note">Best fit for financing need, risk preference, and economic profile.</div>
      <div class="rec-score"><span class="l">Financing Fit Score</span><span class="v">84 <small>/100</small></span></div><div class="pbar"><div class="pbar-fill" style="width:84%;background:var(--green)"></div></div></div>
      <div style="margin-top:.8rem"><h4 style="color:var(--ink)">Alternative Schemes</h4>
      <div class="alt-row"><span>2. Green Loan (w/ Partial Guarantee)</span><span class="v">76 /100</span></div>
      <div class="alt-row"><span>4. Battery-as-a-Service</span><span class="v">73 /100</span></div>
      <div class="alt-row"><span>7. Blended Finance</span><span class="v">62 /100</span></div></div>
    """, num="9", tone="green")
    p8 = panel("Scheme Matching Results", """
      <table class="tbl tbl--schemes"><thead><tr><th>Scheme</th><th class="num">Need</th><th class="num">Risk</th><th class="num">TCO</th><th class="num">Total</th><th class="num">Rank</th></tr></thead><tbody>
      <tr><td>1. Conventional Ownership</td><td class="num">60</td><td class="num">45</td><td class="num">45</td><td class="num total">60</td><td class="num">5</td></tr>
      <tr><td>2. Green Loan</td><td class="num">70</td><td class="num">65</td><td class="num">50</td><td class="num total">76</td><td class="num">2</td></tr>
      <tr class="row-primary"><td>3. Lease / Rent (Operating Lease)</td><td class="num">80</td><td class="num">85</td><td class="num">55</td><td class="num total">84</td><td class="num rank">1</td></tr>
      <tr><td>4. BaaS</td><td class="num">75</td><td class="num">80</td><td class="num">55</td><td class="num total">73</td><td class="num">3</td></tr>
      </tbody></table>
    """, num="8")
    # Panel 2: Existing Readiness (neutral labels, example figures)
    pillars = [("Charging Infrastructure", 70), ("Policy & Incentive", 75),
               ("Aftersales Service", 65), ("Economic Attractiveness", 72),
               ("Energy Environment", 74), ("Enabling Environment", 68)]
    pillar_html = "".join(
        f'<div class="pillar"><span class="pk">{esc(k)}</span>'
        f'{progress_bar(v, "#16a34a")}<span class="pv">{v}</span></div>' for k, v in pillars)
    p2 = panel("Existing Readiness (from Platform)", f"""
      <div class="rd"><span class="lab">Consumer Readiness Score</span>{sparkline()}
        <div class="big">68<span class="of"> /100</span></div><div class="lvl">Medium - High</div></div>
      <div class="rd"><span class="lab">City / Ecosystem Readiness Score</span>{sparkline()}
        <div class="big">72<span class="of"> /100</span></div><div class="lvl">High</div></div>
      <h4>Key City Readiness Pillars</h4>{pillar_html}
      <a class="view-link" href="#">View Full Readiness Detail</a>
    """, num="2")

    # Panel 5: Economic Readiness
    p5 = panel("Project Economic Readiness", """
      <div class="econ">
        <div class="c"><div class="t">TCO Competitiveness<br>(Weight 50%)</div><div class="v">42<span class="of"> /100</span></div></div>
        <div class="c"><div class="t">Investment Burden<br>(Weight 25%)</div><div class="v">34<span class="of"> /100</span></div></div>
        <div class="c"><div class="t">Financing Market Access<br>(Weight 25%)</div><div class="v">72<span class="of"> /100</span></div></div>
        <div class="c"><div class="t">Economic Readiness Score<br>(Weighted)</div><div class="v">46<span class="of"> /100</span></div></div>
      </div>
      <div class="econ-lvl">Economic Readiness Level: <b>Moderate</b></div>
    """, num="5")

    # Panel 6: Sustainable Finance
    def _srow(sym, cls, k, v):
        return f"<tr><td>{esc(k)}</td><td class='num'><span class='{cls}'>{sym}</span></td><td>{esc(v)}</td></tr>"
    p6 = panel("Sustainable Finance & Support", "<table class='tbl'><tbody>"
        + _srow("✓", "chk", "Green Taxonomy Alignment", "Eligible")
        + _srow("✓", "chk", "Green Financing Availability", "High")
        + _srow("✓", "chk", "Government Incentive", "Available")
        + _srow("~", "warn", "Other Fiscal Support", "Partial")
        + _srow("✓", "chk", "Carbon / Environmental Benefit", "High")
        + "</tbody></table><a class='view-link' href='#'>View Details</a>", num="6")

    # Panel 7: Financing Supply
    supply = [("Green Loan", "High"), ("Lease / Rent", "High"), ("BaaS", "Medium"),
              ("Project Finance", "Low"), ("Blended Finance", "Medium"),
              ("Export Credit / Agency", "Low")]
    p7 = panel("Financing Supply (Provider Landscape)", "<table class='tbl'><thead><tr><th>Instrument</th><th class='num'>Availability</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(k)}</td><td class='num'>{esc(v)}</td></tr>" for k, v in supply)
        + "</tbody></table><div class='callout'>Typical tenor offered: 3–7 Years · Risk appetite for EV: Increasing</div>"
        + "<a class='view-link' href='#'>View Provider List</a>", num="7")

    # Panel 10: Recommended Structure
    p10 = panel("Recommended Structure (Summary)", "<div class='struct'>"
        + _cell("🏦", "Financing Structure", "Operating Lease")
        + _cell("🧩", "Risk Allocation (Key)", "Provider: Battery, Residual Value, Maintenance, Downtime · You: Usage, Operational Cost, Driver, Cargo Risk")
        + _cell("📅", "Tenor", "5 Years")
        + _cell("💳", "Upfront Payment", "10% of Vehicle Price")
        + _cell("🔌", "Charging Arrangement", "Provider owns & operates DC fast charging station")
        + _cell("🧾", "Monthly Payment (Est.)", "IDR 35 – 38 Million")
        + "</div><a class='view-link' href='#'>View Full Structure</a>", num="10", tone="teal")

    # Panel 11: Key Conditions
    conds = ["Availability of operating lease provider in Indonesia",
             "Clear SLA for uptime and maintenance",
             "Charging infrastructure readiness at depot",
             "Execution of government incentive application",
             "Credit assessment & documentation completion"]
    p11 = panel("Key Conditions", "".join(
        f"<div class='cond'><span class='c-ic'>✓</span><span>{esc(c)}</span></div>" for c in conds)
        + "<div class='foot-note'>This recommendation is indicative and based on data provided and open sources. Final decision remains with the stakeholder and financing parties.</div>"
        + "<a class='view-link' href='#'>View All Conditions</a>", num="11", tone="green")

    st.markdown(
        f'<div class="cols"><div class="col">{p1}{p2}{p3}{p4}'
        f'<div class="mid">{p5}{p6}{p7}{p8}</div></div>'
        f'<div class="col">{p9}{p10}{p11}</div></div>',
        unsafe_allow_html=True,
    )


def _cell(icon: str, k: str, v: str) -> str:
    return (
        f"<div class='cell'><span class='ci'>{icon}</span>"
        f"<div><div class='ck'>{esc(k)}</div><div class='cv'>{esc(v)}</div></div></div>"
    )


def _weighted(record: dict, slugs: list[str], weights: list[float]) -> float | None:
    vals = [record.get(s) for s in slugs]
    if any(v is None for v in vals):
        return None
    return sum(float(v) * w for v, w in zip(vals, weights))


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #
CSS = """
<style>
:root{
  --navy:#0f2a52; --navy-2:#123a6b; --blue:#1d4ed8; --blue-l:#2563eb;
  --ink:#0f172a; --muted:#64748b; --line:#e5e7eb; --bg:#eef2f7;
  --green:#16a34a; --amber:#f59e0b; --red:#dc2626; --purple:#7c3aed; --teal:#0d9488;
}
.block-container{padding-top:1.2rem; padding-bottom:2rem; max-width:1500px;}
h1,h2,h3{color:var(--ink);}
[data-testid="stSidebar"]{background:var(--navy);}
[data-testid="stSidebar"] *{color:#e6edf7;}
[data-testid="stSidebar"] .stRadio label{color:#e6edf7;}
[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.15);}
.fpb-brand{display:flex;gap:.6rem;align-items:center;margin:.2rem 0 1.1rem;}
.fpb-logo{width:38px;height:38px;border-radius:50%;background:#16a34a;
  display:flex;align-items:center;justify-content:center;font-size:20px;color:#fff;}
.fpb-brand b{font-size:1.05rem;letter-spacing:.03em;color:#fff;display:block;}
.fpb-brand small{color:#9fb3d1;font-size:.72rem;}
.nav{display:flex;flex-direction:column;gap:.15rem;margin-bottom:1rem;}
.nav a{display:flex;gap:.6rem;align-items:center;padding:.55rem .7rem;border-radius:8px;
  color:#cdd9ec;text-decoration:none;font-size:.9rem;}
.nav a.active{background:var(--blue-l);color:#fff;font-weight:600;}
.nav a:hover{background:rgba(255,255,255,.08);}
.ds-box{margin-top:.6rem;border:1px solid rgba(255,255,255,.15);border-radius:10px;
  padding:.7rem .8rem;font-size:.78rem;}
.ds-box .t{color:#fff;font-weight:700;letter-spacing:.05em;font-size:.72rem;margin-bottom:.4rem;}
.ds-box .i{display:flex;gap:.5rem;align-items:flex-start;margin:.45rem 0;color:#cdd9ec;}
.ds-box .i span.g{color:#7ee2a8;}

/* header */
.fpb-head{display:flex;justify-content:space-between;align-items:center;
  background:#fff;border:1px solid var(--line);border-radius:12px;padding:.7rem 1.1rem;
  margin-bottom:.9rem;box-shadow:0 1px 2px rgba(16,24,40,.04);}
.fpb-head h2{margin:0;font-size:1.25rem;}
.fpb-head .code{color:var(--muted);font-weight:600;margin-left:.6rem;font-size:.9rem;}
.fpb-head .right{display:flex;gap:.8rem;align-items:center;}
.btn-export{display:inline-flex;gap:.4rem;align-items:center;border:1px solid var(--line);
  background:#fff;border-radius:8px;padding:.45rem .8rem;font-size:.85rem;color:var(--ink);
  font-weight:600;cursor:default;}
.user{display:flex;gap:.5rem;align-items:center;}
.user .av{width:34px;height:34px;border-radius:50%;background:var(--navy);color:#fff;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;}
.user small{display:block;color:var(--muted);}

/* filters */
.filters{display:grid;grid-template-columns:repeat(5,1fr);gap:.8rem;margin-bottom:.9rem;}
.field label{display:block;font-size:.72rem;color:var(--muted);margin-bottom:.25rem;font-weight:600;}
.field .sel{display:flex;justify-content:space-between;align-items:center;background:#fff;
  border:1px solid var(--line);border-radius:8px;padding:.5rem .7rem;font-size:.85rem;color:var(--ink);}
.field .sel::after{content:"▾";color:var(--muted);}

/* index cards */
.idx-row{display:grid;grid-template-columns:repeat(6,1fr);gap:.8rem;margin-bottom:1rem;}
.idx-card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:.85rem;
  display:flex;gap:.6rem;align-items:flex-start;box-shadow:0 1px 2px rgba(16,24,40,.04);}
.idx-card--hero{border:1.5px solid var(--green);background:#f2fbf5;}
.idx-icon{font-size:1.3rem;width:34px;height:34px;flex:0 0 34px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;background:color-mix(in srgb,var(--accent) 12%,#fff);}
.idx-label{font-size:.72rem;color:var(--ink);font-weight:600;line-height:1.15;min-height:2.1em;}
.idx-value{font-size:1.7rem;font-weight:800;color:var(--accent);line-height:1;}
.idx-denom{font-size:.8rem;color:var(--muted);font-weight:600;}
.idx-desc{font-size:.72rem;font-weight:600;margin-top:.15rem;}
.pbar{height:6px;background:#e5e7eb;border-radius:4px;margin-top:.5rem;overflow:hidden;}
.pbar-fill{height:100%;border-radius:4px;}

/* layout columns */
.cols{display:grid;grid-template-columns:2.35fr 1fr;gap:1rem;align-items:start;}
.col{display:flex;flex-direction:column;gap:1rem;}
.mid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;}

/* panels */
.panel{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;
  box-shadow:0 1px 2px rgba(16,24,40,.04);}
.panel-head{background:var(--navy);color:#fff;font-weight:700;font-size:.85rem;padding:.55rem .9rem;}
.panel--green .panel-head{background:var(--green);}
.panel--teal .panel-head{background:var(--teal);}
.panel-body{padding:.9rem;}
.panel h4{margin:.2rem 0 .6rem;color:var(--blue);font-size:.82rem;}

/* key-value */
.kv{display:flex;gap:.6rem;align-items:center;padding:.32rem 0;font-size:.82rem;
  border-bottom:1px dashed #eef1f5;}
.kv:last-child{border-bottom:none;}
.kv-ic{width:20px;text-align:center;color:var(--navy);}
.kv-k{color:var(--muted);flex:1;}
.kv-v{color:var(--ink);font-weight:600;}

/* readiness */
.rd{border:1px solid var(--line);border-radius:10px;padding:.6rem .7rem;margin-bottom:.7rem;}
.rd .lab{font-size:.78rem;color:var(--ink);font-weight:600;}
.rd .big{font-size:1.5rem;font-weight:800;color:var(--green);}
.rd .of{font-size:.75rem;color:var(--muted);}
.rd .lvl{font-size:.72rem;color:var(--green);font-weight:600;}
.spark{width:90px;height:26px;float:right;}
.pillar{display:flex;align-items:center;gap:.5rem;font-size:.74rem;margin:.3rem 0;}
.pillar .pk{flex:1;color:var(--ink);}
.pillar .pbar{flex:0 0 70px;margin:0;height:5px;}
.pillar .pv{width:22px;text-align:right;color:var(--muted);font-weight:600;}

/* likert */
.lk{display:flex;align-items:center;gap:.5rem;padding:.3rem 0;font-size:.8rem;
  border-bottom:1px dashed #eef1f5;}
.lk:last-child{border-bottom:none;}
.lk-k{flex:1;color:var(--ink);}
.lk-s{display:flex;align-items:center;gap:.35rem;}
.stars{letter-spacing:1px;}
.star-on{color:#f59e0b;} .star-off{color:#d7dde6;}
.star-val{font-weight:700;color:var(--ink);margin-left:.2rem;}
.score-line{display:flex;justify-content:space-between;align-items:baseline;margin-top:.6rem;
  padding-top:.5rem;border-top:1px solid var(--line);}
.score-line .sl{font-size:.8rem;color:var(--ink);font-weight:600;}
.score-line .sv{font-size:1.25rem;font-weight:800;color:var(--navy);}
.idx-badge{display:flex;justify-content:space-between;align-items:center;border-radius:8px;
  padding:.5rem .7rem;margin-top:.5rem;font-size:.8rem;font-weight:600;}
.idx-badge.green{background:#eafaf0;color:#15803d;}
.idx-badge.amber{background:#fef6e7;color:#b45309;}
.idx-badge .n{font-size:1.2rem;font-weight:800;}
.scale-note{background:#f1f5fb;border-radius:8px;padding:.5rem .7rem;font-size:.72rem;
  color:var(--muted);text-align:center;margin-top:.7rem;}

/* tco */
.tco-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}
.chart{display:flex;gap:.5rem;height:230px;}
.chart-grid{display:flex;flex-direction:column;justify-content:space-between;
  font-size:.65rem;color:var(--muted);text-align:right;width:34px;}
.chart-bars{flex:1;display:flex;justify-content:space-around;align-items:flex-end;
  border-left:1px solid var(--line);border-bottom:1px solid var(--line);padding:0 .5rem;}
.bar-col{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;}
.bar{width:54px;border-radius:4px 4px 0 0;}
.bar--diesel{background:#9aa6b6;} .bar--ev{background:#16a34a;}
.bar-val{font-size:.72rem;font-weight:700;color:var(--ink);margin-bottom:.2rem;}
.bar-x{font-size:.72rem;color:var(--muted);margin-top:.3rem;}
.chart-empty{color:var(--muted);font-size:.8rem;padding:2rem 0;text-align:center;}
.callout{background:#eef6ff;border:1px solid #d6e8fb;border-radius:8px;padding:.5rem .7rem;
  font-size:.76rem;color:#1e40af;text-align:center;margin-top:.6rem;}
.callout.grey{background:#f1f5f9;border-color:#e2e8f0;color:var(--muted);}

/* tables */
.tbl{width:100%;border-collapse:collapse;font-size:.76rem;}
.tbl th{background:#f1f5f9;color:var(--ink);text-align:left;padding:.45rem .5rem;font-weight:700;}
.tbl th.num,.tbl td.num{text-align:right;}
.tbl td{padding:.4rem .5rem;border-bottom:1px solid #eef1f5;color:var(--ink);}
.tbl .sub{font-weight:400;color:var(--muted);font-size:.66rem;}
.tbl td.ev{color:var(--green);font-weight:700;}
.tbl--schemes th,.tbl--schemes td{padding:.35rem .35rem;font-size:.72rem;}
.tbl--schemes .sc-name{text-align:left;white-space:nowrap;}
.tbl--schemes .total{font-weight:800;}
.tbl--schemes .rank{font-weight:700;}
.row-primary{background:#eafaf0;}
.row-primary .total,.row-primary .rank{color:var(--green);}

/* recommendation */
.rec-hero{text-align:center;border:1.5px solid var(--green);border-radius:10px;padding:.9rem;
  background:#f4fbf6;}
.rec-hero .tag{font-size:.72rem;font-weight:700;color:var(--blue);letter-spacing:.05em;}
.rec-hero .trophy{font-size:2rem;}
.rec-hero .scheme{font-size:1.3rem;font-weight:800;color:var(--green);line-height:1.1;}
.rec-hero .sub{font-size:.78rem;color:var(--muted);}
.rec-hero .note{font-size:.72rem;color:var(--ink);margin-top:.5rem;}
.rec-score{display:flex;justify-content:space-between;align-items:baseline;margin-top:.7rem;}
.rec-score .l{font-size:.78rem;color:var(--ink);font-weight:600;}
.rec-score .v{font-size:1.6rem;font-weight:800;color:var(--green);}
.alt-row{display:flex;justify-content:space-between;font-size:.78rem;padding:.35rem 0;
  border-bottom:1px dashed #eef1f5;}
.alt-row:last-child{border-bottom:none;}
.alt-row .v{font-weight:700;color:var(--ink);}
.view-link{display:block;text-align:center;color:var(--blue);font-weight:600;font-size:.78rem;
  margin-top:.6rem;text-decoration:none;}

/* structure grid */
.struct{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;}
.struct .cell{display:flex;gap:.5rem;align-items:flex-start;}
.struct .ci{font-size:1rem;color:var(--navy);width:20px;text-align:center;}
.struct .ck{font-size:.74rem;color:var(--ink);font-weight:700;}
.struct .cv{font-size:.72rem;color:var(--muted);}

/* econ cards */
.econ{display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;}
.econ .c{border:1px solid var(--line);border-radius:8px;padding:.5rem;text-align:center;}
.econ .c .t{font-size:.66rem;color:var(--muted);min-height:2.4em;}
.econ .c .v{font-size:1.25rem;font-weight:800;color:var(--navy);}
.econ .c .of{font-size:.66rem;color:var(--muted);}
.econ .c .pbar{margin-top:.35rem;}
.econ-lvl{display:flex;justify-content:center;gap:.4rem;align-items:center;margin-top:.7rem;
  font-size:.78rem;color:var(--ink);font-weight:600;}
.econ-lvl b{color:var(--green);}

/* status pills */
.chk{color:var(--green);font-weight:800;}
.warn{color:var(--amber);font-weight:800;}
.cond{display:flex;gap:.5rem;font-size:.78rem;margin:.4rem 0;color:var(--ink);}
.cond .c-ic{color:var(--green);font-weight:800;}
.foot-note{font-size:.68rem;color:var(--muted);margin-top:.6rem;line-height:1.4;}

/* questionnaire */
.q-head{background:#fff;border:1px solid var(--line);border-radius:12px;padding:.8rem 1.1rem;
  margin-bottom:1rem;box-shadow:0 1px 2px rgba(16,24,40,.04);}
.q-head h2{margin:0;font-size:1.2rem;}
.q-head p{margin:.2rem 0 0;color:var(--muted);font-size:.85rem;}
.q-sec{background:var(--navy);color:#fff;font-weight:700;font-size:.9rem;
  padding:.5rem .9rem;border-radius:8px;margin:1.1rem 0 .5rem;}
.q-req{color:var(--red);font-weight:700;}
</style>
"""


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def _sidebar(bundle) -> tuple[object, object, bool]:
    with st.sidebar:
        st.markdown(
            """
            <div class="fpb-brand">
              <div class="fpb-logo">⚡</div>
              <div><b>FINANCING PLAYBOOK</b><small>EV Financing Recommendation</small></div>
            </div>
            <div class="nav">
              <a class="active" href="#">📊 Dashboard</a>
              <a href="#">📋 Assessments</a>
              <a href="#">🗂️ Case Management</a>
              <a href="#">📚 Data Library</a>
              <a href="#">🏦 Financing Providers</a>
              <a href="#">📄 Reports</a>
              <a href="#">🔀 Scenario Analysis</a>
              <a href="#">⚙️ Settings</a>
            </div>
            <hr>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Gunakan tab Kuesioner untuk input manual, atau impor jawaban di bawah.")
        load_example = st.button("↻ Load example assessment", use_container_width=True)
        xlsx = st.file_uploader("Import questionnaire (.xlsx)", type=["xlsx"])
        jfile = st.file_uploader("Import record (.json)", type=["json"])
        st.markdown(
            """
            <div class="ds-box">
              <div class="t">DATA SOURCES</div>
              <div class="i"><span>🟢</span><div><b>Consumer Readiness</b><br>Approved readiness score</div></div>
              <div class="i"><span>🏙️</span><div><b>City / Ecosystem Readiness</b><br>Approved regional score</div></div>
              <div class="i"><span>📁</span><div><b>Open Data</b><br>14 Data Categories</div></div>
            </div>
            <div style="margin-top:.8rem;font-size:.7rem;color:#9fb3d1;">Version 1.0.0</div>
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
        req = ' <span class="q-req">*</span>' if field.get("required") else ""
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

    # ---- header + filters --------------------------------------------- #
    st.markdown(
        f"""
        <div class="fpb-head">
          <div style="display:flex;align-items:baseline;">
            <h2>Assessment Detail</h2><span class="code">{esc(CASE_REF['id'])}</span>
          </div>
          <div class="right">
            <span class="btn-export">⬇ Export Report</span>
            <div class="user"><div class="av">{esc(initials(who))}</div>
              <div><b style="font-size:.85rem;">{esc(who)}</b></div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="filters">
          <div class="field"><label>City / Region</label><div class="sel">{esc(city)}</div></div>
          <div class="field"><label>Use Case</label><div class="sel">{esc(use_case)}</div></div>
          <div class="field"><label>Operation</label><div class="sel">{esc(operation)}</div></div>
          <div class="field"><label>Vehicle Type</label><div class="sel">{esc(vehicle)}</div></div>
          <div class="field"><label>Assessment Date</label><div class="sel">{esc(date)} 📅</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- index cards --------------------------------------------------- #
    fn = metric_val(result, "financing_need_index")
    rp = metric_val(result, "risk_profile_index")
    tcc = metric_val(result, "tco_competitiveness")
    ib = metric_val(result, "investment_burden")
    er = metric_val(result, "economic_readiness")
    overall = result.overall.value if result.overall.state == "computed" else None

    cards = "".join(
        [
            index_card(label="Financing Need Index", value=fn,
                       descriptor=band_text_hyphen(fn), icon="💰", accent="var(--green)"),
            index_card(label="Risk Profile Index", value=rp,
                       descriptor=band_text_hyphen(rp), icon="🛡️", accent="var(--amber)"),
            index_card(label="TCO Competitiveness", value=tcc,
                       descriptor="Below Parity" if (tcc is not None and tcc < 100) else "At Parity",
                       icon="📊", accent="var(--blue)"),
            index_card(label="Investment Burden", value=ib,
                       descriptor="High Burden" if (ib is not None and ib < 50) else "Moderate Burden",
                       icon="💵", accent="var(--purple)"),
            index_card(label="Economic Readiness", value=er,
                       descriptor=band_text(er), icon="🎯", accent="var(--teal)"),
            index_card(label="Overall Financing Fit Score", value=overall,
                       descriptor="Good Fit" if (overall is not None and overall >= 67)
                       else ("Fair Fit" if overall is not None and overall >= 34 else "Weak Fit"),
                       icon="🏆", accent="var(--green)", big=True),
        ]
    )
    st.markdown(f'<div class="idx-row">{cards}</div>', unsafe_allow_html=True)

    # ---- two-column body ---------------------------------------------- #
    left, right = st.columns([2.35, 1])

    with left:
        # Panel 1: Case Context
        p1 = panel(
            "Case Context",
            "".join(
                [
                    kv_row("🏢", "Stakeholder Type", stakeholder),
                    kv_row("🛣️", "Annual Mileage", f"{num(rec.get('tco_annual_km'))} km"),
                    kv_row("🛒", "Purchase Scenario", CASE_REF["scenario"]),
                    kv_row("📍", "Assessment Scope", use_case),
                    kv_row("👤", "Created By", who),
                    kv_row("🕑", "Last Updated", date),
                ]
            ),
            num="1",
        )
        # Panel 2: Existing Readiness
        cons = ctx.get("consumer_readiness")
        cri = ctx.get("city_cri")
        pillars = [
            ("Infrastructure", _meta_num("form_1_4", 70)),
            ("Policy & Support", _meta_num("form_1_5", 75)),
            ("Economic Scale", _meta_num("form_1_6", 72)),
            ("Aftermarket / Service", _meta_num("form_1_7", 68)),
        ]
        pillar_html = "".join(
            f'<div class="pillar"><span class="pk">{esc(k)}</span>'
            f'{progress_bar(v, "#16a34a")}<span class="pv">{v}</span></div>'
            for k, v in pillars
        )
        p2 = panel(
            "Existing Readiness (from Platform)",
            f"""
            <div class="rd"><span class="lab">Consumer Readiness Score</span>{sparkline()}
              <div class="big">{num(cons)}<span class="of"> /100</span></div>
              <div class="lvl">{band_text(cons)}</div></div>
            <div class="rd"><span class="lab">City / Ecosystem Readiness Score</span>{sparkline()}
              <div class="big">{num(cri)}<span class="of"> /100</span></div>
              <div class="lvl">{band_text(cri)}</div></div>
            <h4>Key City Readiness Pillars</h4>{pillar_html}
            <a class="view-link" href="#">View Full Readiness Detail</a>
            """,
            num="2",
        )
        # Panel 3: Financing Profile
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
        p3 = panel(
            "Financing Profile (Questionnaire Results)",
            f"""
            <div class="tco-grid">
              <div>
                <h4>3A. Financing Need</h4>
                {''.join(likert_row(l, rec.get(s)) for l, s in fn_fields)}
                <div class="score-line"><span class="sl">Financing Need Score</span>
                  <span class="sv">{num(fn_score,2)} <span style="font-size:.7rem;color:var(--muted)">/5</span></span></div>
                <div class="idx-badge green"><span>Financing Need Index</span>
                  <span class="n">{num(fn)} <span style="font-size:.7rem">/100</span></span></div>
              </div>
              <div>
                <h4>3B. Risk Profile</h4>
                {''.join(likert_row(l, rec.get(s)) for l, s in rp_fields)}
                <div class="score-line"><span class="sl">Risk Profile Score</span>
                  <span class="sv">{num(rp_score,2)} <span style="font-size:.7rem;color:var(--muted)">/5</span></span></div>
                <div class="idx-badge amber"><span>Risk Profile Index</span>
                  <span class="n">{num(rp)} <span style="font-size:.7rem">/100</span></span></div>
              </div>
            </div>
            <div class="scale-note">Scale: 1 = Very Low / Very Risk Averse&nbsp;&nbsp;
              3 = Moderate&nbsp;&nbsp;5 = Very High / Very Risk Tolerant</div>
            """,
            num="3",
        )
        # Panel 4: TCO
        if tco.get("state") == "insufficient_inputs":
            tco_body = (
                "<div class='chart-empty'>TCO inputs incomplete — missing: "
                + esc(", ".join(tco.get("missing", []))) + "</div>"
            )
        else:
            d_total = tco["diesel"]["total_idr_m"]
            e_total = tco["ev"]["total_idr_m"]
            diff = None
            if d_total:
                diff = (e_total - d_total) / d_total * 100
            tco_body = f"""
            <div class="tco-grid">
              <div>
                <h4>Cost Comparison (8 Years)</h4>
                <div style="font-size:.7rem;color:var(--muted);margin-bottom:.3rem;">
                  Total TCO (IDR Million)</div>
                {bar_chart(d_total, e_total)}
                <div class="callout">EV TCO is {abs(diff):.1f}%
                  {'higher' if diff and diff>0 else 'lower'} than Diesel in base case scenario.</div>
                <div class="callout grey">Cold Chain Add-on: Refrigeration energy and
                  equipment cost included in TCO.</div>
              </div>
              <div>
                <h4>Key TCO Indicators</h4>
                {tco_indicator_rows(tco)}
              </div>
            </div>"""
        p4 = panel("Total Cost of Ownership (TCO) Analysis", tco_body, num="4", tone="navy")

        # Panel 5: Economic Readiness
        ma = metric_val(result, "market_access")
        p5 = panel(
            "Project Economic Readiness",
            f"""
            <div class="econ">
              <div class="c"><div class="t">TCO Competitiveness<br>(Weight 50%)</div>
                <div class="v">{num(tcc)}<span class="of"> /100</span></div>
                {progress_bar(tcc, "var(--blue)")}</div>
              <div class="c"><div class="t">Investment Burden<br>(Weight 25%)</div>
                <div class="v">{num(ib)}<span class="of"> /100</span></div>
                {progress_bar(ib, "var(--blue)")}</div>
              <div class="c"><div class="t">Financing Market Access<br>(Weight 25%)</div>
                <div class="v">{num(ma)}<span class="of"> /100</span></div>
                {progress_bar(ma, "var(--green)")}</div>
              <div class="c"><div class="t">Economic Readiness Score<br>(Weighted)</div>
                <div class="v">{num(er)}<span class="of"> /100</span></div>
                {progress_bar(er, "var(--green)")}</div>
            </div>
            <div class="econ-lvl">Economic Readiness Level: <b>{band_text(er)}</b></div>
            """,
            num="5",
        )
        # Panel 6: Sustainable Finance
        def status(sym: str, cls: str, label: str, note: str) -> str:
            return (
                f"<tr><td>{esc(label)}</td>"
                f"<td class='num'><span class='{cls}'>{sym}</span></td>"
                f"<td>{esc(note)}</td></tr>"
            )
        def support_status(value: str) -> tuple[str, str]:
            unavailable = {"", "No", "None", "Not eligible", "Unknown", "(choose one)"}
            return ("✓", "chk") if value not in unavailable else ("~", "warn")

        sf_rows = [
            ("Green Taxonomy Alignment", _m("form_7_1", "Not provided")),
            ("Green / Sustainable Financing", _m("form_7_2", "Not provided")),
            ("Government Incentive", _m("form_7_3", "Not provided")),
            ("Other Fiscal Support", _m("form_7_5", "Not provided")),
            ("Carbon / Environmental Benefit", _m("form_7_6", "Not provided")),
        ]
        p6 = panel(
            "Sustainable Finance & Support",
            "<table class='tbl'><tbody>"
            + "".join(status(*support_status(value), label, value) for label, value in sf_rows)
            + "</tbody></table>"
            + "<a class='view-link' href='#'>View Details</a>",
            num="6",
        )
        # Panel 7: Financing Supply
        supply = [
            ("Green Loan", rec.get("fs_green_loan", "—")),
            ("Lease / Rent", rec.get("fs_lease_rent", "—")),
            ("BaaS", rec.get("fs_baas", "—")),
            ("Project Finance", rec.get("fs_project_finance", "—")),
            ("Blended Finance", rec.get("fs_blended_finance", "—")),
            ("Export Credit / Agency", "Low"),
        ]
        p7 = panel(
            "Financing Supply (Provider Landscape)",
            "<table class='tbl'><thead><tr><th>Instrument</th>"
            "<th class='num'>Availability</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{esc(k)}</td><td class='num'>{esc(str(v))}</td></tr>"
                for k, v in supply
            )
            + "</tbody></table>"
            + "<div class='callout'>Typical tenor offered: 3–7 Years · "
            "Risk appetite for EV: Increasing</div>"
            + "<a class='view-link' href='#'>View Provider List</a>",
            num="7",
        )
        # Panel 8: Scheme Matching
        p8 = panel(
            "Scheme Matching Results",
            scheme_table(result.schemes, bundle.schemes["weights"])
            + "<a class='view-link' href='#'>View Detailed Scoring</a>",
            num="8",
        )

        st.markdown(f'<div class="col">{p1}{p3}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="mid">{p5}{p6}{p7}{p8}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="cols" style="margin-top:1rem;">'
            f'<div class="col">{p4}</div><div class="col">{p2}</div></div>',
            unsafe_allow_html=True,
        )

    with right:
        # Panel 9: Recommended Scheme
        primary = next((s for s in result.schemes if s.is_primary), None)
        alts = [s for s in result.schemes if not s.is_primary and s.rank][:3]
        rec_html = (
            '<div class="rec-hero"><div class="tag">PRIMARY RECOMMENDATION</div>'
            '<div class="trophy">🏆</div>'
            f'<div class="scheme">SCHEME {esc(primary.scheme_id)}<br>{esc(primary.name).upper()}</div>'
            '<div class="sub">Ranked #1 by weighted fit score</div>'
            '<div class="note">Best fit for your financing need, risk preference, '
            'and economic profile.</div>'
            f'<div class="rec-score"><span class="l">Financing Fit Score</span>'
            f'<span class="v">{num(primary.total)} <span style="font-size:.8rem">/100</span></span></div>'
            f'{progress_bar(primary.total, "var(--green)")}</div>'
            if primary
            else '<div class="chart-empty">No eligible recommendation.</div>'
        )
        alt_html = "<div style='margin-top:.8rem;'><h4 style='color:var(--ink)'>Alternative Schemes</h4>"
        for s in alts:
            alt_html += (
                f"<div class='alt-row'><span>{s.rank}. {esc(s.name)}</span>"
                f"<span class='v'>{num(s.total)} <span style='font-size:.7rem;color:var(--muted)'>/100</span></span></div>"
            )
        alt_html += "</div><a class='view-link' href='#'>View Scheme Comparison</a>"
        p9 = panel("Recommended Scheme", rec_html + alt_html, num="9", tone="green")

        # Panel 10: Recommended Structure
        struct_name = primary.name if primary else "Operating Lease"
        p10 = panel(
            "Recommended Structure (Summary)",
            "<div class='struct'>"
            + _cell("🏦", "Financing Structure", struct_name)
            + _cell("🧩", "Risk Allocation (Key)",
                    "Provider: Battery, Residual Value, Maintenance, Downtime · "
                    "You: Usage, Operational Cost, Driver, Cargo Risk")
            + _cell("📅", "Tenor", "5 Years")
            + _cell("💳", "Upfront Payment", "10% of Vehicle Price")
            + _cell("🔌", "Charging Arrangement", "Provider owns & operates DC fast charging station")
            + _cell("🧾", "Monthly Payment (Est.)", "IDR 35 – 38 Million")
            + "</div><a class='view-link' href='#'>View Full Structure</a>",
            num="10",
            tone="teal",
        )
        # Panel 11: Key Conditions
        conds = [
            "Availability of operating lease provider in Indonesia",
            "Clear SLA for uptime and maintenance",
            "Charging infrastructure readiness at depot",
            "Execution of government incentive application",
            "Credit assessment & documentation completion",
        ]
        p11 = panel(
            "Key Conditions",
            "".join(f"<div class='cond'><span class='c-ic'>✓</span><span>{esc(c)}</span></div>" for c in conds)
            + "<div class='foot-note'>This recommendation is indicative and based on "
            "data provided and open sources. Final decision remains with the "
            "stakeholder and financing parties.</div>"
            + "<a class='view-link' href='#'>View All Conditions</a>",
            num="11",
            tone="green",
        )
        st.markdown(f'<div class="col">{p9}{p10}{p11}</div>', unsafe_allow_html=True)

    if result.warnings:
        st.caption("⚠ " + " · ".join(result.warnings))


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
