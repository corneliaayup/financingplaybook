# Financing Playbook — Scoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, config-driven scoring engine that turns a normalized questionnaire record into a full assessment (indices, TCO, scheme ranking, headline score), verified against golden values recomputed from the source workbooks.

**Architecture:** Pure Python package `src/fpb/` with no I/O: YAML config defines fields, weights, bands and scheme rules; Python supplies five closed rule primitives. Ingestion, storage and UI are separate plans that consume `engine.score()`.

**Tech Stack:** Python 3.11, PyYAML, pytest. No other runtime dependencies in this plan.

**Spec:** `docs/superpowers/specs/2026-08-29-financing-playbook-assessment-tool-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Python 3.11; the only runtime dependency added by this plan is PyYAML (pytest for tests).
- All arithmetic at full precision; rounding happens only at display (never inside the engine).
- Every result carries `spec_version` and `config_version` stamps.
- Metrics have three states: `computed`, `not_applicable`, `insufficient_inputs` (naming missing fields). No silent defaults.
- The engine module tree must not import streamlit, sqlite3, pandas, or openpyxl.
- Commit after every task.

## File Structure

```
pyproject.toml
config/questionnaire.yaml     # field slugs, types, options, routing, aliases, spec_version
config/scoring.yaml           # index conversion, bands, weights, market-access scale, config_version
config/schemes.yaml           # scheme library: fit rules, library_priority, status
src/fpb/__init__.py
src/fpb/config.py             # load_config, validate_config
src/fpb/types.py              # Metric, TcoTotals, SchemeResult, AssessmentResult, state constants
src/fpb/scoring.py            # likert_index, band, financing_need, risk_profile
src/fpb/tco.py                # symmetric TCO chain, competitiveness, investment burden, payback
src/fpb/market_access.py      # financing market access + economic readiness
src/fpb/schemes.py            # the five primitives, evaluate_scheme, rank_schemes
src/fpb/engine.py             # score(record, bundle, context) -> AssessmentResult
src/fpb/cli.py                # python -m fpb.cli score --record <json>
tests/conftest.py             # bundle fixture loading real config/
tests/fixtures/workbook_case.json
tests/test_config.py
tests/test_scoring.py
tests/test_tco.py
tests/test_market_access.py
tests/test_schemes.py
tests/test_engine.py
tests/test_properties.py
```

---

### Task 1: Project scaffold and config loader

**Files:**
- Create: `pyproject.toml`, `src/fpb/__init__.py`, `src/fpb/config.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `load_config(root: Path) -> ConfigBundle` where `ConfigBundle` is a frozen dataclass with fields `root: Path, spec_version: str, config_version: str, questionnaire: dict, scoring: dict, schemes: dict`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "financing-playbook"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pyyaml>=6"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create package marker and loader**

`src/fpb/__init__.py` is empty. `src/fpb/config.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class ConfigBundle:
    root: Path
    spec_version: str
    config_version: str
    questionnaire: dict
    scoring: dict
    schemes: dict


def load_config(root: Path) -> ConfigBundle:
    q = yaml.safe_load((root / "questionnaire.yaml").read_text())
    s = yaml.safe_load((root / "scoring.yaml").read_text())
    sc = yaml.safe_load((root / "schemes.yaml").read_text())
    return ConfigBundle(root, q["spec_version"], s["config_version"], q, s, sc)
```

- [ ] **Step 3: Write conftest with the real-config fixture**

```python
from pathlib import Path
import pytest
from fpb.config import load_config

REPO = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="session")
def bundle():
    return load_config(REPO / "config")
```

- [ ] **Step 4: Write the failing test**

`tests/test_config.py`:

```python
def test_load_config_versions(bundle):
    assert bundle.spec_version == "2026-01"
    assert bundle.config_version == "2026-01"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `config/questionnaire.yaml` does not exist yet.

- [ ] **Step 6: Create the three minimal config files**

`config/questionnaire.yaml` (full content lands in Task 2; minimal for now):

```yaml
spec_version: "2026-01"
sections: []
```

`config/scoring.yaml` (full content lands in Tasks 3, 5 and 7; the keys below are the
ones `validate_config` reads in Task 2, so carry them now with placeholder weights):

```yaml
config_version: "2026-01"
bands: {low: [0, 33], medium: [34, 66], high: [67, 100]}
financing_need: {slugs: [], weights: [0.25, 0.25, 0.25, 0.25]}
risk_profile: {ownership_slug: rp_ownership, tolerance_slugs: [], weights: [0.5, 0.5]}
economic_readiness: {weights: {tco_competitiveness: 0.5, investment_burden: 0.25, market_access: 0.25}}
overall_fit: {weights: {primary_scheme_fit: 0.4, economic_readiness: 0.25, financing_need_index: 0.2, readiness_context: 0.15}}
```

`config/schemes.yaml` (full content lands in Task 6; `weights` is read by
`validate_config` in Task 2, so carry it now):

```yaml
weights: {need: 0.20, risk: 0.20, tco: 0.20, operational: 0.15, payment: 0.10, support: 0.15}
schemes: []
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src tests config
git commit -m "feat: scaffold fpb package and config loader"
```

---

### Task 2: Types and config validation

**Files:**
- Create: `src/fpb/types.py`
- Modify: `src/fpb/config.py` (add `validate_config`), `tests/test_config.py`

**Interfaces:**
- Produces: `Metric`, `TcoTotals`, `SchemeResult`, `AssessmentResult`, state constants `COMPUTED`, `NOT_APPLICABLE`, `INSUFFICIENT`; `validate_config(bundle) -> list[str]` returning human-readable problems (empty list = valid).

- [ ] **Step 1: Write types.py**

```python
from __future__ import annotations
from dataclasses import dataclass, field

COMPUTED = "computed"
NOT_APPLICABLE = "not_applicable"
INSUFFICIENT = "insufficient_inputs"


@dataclass(frozen=True)
class Metric:
    value: float | None
    state: str = COMPUTED
    missing: tuple[str, ...] = ()
    detail: str = ""

    @staticmethod
    def insufficient(missing: tuple[str, ...]) -> Metric:
        return Metric(None, INSUFFICIENT, tuple(missing))


@dataclass(frozen=True)
class TcoTotals:
    total_idr_m: float
    cost_per_km: float
    annual_opex_idr_m: float
    net_capex_idr_m: float


@dataclass(frozen=True)
class SchemeResult:
    scheme_id: str
    name: str
    status: str
    fits: dict[str, float | None]
    fit_details: dict[str, str]
    total: float | None
    rank: int = 0
    is_primary: bool = False
    tie_with: str | None = None


@dataclass(frozen=True)
class AssessmentResult:
    spec_version: str
    config_version: str
    metrics: dict[str, Metric]
    tco: dict
    schemes: list[SchemeResult]
    overall: Metric
    primary_id: str | None
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Write the failing validation tests**

Append to `tests/test_config.py`:

```python
from fpb.config import validate_config

def test_valid_config_has_no_problems(bundle):
    assert validate_config(bundle) == []

def test_validate_catches_bad_weights(bundle, tmp_path):
    import copy, yaml
    bad = copy.deepcopy(bundle.scoring)
    bad["financing_need"]["weights"] = [0.25, 0.25, 0.25, 0.20]
    (tmp_path / "questionnaire.yaml").write_text(yaml.safe_dump(bundle.questionnaire))
    (tmp_path / "scoring.yaml").write_text(yaml.safe_dump(bad))
    (tmp_path / "schemes.yaml").write_text(yaml.safe_dump(bundle.schemes))
    from fpb.config import load_config
    problems = validate_config(load_config(tmp_path))
    assert any("financing_need" in p and "1.0" in p for p in problems)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `validate_config` not defined.

- [ ] **Step 4: Implement validate_config**

Append to `src/fpb/config.py`:

```python
def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) < 1e-9


def validate_config(bundle: ConfigBundle) -> list[str]:
    problems: list[str] = []
    s = bundle.scoring

    fn_w = s["financing_need"]["weights"]
    if not _close(sum(fn_w), 1.0):
        problems.append(f"financing_need weights sum to {sum(fn_w)}, expected 1.0")

    rp_w = s["risk_profile"]["weights"]
    if not _close(sum(rp_w), 1.0):
        problems.append(f"risk_profile weights sum to {sum(rp_w)}, expected 1.0")

    er_w = s["economic_readiness"]["weights"]
    if not _close(sum(er_w.values()), 1.0):
        problems.append(f"economic_readiness weights sum to {sum(er_w.values())}, expected 1.0")

    of_w = s["overall_fit"]["weights"]
    if not _close(sum(of_w.values()), 1.0):
        problems.append(f"overall_fit weights sum to {sum(of_w.values())}, expected 1.0")

    bands = s["bands"]
    if [tuple(bands[k]) for k in ("low", "medium", "high")] != [(0, 33), (34, 66), (67, 100)]:
        problems.append("bands must be low [0,33], medium [34,66], high [67,100]")

    sw = bundle.schemes["weights"]
    if not _close(sum(sw.values()), 1.0):
        problems.append(f"scheme weights sum to {sum(sw.values())}, expected 1.0")

    priorities = [x["library_priority"] for x in bundle.schemes["schemes"] if x["status"] == "active"]
    if len(priorities) != len(set(priorities)):
        problems.append("library_priority must be unique among active schemes")

    known = {"target_band", "parity_or_gap", "constant", "support_fit", "weighted_sum"}
    for x in bundle.schemes["schemes"]:
        for dim, rule in x["fit"].items():
            if dim != "total" and next(iter(rule)) not in known:
                problems.append(f"scheme {x['id']}: unknown primitive in {dim}")
    return problems
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (the minimal configs from Task 1 must also pass validation; if `KeyError` appears, extend the minimal YAML stubs with the keys validation reads — full content lands in Tasks 3-6).

- [ ] **Step 6: Commit**

```bash
git add src/fpb/types.py src/fpb/config.py tests/test_config.py
git commit -m "feat: result types and config validation"
```

---

### Task 3: Financing Need and Risk Profile scoring

**Files:**
- Create: `src/fpb/scoring.py`, `tests/test_scoring.py`
- Modify: `config/scoring.yaml`, `config/questionnaire.yaml` (add the scored fields)

**Interfaces:**
- Produces: `likert_index(score) -> float`, `band(index, bands) -> str`, `financing_need(record, cfg) -> Metric`, `risk_profile(record, cfg) -> Metric`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scoring.py`:

```python
import pytest
from fpb.scoring import band, financing_need, likert_index, risk_profile
from fpb.types import INSUFFICIENT

BANDS = {"low": (0, 33), "medium": (34, 66), "high": (67, 100)}

def test_likert_index():
    assert likert_index(1) == 0.0
    assert likert_index(3) == 50.0
    assert likert_index(5) == 100.0
    assert likert_index(4.75) == 93.75

def test_band_edges():
    assert band(0, BANDS) == "LOW" and band(33, BANDS) == "LOW"
    assert band(34, BANDS) == "MEDIUM" and band(66, BANDS) == "MEDIUM"
    assert band(67, BANDS) == "HIGH" and band(100, BANDS) == "HIGH"

def test_financing_need_workbook_case(bundle):
    rec = {"fn_external_need": 5, "fn_cashflow_constraint": 4,
           "fn_payment_preference": 5, "fn_support_requirement": 5}
    m = financing_need(rec, bundle.scoring["financing_need"])
    assert m.value == 93.75 and m.state == "computed"

def test_risk_profile_uses_50_50_rule(bundle):
    rec = {"rp_ownership": 5, "rp_technology": 4, "rp_battery": 5,
           "rp_residual": 5, "rp_maintenance": 4, "rp_downtime": 5}
    m = risk_profile(rec, bundle.scoring["risk_profile"])
    assert m.value == 95.0  # 0.5*5 + 0.5*4.6 = 4.8 -> (4.8-1)/4*100

def test_risk_profile_divergent_answers_not_simple_average(bundle):
    rec = {"rp_ownership": 5, "rp_technology": 1, "rp_battery": 1,
           "rp_residual": 1, "rp_maintenance": 1, "rp_downtime": 1}
    m = risk_profile(rec, bundle.scoring["risk_profile"])
    assert m.value == 50.0  # simple average of six would give 16.67

def test_missing_fields_are_insufficient_not_defaulted(bundle):
    m = financing_need({}, bundle.scoring["financing_need"])
    assert m.state == INSUFFICIENT
    assert set(m.missing) == {"fn_external_need", "fn_cashflow_constraint",
                              "fn_payment_preference", "fn_support_requirement"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `fpb.scoring` does not exist.

- [ ] **Step 3: Implement scoring.py**

```python
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
```

- [ ] **Step 4: Fill the scored fields into config**

`config/scoring.yaml` becomes (the economic-readiness and overall-fit keys are kept
from Task 1 because `validate_config` reads them; their weights are final, while the
`market_access`, `tco` and `cold_chain` blocks land in Tasks 5 and 7):

```yaml
config_version: "2026-01"
bands: {low: [0, 33], medium: [34, 66], high: [67, 100]}
financing_need:
  slugs: [fn_external_need, fn_cashflow_constraint, fn_payment_preference, fn_support_requirement]
  weights: [0.25, 0.25, 0.25, 0.25]
risk_profile:
  ownership_slug: rp_ownership
  tolerance_slugs: [rp_technology, rp_battery, rp_residual, rp_maintenance, rp_downtime]
  weights: [0.5, 0.5]
economic_readiness:
  weights: {tco_competitiveness: 0.5, investment_burden: 0.25, market_access: 0.25}
overall_fit:
  weights: {primary_scheme_fit: 0.4, economic_readiness: 0.25, financing_need_index: 0.2, readiness_context: 0.15}
```

`config/questionnaire.yaml` gains the six scored fields under their sections (types and aliases; full field list is owned by the ingestion plan — the engine plan needs only the slugs the engine consumes):

```yaml
spec_version: "2026-01"
sections:
  - id: financing_need
    fields:
      - {slug: fn_external_need, type: likert_5, required: true, scoring_role: financing_need}
      - {slug: fn_cashflow_constraint, type: likert_5, required: true, scoring_role: financing_need}
      - {slug: fn_payment_preference, type: likert_5, required: true, scoring_role: financing_need}
      - {slug: fn_support_requirement, type: likert_5, required: true, scoring_role: financing_need}
  - id: risk_profile
    fields:
      - {slug: rp_ownership, type: likert_5, required: true, scoring_role: risk_profile}
      - {slug: rp_technology, type: likert_5, required: true, scoring_role: risk_profile}
      - {slug: rp_battery, type: likert_5, required: true, scoring_role: risk_profile}
      - {slug: rp_residual, type: likert_5, required: true, scoring_role: risk_profile}
      - {slug: rp_maintenance, type: likert_5, required: true, scoring_role: risk_profile}
      - {slug: rp_downtime, type: likert_5, required: true, scoring_role: risk_profile}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_scoring.py tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fpb/scoring.py config tests/test_scoring.py
git commit -m "feat: financing need and risk profile scoring with 50/50 risk rule"
```

---

### Task 4: TCO engine

**Files:**
- Create: `src/fpb/tco.py`, `tests/test_tco.py`

**Interfaces:**
- Produces: `PowertrainInputs` (frozen dataclass: `capex_idr_m, subsidy_idr_m, energy_idr_km, maintenance_idr_m_yr, insurance_idr_m_yr, infra_idr_m, battery_idr_m, residual_idr_m, financing_idr_m`), `run(diesel, ev, annual_km, years, cc_capex_idr_m=0.0, cc_energy_idr_m_yr=0.0, apply_to=("ev","diesel")) -> TcoResult` where `TcoResult` holds `diesel: TcoTotals, ev: TcoTotals, competitiveness: Metric, investment_burden: Metric, operating_saving_pct: float, payback_years: float | None, break_even_km: float | None, recovered_within_horizon: bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tco.py`:

```python
import pytest
from fpb.tco import PowertrainInputs, run
from fpb.types import INSUFFICIENT

D = PowertrainInputs(500, 0, 906, 40, 15, 0, 0, 60, 30)
E = PowertrainInputs(850, 100, 450, 25, 12, 50, 100, 0, 50)

def test_workbook_totals_reproduced():
    r = run(D, E, 50000, 8)
    assert r.diesel.total_idr_m == pytest.approx(1272.4)
    assert r.ev.total_idr_m == pytest.approx(1426.0)
    assert r.diesel.cost_per_km == pytest.approx(3181, abs=1)
    assert r.ev.cost_per_km == pytest.approx(3565, abs=1)

def test_competitiveness_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.competitiveness.value == pytest.approx(75.85664885256209)

def test_investment_burden_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.investment_burden.value == pytest.approx(50.0)

def test_payback_and_saving_workbook_case():
    r = run(D, E, 50000, 8)
    assert r.operating_saving_pct == pytest.approx(0.4067796610169491)
    assert r.payback_years == pytest.approx(6.127450980392157)
    assert r.break_even_km == pytest.approx(306372.54901960783)
    assert r.recovered_within_horizon is True

def test_symmetric_diesel_formula_counts_diesel_battery_line():
    d2 = PowertrainInputs(500, 0, 906, 40, 15, 0, 35, 60, 30)
    r = run(d2, E, 50000, 8)
    assert r.diesel.total_idr_m == pytest.approx(1307.4)  # old sheet formula would keep 1272.4

def test_no_premium_means_no_burden():
    e = PowertrainInputs(400, 100, 450, 25, 12, 0, 0, 0, 0)   # net 300 < diesel net 500
    r = run(D, e, 50000, 8)
    assert r.investment_burden.value == 100.0

def test_zero_diesel_net_with_ev_premium_is_zero_burden_score():
    d = PowertrainInputs(0, 0, 906, 40, 15, 0, 0, 0, 0)
    r = run(d, E, 50000, 8)
    assert r.investment_burden.value == 0.0
    assert "diesel net CAPEX zero" in r.investment_burden.detail

def test_payback_beyond_horizon_flagged():
    e = PowertrainInputs(2000, 0, 450, 25, 12, 0, 0, 0, 0)
    r = run(D, e, 50000, 8)
    assert r.payback_years > 8
    assert r.recovered_within_horizon is False

def test_cold_chain_default_applies_to_both():
    r = run(D, E, 50000, 8, cc_capex_idr_m=50, cc_energy_idr_m_yr=25)
    both = r
    ev_only = run(D, E, 50000, 8, cc_capex_idr_m=50, cc_energy_idr_m_yr=25, apply_to=("ev",))
    assert both.ev.total_idr_m == pytest.approx(1426.0 + 250)     # 50 + 25*8
    assert both.diesel.total_idr_m == pytest.approx(1272.4 + 250)
    assert ev_only.diesel.total_idr_m == pytest.approx(1272.4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tco.py -v`
Expected: FAIL — `fpb.tco` does not exist.

- [ ] **Step 3: Implement tco.py**

```python
from __future__ import annotations
from dataclasses import dataclass
from .types import Metric, TcoTotals


@dataclass(frozen=True)
class PowertrainInputs:
    capex_idr_m: float
    subsidy_idr_m: float
    energy_idr_km: float
    maintenance_idr_m_yr: float
    insurance_idr_m_yr: float
    infra_idr_m: float
    battery_idr_m: float
    residual_idr_m: float
    financing_idr_m: float


@dataclass(frozen=True)
class TcoResult:
    diesel: TcoTotals
    ev: TcoTotals
    competitiveness: Metric
    investment_burden: Metric
    operating_saving_pct: float
    payback_years: float | None
    break_even_km: float | None
    recovered_within_horizon: bool


def _totals(p: PowertrainInputs, annual_km: float, years: float,
            add_capex: float, add_energy_yr: float) -> TcoTotals:
    energy = p.energy_idr_km * annual_km / 1e6 + add_energy_yr
    total = (p.capex_idr_m - p.subsidy_idr_m + add_capex
             + energy * years
             + p.maintenance_idr_m_yr * years
             + p.insurance_idr_m_yr * years
             + p.infra_idr_m + p.battery_idr_m
             - p.residual_idr_m + p.financing_idr_m)
    opex = energy + p.maintenance_idr_m_yr + p.insurance_idr_m_yr
    return TcoTotals(total, total * 1e6 / (annual_km * years), opex,
                     p.capex_idr_m - p.subsidy_idr_m)


def run(diesel: PowertrainInputs, ev: PowertrainInputs, annual_km: float, years: float,
        cc_capex_idr_m: float = 0.0, cc_energy_idr_m_yr: float = 0.0,
        apply_to: tuple[str, ...] = ("ev", "diesel")) -> TcoResult:
    d = _totals(diesel, annual_km, years,
                cc_capex_idr_m if "diesel" in apply_to else 0.0,
                cc_energy_idr_m_yr if "diesel" in apply_to else 0.0)
    e = _totals(ev, annual_km, years,
                cc_capex_idr_m if "ev" in apply_to else 0.0,
                cc_energy_idr_m_yr if "ev" in apply_to else 0.0)

    if e.cost_per_km <= d.cost_per_km:
        comp = Metric(100.0, detail="EV at or below diesel cost/km")
    else:
        ratio = e.cost_per_km / d.cost_per_km
        comp = Metric(0.0 if ratio >= 1.5 else 100 - (ratio - 1) * 200)

    if e.net_capex_idr_m <= d.net_capex_idr_m:
        burden = Metric(100.0, detail="no incremental CAPEX premium")
    elif d.net_capex_idr_m <= 0:
        burden = Metric(0.0, detail="diesel net CAPEX zero with positive EV premium")
    elif e.net_capex_idr_m >= 2 * d.net_capex_idr_m:
        burden = Metric(0.0)
    else:
        burden = Metric(100 - ((e.net_capex_idr_m / d.net_capex_idr_m) - 1) * 100)

    saving = (d.annual_opex_idr_m - e.annual_opex_idr_m) / d.annual_opex_idr_m
    incremental = e.net_capex_idr_m - d.net_capex_idr_m
    annual_saving = d.annual_opex_idr_m - e.annual_opex_idr_m
    if annual_saving > 0:
        payback = incremental / annual_saving
        break_even = incremental / (annual_saving / annual_km)
    else:
        payback = None
        break_even = None
    recovered = payback is not None and payback <= years
    return TcoResult(d, e, comp, burden, saving, payback, break_even, recovered)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tco.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/fpb/tco.py tests/test_tco.py
git commit -m "feat: symmetric TCO engine with burden guards and payback verdict"
```

---

### Task 5: Financing Market Access and Economic Readiness

**Files:**
- Create: `src/fpb/market_access.py`, `tests/test_market_access.py`
- Modify: `config/scoring.yaml`

**Interfaces:**
- Produces: `market_access(record, cfg) -> Metric` and `economic_readiness(tco_comp: Metric, burden: Metric, access: Metric, cfg) -> Metric`.

- [ ] **Step 1: Write the failing tests**

`tests/test_market_access.py`:

```python
import pytest
from fpb.market_access import economic_readiness, market_access
from fpb.types import INSUFFICIENT, Metric

LABELS = {"fs_green_loan": "High", "fs_lease_rent": "High", "fs_baas": "Medium",
          "fs_project_finance": "Low", "fs_blended_finance": "Medium"}

def test_market_access_reference_labels(bundle):
    m = market_access(LABELS, bundle.scoring["market_access"])
    assert m.value == pytest.approx(73.0)   # (100+100+66+33+66)/5

def test_market_access_case_insensitive_labels(bundle):
    m = market_access({k: v.lower() for k, v in LABELS.items()},
                      bundle.scoring["market_access"])
    assert m.value == pytest.approx(73.0)

def test_market_access_missing_field_is_insufficient(bundle):
    m = market_access({}, bundle.scoring["market_access"])
    assert m.state == INSUFFICIENT and len(m.missing) == 5

def test_economic_readiness_workbook_case(bundle):
    er = economic_readiness(Metric(75.85664885256209), Metric(50.0), Metric(73.0),
                            bundle.scoring["economic_readiness"])
    assert er.value == pytest.approx(68.67832442628105)

def test_economic_readiness_propagates_insufficient(bundle):
    er = economic_readiness(Metric.insufficient(("tco_x",)), Metric(50.0), Metric(73.0),
                            bundle.scoring["economic_readiness"])
    assert er.state == INSUFFICIENT and "tco_x" in er.missing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_market_access.py -v`
Expected: FAIL — `fpb.market_access` does not exist.

- [ ] **Step 3: Implement market_access.py**

```python
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


def economic_readiness(tco_comp: Metric, burden: Metric, access: Metric, cfg: dict) -> Metric:
    inputs = {"tco_competitiveness": tco_comp, "investment_burden": burden,
              "market_access": access}
    missing = tuple(s for m in inputs.values() for s in m.missing if m.state == INSUFFICIENT)
    if any(m.state == INSUFFICIENT for m in inputs.values()):
        return Metric.insufficient(missing)
    w = cfg["weights"]
    return Metric(w["tco_competitiveness"] * tco_comp.value
                  + w["investment_burden"] * burden.value
                  + w["market_access"] * access.value)
```

- [ ] **Step 4: Extend config/scoring.yaml**

`economic_readiness` already exists from Task 3 — do not add it again (a duplicate
top-level key in YAML is a hard error). Append only:

```yaml
market_access:
  scale: {none: 0, low: 33, medium: 66, high: 100}
  slugs: [fs_green_loan, fs_lease_rent, fs_baas, fs_project_finance, fs_blended_finance]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fpb/market_access.py config/scoring.yaml tests/test_market_access.py
git commit -m "feat: financing market access and economic readiness"
```

<!-- PLAN PART 2 -->

---

### Task 6: Scheme primitives and library

**Files:**
- Create: `src/fpb/schemes.py`, `tests/test_schemes.py`
- Modify: `config/schemes.yaml` (full library)

**Interfaces:**
- Consumes: `band(index, bands)` from Task 3, `SchemeResult` from Task 2.
- Produces: `eval_fit(rule, values, bands, scheme) -> tuple[float | None, str]`, `evaluate_scheme(scheme, values, weights, bands) -> SchemeResult`, `rank_schemes(results, schemes_by_id) -> list[SchemeResult]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_schemes.py`:

```python
import pytest
from fpb.schemes import eval_fit, evaluate_scheme, rank_schemes

BANDS = {"low": (0, 33), "medium": (34, 66), "high": (67, 100)}
W = {"need": 0.20, "risk": 0.20, "tco": 0.20, "operational": 0.15,
     "payment": 0.10, "support": 0.15}

# Workbook illustrative case: need 93.75 (HIGH), risk 95.0 (HIGH),
# EV 3565 vs diesel 3181 Rp/km, FN4 = 5
VALS = {"financing_need_index": 93.75, "risk_profile_index": 95.0,
        "fn_support_requirement": 5, "ev_cost_per_km": 3565.0,
        "diesel_cost_per_km": 3181.0}

# Sheet 'Scheme Match' H4:H11 — reproduced to the cent in the design phase.
SHEET = {"1": 63.5, "2": 63.0, "3": 75.25, "4": 82.5, "4a/4b": 83.75,
         "5": 92.25, "6": 89.0, "7": 86.75}

def test_all_eight_active_schemes_reproduce_sheet_totals(bundle):
    active = [s for s in bundle.schemes["schemes"] if s["status"] == "active"]
    assert len(active) == 8
    for s in active:
        r = evaluate_scheme(s, VALS, W, BANDS)
        assert r.total == pytest.approx(SHEET[s.scheme_id]), s.scheme_id

def test_rank_order_matches_sheet(bundle):
    active = [s for s in bundle.schemes["schemes"] if s["status"] == "active"]
    by_id = {s["id"]: s for s in active}
    ranked = rank_schemes([evaluate_scheme(s, VALS, W, BANDS) for s in active], by_id)
    order = {r.scheme_id: r.rank for r in ranked}
    assert order == {"5": 1, "6": 2, "7": 3, "4a/4b": 4, "4": 5, "3": 6,
                     "1": 7, "2": 8}
    assert [r.scheme_id for r in ranked if r.is_primary] == ["5"]

def test_fit_details_explain_the_number(bundle):
    s = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    r = evaluate_scheme(s, VALS, W, BANDS)
    assert "financing_need_index" in r.fit_details["need"]
    assert r.fit_details["need"].startswith("financing_need_index=93.75")
    assert "band=HIGH" in r.fit_details["need"]

def test_gap_closer_support_rule(bundle):
    s5 = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    low = dict(VALS, fn_support_requirement=3)
    r = evaluate_scheme(s5, low, W, BANDS)
    assert r.fits["support"] == 70          # FN4 < 4 -> gap-closer not triggered
    assert r.total == pytest.approx(92.25 - 0.15 * 30)

def test_draft_schemes_are_ineligible_but_visible(bundle):
    active = [s for s in bundle.schemes["schemes"] if s["status"] == "active"]
    drafts = [s for s in bundle.schemes["schemes"] if s["status"] == "draft"]
    assert {s["id"] for s in drafts} == {"gl", "pf"}
    results = [evaluate_scheme(s, VALS, W, BANDS)
               for s in active + drafts]
    ranked = rank_schemes(results, {s["id"]: s for s in active + drafts})
    for r in ranked:
        if r.status == "draft":
            assert r.rank == 0 and not r.is_primary

def test_tie_break_is_deterministic_and_visible():
    a = {"id": "a", "name": "A", "status": "active", "library_priority": 1,
         "fit": {d: {"constant": 80} for d in W} | {"total": {"weighted_sum": list(W)}}}
    b = dict(a, id="b", name="B", library_priority=2)
    ranked = rank_schemes([evaluate_scheme(a, {}, W, BANDS),
                           evaluate_scheme(b, {}, W, BANDS)], {"a": a, "b": b})
    assert [(r.scheme_id, r.rank) for r in ranked] == [("a", 1), ("b", 2)]
    assert ranked[0].is_primary and not ranked[1].is_primary
    assert ranked[0].tie_with == "b" and ranked[1].tie_with == "a"

def test_unavailable_input_yields_none_not_a_default(bundle):
    vals = dict(VALS, ev_cost_per_km=None, diesel_cost_per_km=None)
    s5 = next(x for x in bundle.schemes["schemes"] if x["id"] == "5")
    r = evaluate_scheme(s5, vals, W, BANDS)
    assert r.fits["tco"] is None and r.total is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_schemes.py -v`
Expected: FAIL — `fpb.schemes` does not exist.

- [ ] **Step 3: Implement schemes.py**

```python
from __future__ import annotations
from dataclasses import replace
from .scoring import band
from .types import SchemeResult


def eval_fit(rule: dict, values: dict, bands: dict, scheme: dict) -> tuple[float | None, str]:
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
        return float(score), f"{arg['source']}={v:g} band={b} target={arg['target']} -> {score}"

    if prim == "parity_or_gap":
        ev = values.get("ev_cost_per_km")
        dz = values.get("diesel_cost_per_km")
        if ev is None or dz is None:
            return None, "TCO cost/km unavailable"
        if ev <= dz:
            return float(arg["match"]), f"EV {ev:g} <= diesel {dz:g} Rp/km -> {arg['match']}"
        if scheme.get("closes_financing_gap"):
            return float(arg["gap_group"]), f"EV {ev:g} > diesel {dz:g}; closes financing gap -> {arg['gap_group']}"
        return float(arg["else"]), f"EV {ev:g} > diesel {dz:g}; no gap closure -> {arg['else']}"

    if prim == "support_fit":
        gc = arg["gap_closer"]
        if scheme.get("support_gap_closer"):
            v = values.get(gc["metric"])
            if v is None:
                return None, f"{gc['metric']} unavailable"
            hit = v >= gc["ge"]
            score = gc["then"] if hit else gc["else"]
            return float(score), f"gap-closer {gc['metric']}={v:g} >= {gc['ge']}? {hit} -> {score}"
        if scheme.get("green_eligible"):
            return float(arg["green_eligible"]), f"green-eligible channel -> {arg['green_eligible']}"
        return float(arg["default"]), f"default channel -> {arg['default']}"

    raise ValueError(f"unknown fit primitive: {prim}")


def evaluate_scheme(scheme: dict, values: dict, weights: dict, bands: dict) -> SchemeResult:
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
        details["total"] = "weighted_sum(" + ", ".join(f"{k}*{weights[k]}" for k in weights) + ")"
    return SchemeResult(scheme["id"], scheme["name"], scheme["status"], fits, details, total)


def rank_schemes(results: list[SchemeResult], schemes_by_id: dict) -> list[SchemeResult]:
    eligible = [r for r in results if r.status == "active" and r.total is not None]
    order = sorted(eligible,
                   key=lambda r: (-r.total, schemes_by_id[r.scheme_id]["library_priority"]))
    totals = [r.total for r in order]
    ranked = []
    for i, r in enumerate(order):
        tied = [o.scheme_id for o in order if o is not r and o.total == r.total]
        ranked.append(replace(r, rank=i + 1, is_primary=(i == 0),
                              tie_with=",".join(sorted(tied)) or None))
    for r in results:
        if r not in eligible:
            ranked.append(replace(r, rank=0, is_primary=False))
    return ranked
```

- [ ] **Step 4: Write the full scheme library**

`config/schemes.yaml` becomes:

```yaml
weights: {need: 0.20, risk: 0.20, tco: 0.20, operational: 0.15, payment: 0.10, support: 0.15}

schemes:
  - id: "1"
    name: "Conventional Ownership"
    library_priority: 1
    status: active
    closes_financing_gap: false
    green_eligible: false
    fit:
      need: {target_band: {source: financing_need_index, target: LOW, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: LOW, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 80}
      payment: {constant: 50}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "2"
    name: "Conversion / Recycle"
    library_priority: 2
    status: active
    closes_financing_gap: false
    green_eligible: false
    fit:
      need: {target_band: {source: financing_need_index, target: MEDIUM, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: MEDIUM, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 70}
      payment: {constant: 60}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "3"
    name: "Lease / Rent"
    library_priority: 3
    status: active
    closes_financing_gap: false
    green_eligible: true
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: MEDIUM, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 85}
      payment: {constant: 85}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "4"
    name: "Lease + Charging"
    library_priority: 4
    status: active
    closes_financing_gap: false
    green_eligible: true
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: HIGH, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 90}
      payment: {constant: 90}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "4a/4b"
    name: "Battery Risk Separation / BaaS"
    library_priority: 5
    status: active
    closes_financing_gap: false
    green_eligible: true
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: HIGH, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 95}
      payment: {constant: 95}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "5"
    name: "Blended Finance / VGF"
    library_priority: 6
    status: active
    closes_financing_gap: true
    green_eligible: false
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: HIGH, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 95}
      payment: {constant: 90}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "6"
    name: "Performance-based / FaaS"
    library_priority: 7
    status: active
    closes_financing_gap: true
    green_eligible: true
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: HIGH, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 90}
      payment: {constant: 95}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "7"
    name: "Total Outsourcing"
    library_priority: 8
    status: active
    closes_financing_gap: true
    green_eligible: false
    fit:
      need: {target_band: {source: financing_need_index, target: HIGH, match: 100, mismatch: 70}}
      risk: {target_band: {source: risk_profile_index, target: HIGH, match: 100, mismatch: 70}}
      tco: {parity_or_gap: {match: 100, gap_group: 70, else: 40}}
      operational: {constant: 85}
      payment: {constant: 95}
      support: {support_fit: {gap_closer: {metric: fn_support_requirement, ge: 4, then: 100, else: 70}, green_eligible: 80, default: 70}}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  # Draft entries exist only in the reference dashboard. The workbook library carries
  # no rules for them, and fit dimensions are calibrated per scheme, so they cannot be
  # scored. Excluded from primary-recommendation eligibility; visible in comparison
  # with placeholder fits from the dashboard's Scheme_Comparison sheet.
  - id: "gl"
    name: "Green Loan (w/ Partial Guarantee)"
    library_priority: 101
    status: draft
    closes_financing_gap: false
    green_eligible: true
    fit:
      need: {constant: 70}
      risk: {constant: 65}
      tco: {constant: 50}
      operational: {constant: 70}
      payment: {constant: 65}
      support: {constant: 80}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}

  - id: "pf"
    name: "Project Finance"
    library_priority: 102
    status: draft
    closes_financing_gap: false
    green_eligible: false
    fit:
      need: {constant: 50}
      risk: {constant: 40}
      tco: {constant: 55}
      operational: {constant: 60}
      payment: {constant: 40}
      support: {constant: 60}
      total: {weighted_sum: [need, risk, tco, operational, payment, support]}
```

**Config-validity note for Task 2's validator:** the active list is 8 schemes with
`library_priority` 1–8, unique; drafts have priorities 101–102 but `validate_config`
only checks uniqueness among `status == "active"`, so both drafts pass.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS across all suites. If `test_config.py` validation rejects the library, fix the YAML rather than loosening the validator.

- [ ] **Step 6: Commit**

```bash
git add src/fpb/schemes.py config/schemes.yaml tests/test_schemes.py
git commit -m "feat: five rule primitives and 10-scheme library reproducing workbook totals"
```

---

### Task 7: Engine orchestration

**Files:**
- Create: `src/fpb/engine.py`, `tests/test_engine.py`, `tests/fixtures/workbook_case.json`
- Modify: `config/scoring.yaml`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: `score(record: dict, bundle: ConfigBundle, context: dict) -> AssessmentResult`. `context` carries `consumer_readiness` and `city_cri` (each `float | None`), pre-populated by the ingestion layer.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py`:

```python
import json
import pytest
from pathlib import Path
from fpb.engine import score
from fpb.types import COMPUTED, INSUFFICIENT

REPO = Path(__file__).resolve().parents[1]
WORKBOOK = json.loads((REPO / "tests/fixtures/workbook_case.json").read_text())
CTX = {"consumer_readiness": 57, "city_cri": 40.4}

def test_workbook_case_end_to_end(bundle):
    r = score(WORKBOOK, bundle, CTX)
    m = r.metrics
    assert m["financing_need_index"].value == pytest.approx(93.75)
    assert m["risk_profile_index"].value == pytest.approx(95.0)
    assert m["tco_competitiveness"].value == pytest.approx(75.85664885256209)
    assert m["investment_burden"].value == pytest.approx(50.0)
    assert m["market_access"].value == pytest.approx(73.0)
    assert m["economic_readiness"].value == pytest.approx(68.67832442628105)
    assert r.overall.value == pytest.approx(80.12458110657028)
    assert r.primary_id == "5"
    assert r.spec_version == "2026-01" and r.config_version == "2026-01"

def test_tco_totals_match_sheet(bundle):
    r = score(WORKBOOK, bundle, CTX)
    assert r.tco["diesel"]["total_idr_m"] == pytest.approx(1272.4)
    assert r.tco["ev"]["total_idr_m"] == pytest.approx(1426.0)
    assert r.tco["diesel"]["cost_per_km"] == pytest.approx(3181, abs=1)
    assert r.tco["recovered_within_horizon"] is True

def test_missing_tco_degrades_specific_metrics_not_all(bundle):
    rec = {k: v for k, v in WORKBOOK.items() if not k.startswith(("tco_", "cc_"))}
    r = score(rec, bundle, CTX)
    assert r.metrics["financing_need_index"].state == COMPUTED
    assert r.metrics["risk_profile_index"].state == COMPUTED
    assert r.metrics["tco_competitiveness"].state == INSUFFICIENT
    assert r.metrics["economic_readiness"].state == INSUFFICIENT
    assert r.overall.state == INSUFFICIENT
    assert "tco_ev_capex" in r.overall.missing
    assert r.primary_id is None
    assert all(s.total is None for s in r.schemes)

def test_missing_readiness_context_is_reported(bundle):
    r = score(WORKBOOK, bundle, {"consumer_readiness": None, "city_cri": 40.4})
    assert r.metrics["readiness_context"].state == INSUFFICIENT
    assert "consumer_readiness" in r.metrics["readiness_context"].missing
    assert r.overall.state == INSUFFICIENT

def test_draft_schemes_never_primary(bundle):
    r = score(WORKBOOK, bundle, CTX)
    ids = {s.scheme_id for s in r.schemes}
    assert {"gl", "pf"} <= ids
    assert all(not s.is_primary for s in r.schemes if s.status == "draft")

def test_versions_are_stamped(bundle):
    r = score(WORKBOOK, bundle, CTX)
    assert r.spec_version and r.config_version
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_engine.py -v`
Expected: FAIL — `fpb.engine` does not exist.

- [ ] **Step 3: Implement engine.py**

```python
from __future__ import annotations
from dataclasses import asdict
from .config import ConfigBundle
from .market_access import economic_readiness, market_access
from .schemes import evaluate_scheme, rank_schemes
from .scoring import financing_need, risk_profile
from .tco import PowertrainInputs, run as run_tco
from .types import COMPUTED, INSUFFICIENT, AssessmentResult, Metric


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
    needed = ([f"{p}{f}" for p in (t["diesel_prefix"], t["ev_prefix"]) for f in t["fields"]]
              + [t["annual_km_slug"], t["years_slug"]])
    missing = sorted(x for x in needed if record.get(x) is None)
    if missing:
        tco_block = {"state": INSUFFICIENT, "missing": missing}
        comp = burden = Metric.insufficient(tuple(missing))
    else:
        cc = s["cold_chain"]
        res = run_tco(
            PowertrainInputs(*[_f(record, t["diesel_prefix"] + f) for f in t["fields"]]),
            PowertrainInputs(*[_f(record, t["ev_prefix"] + f) for f in t["fields"]]),
            _f(record, t["annual_km_slug"]), _f(record, t["years_slug"]),
            _f(record, cc["capex_slug"]) or 0.0,
            _f(record, cc["energy_slug"]) or 0.0,
            tuple(cc["apply_to"]),
        )
        tco_block = {"diesel": asdict(res.diesel), "ev": asdict(res.ev),
                     "operating_saving_pct": res.operating_saving_pct,
                     "payback_years": res.payback_years,
                     "break_even_km": res.break_even_km,
                     "recovered_within_horizon": res.recovered_within_horizon,
                     "cold_chain_apply_to": list(cc["apply_to"])}
        comp, burden = res.competitiveness, res.investment_burden
        if not res.recovered_within_horizon:
            warnings.append("EV CAPEX premium is not recovered within the assessment horizon")
    metrics["tco_competitiveness"] = comp
    metrics["investment_burden"] = burden

    consumer = _f(context, "consumer_readiness") if context.get("consumer_readiness") is not None else None
    cri = _f(context, "city_cri") if context.get("city_cri") is not None else None
    if consumer is None or cri is None:
        miss = tuple(x for x, v in (("consumer_readiness", consumer), ("city_cri", cri)) if v is None)
        readiness = Metric.insufficient(miss)
    else:
        readiness = Metric((consumer + cri) / 2)
    metrics["readiness_context"] = readiness

    metrics["economic_readiness"] = economic_readiness(
        comp, burden, metrics["market_access"], s["economic_readiness"])

    values = {
        "financing_need_index": metrics["financing_need_index"].value,
        "risk_profile_index": metrics["risk_profile_index"].value,
        "fn_support_requirement": _f(record, "fn_support_requirement"),
        "ev_cost_per_km": (tco_block.get("ev") or {}).get("cost_per_km"),
        "diesel_cost_per_km": (tco_block.get("diesel") or {}).get("cost_per_km"),
    }
    weights = bundle.schemes["weights"]
    by_id = {x["id"]: x for x in bundle.schemes["schemes"]}
    evaluated = [evaluate_scheme(x, values, weights, s["bands"]) for x in by_id.values()]
    ranked = rank_schemes(evaluated, by_id)
    primary = next((r for r in ranked if r.is_primary), None)

    inputs = {
        "primary_scheme_fit": Metric(primary.total) if primary else Metric.insufficient(("primary_scheme_fit",)),
        "economic_readiness": metrics["economic_readiness"],
        "financing_need_index": metrics["financing_need_index"],
        "readiness_context": readiness,
    }
    if primary is None and any(s.total is None for s in ranked):
        warnings.append("no scheme could be fully scored; recommendation withheld")
    gap = tuple(sorted({m for mt in inputs.values() for m in mt.missing}))
    overall = (Metric.insufficient(gap) if gap else
               Metric(sum(w * inputs[k].value for k, w in s["overall_fit"]["weights"].items())))
    metrics["overall_financing_fit"] = overall

    return AssessmentResult(bundle.spec_version, bundle.config_version, metrics,
                            tco_block, ranked, overall,
                            primary.scheme_id if primary else None, warnings)
```

- [ ] **Step 4: Extend config/scoring.yaml**

`overall_fit` already exists from Task 3 — do not add it again. Append only:

```yaml
tco:
  annual_km_slug: tco_annual_km
  years_slug: tco_years
  diesel_prefix: tco_diesel_
  ev_prefix: tco_ev_
  fields: [capex, subsidy, energy_idr_km, maintenance_idr_m_yr, insurance_idr_m_yr,
           infra_idr_m, battery_idr_m, residual_idr_m, financing_idr_m]
cold_chain:
  capex_slug: cc_capex_idr_m
  energy_slug: cc_energy_idr_m_yr
  apply_to: [ev, diesel]
```

- [ ] **Step 5: Create the golden fixture**

`tests/fixtures/workbook_case.json` — the workbook's illustrative case, the only case in the source files with complete raw inputs:

```json
{
  "fn_external_need": 5, "fn_cashflow_constraint": 4,
  "fn_payment_preference": 5, "fn_support_requirement": 5,
  "rp_ownership": 5, "rp_technology": 4, "rp_battery": 5,
  "rp_residual": 5, "rp_maintenance": 4, "rp_downtime": 5,
  "tco_annual_km": 50000, "tco_years": 8,
  "tco_diesel_capex": 500, "tco_diesel_subsidy": 0, "tco_diesel_energy_idr_km": 906,
  "tco_diesel_maintenance_idr_m_yr": 40, "tco_diesel_insurance_idr_m_yr": 15,
  "tco_diesel_infra_idr_m": 0, "tco_diesel_battery_idr_m": 0,
  "tco_diesel_residual_idr_m": 60, "tco_diesel_financing_idr_m": 30,
  "tco_ev_capex": 850, "tco_ev_subsidy": 100, "tco_ev_energy_idr_km": 450,
  "tco_ev_maintenance_idr_m_yr": 25, "tco_ev_insurance_idr_m_yr": 12,
  "tco_ev_infra_idr_m": 50, "tco_ev_battery_idr_m": 100,
  "tco_ev_residual_idr_m": 0, "tco_ev_financing_idr_m": 50,
  "fs_green_loan": "High", "fs_lease_rent": "High", "fs_baas": "Medium",
  "fs_project_finance": "Low", "fs_blended_finance": "Medium"
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/fpb/engine.py config/scoring.yaml tests/fixtures tests/test_engine.py
git commit -m "feat: engine orchestration with overall fit and per-metric degradation"
```

---

### Task 8: Property tests

**Files:**
- Create: `tests/test_properties.py`

**Interfaces:**
- Consumes: `score`, `evaluate_scheme`, `rank_schemes` from Tasks 3–7.
- Produces: nothing consumed downstream; these are the invariant guards from spec §10.3.

- [ ] **Step 1: Write the property tests**

`tests/test_properties.py`:

```python
import random
from fpb.engine import score
from fpb.types import COMPUTED, INSUFFICIENT, NOT_APPLICABLE

STATES = {COMPUTED, INSUFFICIENT, NOT_APPLICABLE}
TCO_SLUGS = ["tco_annual_km", "tco_years"] + [
    f"{p}{f}" for p in ("tco_diesel_", "tco_ev_")
    for f in ("capex", "subsidy", "energy_idr_km", "maintenance_idr_m_yr",
              "insurance_idr_m_yr", "infra_idr_m", "battery_idr_m",
              "residual_idr_m", "financing_idr_m")]
FS = ["fs_green_loan", "fs_lease_rent", "fs_baas", "fs_project_finance", "fs_blended_finance"]
FN = ["fn_external_need", "fn_cashflow_constraint", "fn_payment_preference", "fn_support_requirement"]
RP = ["rp_ownership", "rp_technology", "rp_battery", "rp_residual", "rp_maintenance", "rp_downtime"]


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
        r = score(_record(rng), bundle,
                  {"consumer_readiness": rng.randint(0, 100), "city_cri": rng.randint(0, 100)})
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
        # equal totals are still strictly ordered by the library_priority tie-break
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

    base = _score(_record(random.Random(7)), bundle, {"consumer_readiness": 60, "city_cri": 50})
    bumped_schemes = deepcopy(bundle.schemes)
    five = next(x for x in bumped_schemes["schemes"] if x["id"] == "5")
    five["fit"]["operational"]["constant"] = 100
    alt_bundle = SimpleNamespace(spec_version=bundle.spec_version,
                                 config_version=bundle.config_version,
                                 questionnaire=bundle.questionnaire,
                                 scoring=bundle.scoring,
                                 schemes=bumped_schemes)
    alt = _score(_record(random.Random(7)), alt_bundle, {"consumer_readiness": 60, "city_cri": 50})
    b = next(x for x in base.schemes if x.scheme_id == "5")
    a = next(x for x in alt.schemes if x.scheme_id == "5")
    if b.total is not None and b.fits["operational"] is not None:
        assert a.total > b.total
```

- [ ] **Step 2: Fix the missing import in the test file**

`pytest` is used by `test_weights_sum_to_one` but not imported at the top of
`tests/test_properties.py`; the file's first line in Step 1 is `import random`, so add
`import pytest` as the second line before running the suite.

- [ ] **Step 3: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_properties.py -v`
Expected: PASS. The property suite is heavier (200 full scoring runs); if it feels
slow locally, that is expected and acceptable — it is a guard, not a unit test.

- [ ] **Step 4: Commit**

```bash
git add tests/test_properties.py
git commit -m "test: engine invariants over 200 randomized cases"
```

---

### Task 9: Command-line entry point

**Files:**
- Create: `src/fpb/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `validate_config` from Task 1/2, `score` from Task 7.
- Produces: `python -m fpb.cli score --config config --record <file> [--context <file>]` printing the `AssessmentResult` as JSON to stdout; exit code 3 when config validation fails, 0 otherwise.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_cli_scores_workbook_case(bundle, tmp_path):
    ctx = tmp_path / "ctx.json"
    ctx.write_text(json.dumps({"consumer_readiness": 57, "city_cri": 40.4}))
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    out = subprocess.run(
        [sys.executable, "-m", "fpb.cli", "score",
         "--config", str(REPO / "config"),
         "--record", str(REPO / "tests/fixtures/workbook_case.json"),
         "--context", str(ctx)],
        capture_output=True, text=True, cwd=REPO, env=env, check=True).stdout
    r = json.loads(out)
    assert r["primary_id"] == "5"
    assert r["metrics"]["overall_financing_fit"]["value"] == pytest.approx(80.12458110657028)
    assert r["metrics"]["overall_financing_fit"]["state"] == "computed"
    assert r["config_version"] == "2026-01"


def test_cli_config_validation_failure_exits_3(bundle, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name, data in (("questionnaire", bundle.questionnaire),
                       ("schemes", bundle.schemes),
                       ("scoring", bundle.scoring)):
        import yaml
        yaml.safe_dump(data, (cfg / f"{name}.yaml").open("w"))
    bad = yaml.safe_load((cfg / "scoring.yaml").read_text())
    bad["financing_need"]["weights"][0] = 0.10
    yaml.safe_dump(bad, (cfg / "scoring.yaml").open("w"))
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "fpb.cli", "score",
         "--config", str(cfg),
         "--record", str(REPO / "tests/fixtures/workbook_case.json")],
        capture_output=True, text=True, cwd=REPO, env=env)
    assert proc.returncode == 3
    assert "config:" in proc.stderr
```

- [ ] **Step 2: Install the package editably (once, for the subprocess)**

Run: `.venv/bin/pip install -e .`
Expected: success. This is the only step requiring network; if the environment is
offline, the tests still pass because `PYTHONPATH=src` is set in the subprocess env —
editable install is for ad-hoc CLI use, not for the suite.

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `fpb.cli` does not exist.

- [ ] **Step 4: Implement cli.py**

```python
from __future__ import annotations
import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .config import load_config, validate_config
from .engine import score


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fpb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score")
    p.add_argument("--config", type=Path, default=Path("config"))
    p.add_argument("--record", type=Path, required=True)
    p.add_argument("--context", type=Path)
    args = ap.parse_args(argv)

    bundle = load_config(args.config)
    problems = validate_config(bundle)
    if problems:
        for x in problems:
            print(f"config: {x}", file=sys.stderr)
        return 3

    record = json.loads(args.record.read_text())
    context = json.loads(args.context.read_text()) if args.context else {}
    result = score(record, bundle, context)
    print(json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`dataclasses.asdict` recurses into the frozen dataclasses; `Metric` becomes
`{"value": ..., "state": ..., "missing": [...], "detail": ...}` and `SchemeResult`
becomes a plain dict, so the JSON matches what the UI plan will consume.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS across all suites.

- [ ] **Step 6: Smoke the CLI by hand**

Run: `.venv/bin/python -m fpb.cli score --config config --record tests/fixtures/workbook_case.json --context <(printf '{"consumer_readiness":57,"city_cri":40.4}')`
Expected: JSON with `"primary_id": "5"` and `"overall_financing_fit"` value ≈ 80.12.

- [ ] **Step 7: Commit**

```bash
git add src/fpb/cli.py tests/test_cli.py
git commit -m "feat: score subcommand emitting AssessmentResult as JSON"
```

---

## Self-review notes

**Spec coverage.** This plan implements spec §6 (scoring engine), §7 (scheme library),
§9 (error handling) and §10 (testing). Deliberately **not** covered here, because they
belong to separate plans in the engine → ingestion → UI split: spec §5 ingestion
(readers, resolver, validation UI), §8 storage and frozen results, §4's `data_library`,
`ui` and `export` units, and §12's `config/reference_data/`.

**Deferred within this plan.** Spec §6.5's "insurance and tax default from the
open-data library when blank" requires the reference-data store, so it lands with
ingestion; until then a missing `tco_*_insurance_idr_m_yr` is reported as
insufficient input, which is the safe direction. Spec §9.2's `not_applicable` state is
defined in `types.py` and admitted by the property test, but no engine path emits it
yet — routing is resolved during ingestion.

**Type consistency.** `Metric` states compare against the string constants in
`types.py` (`COMPUTED`, `INSUFFICIENT`), and tests use both the constant and the
literal `"computed"` — same value. `evaluate_scheme(scheme, values, weights, bands)`
has identical argument order in Tasks 6 and 7. `PowertrainInputs(...)` positional
argument order in Task 7 matches the dataclass field order in Task 4 and the config
`tco.fields` list exactly. `rank_schemes` returns eligible results first (rank 1..n)
then ineligible ones (rank 0), which both the Task 6 and Task 7 tests rely on.

**Placeholder scan.** No TBD/TODO. The two draft schemes are intentional data
(boxed comment in the YAML), not placeholders in the plan. Every step carries real
code or an exact command.
