# Financing Playbook — Streamlit Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Streamlit dashboard that ingests a questionnaire (Excel respondent form, JSON record, or bundled example), validates it against an expanded questionnaire config, runs the existing engine, and renders the assessment detail view.

**Architecture:** New pure modules (`ingest.py`, `validate.py`, `display.py`) sit upstream/downstream of the untouched engine; `app.py` is the only file importing Streamlit. Config gains per-field metadata (labels, units, bounds, aliases, options) so the questionnaire can change without touching Python.

**Tech Stack:** Python 3.11, Streamlit, pandas, openpyxl, PyYAML, pytest (AppTest for the UI smoke test).

**Spec:** `docs/superpowers/specs/2026-08-29-financing-playbook-dashboard-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- Engine module tree (`src/fpb/engine.py`, `scoring.py`, `tco.py`, `market_access.py`, `schemes.py`, `config.py`, `types.py`) must not import `streamlit`, `pandas`, `openpyxl`, or `sqlite3`. Do not modify these files.
- `config/scoring.yaml` and `config/schemes.yaml` are byte-identical; only `config/questionnaire.yaml` grows.
- The engine's `market_access` scale is `{none: 0, low: 33, medium: 66, high: 100}` and expects literal strings (any case): `None`, `Low`, `Medium`, `High`. Invalid choice values must never reach the engine (it would raise `KeyError`).
- Nothing is silently defaulted: invalid values are excluded from the record, the engine reports `insufficient_inputs`, and the UI shows every issue.
- All 41 existing tests keep passing.
- Every task ends with a commit.

## File Structure

```
pyproject.toml                     Modify: openpyxl core, [ui] extra
config/questionnaire.yaml          Modify: expand 10 fields -> 37 fields
src/fpb/input_types.py             Create: FieldIssue, CaseInput
src/fpb/validate.py                Create: validate_value, validate_record
src/fpb/ingest.py                  Create: read_excel_form, read_json_record, build_case_input
src/fpb/display.py                 Create: fmt_metric, fmt_rupiah, state_badge, scheme_frame
src/fpb/app.py                     Create: Streamlit UI (only streamlit import)
tests/test_validate.py             Create
tests/test_ingest.py               Create
tests/test_display.py              Create
tests/test_app.py                  Create: AppTest smoke
tests/test_config.py               Modify: engine-slug coverage, still validates
README.md                          Modify: "Run the web app" section
```

---

### Task 1: Dependencies and config file metadata expansion

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/questionnaire.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `openpyxl` in core deps; `[ui]` extra with `streamlit` + `pandas`; questionnaire config with 37 fields, each carrying `type`, `label`, `section`, `required`, and optionally `unit`, `min`, `max`, `options`, `aliases.form_column_d`, `context_source`.

- [ ] **Step 1: Update `pyproject.toml`**

```toml
dependencies = ["pyyaml>=6", "openpyxl>=3.1"]

[project.optional-dependencies]
dev = ["pytest>=8"]
ui = ["streamlit>=1.36", "pandas>=2"]
```

- [ ] **Step 2: Install UI deps into the venv (network required)**

Run: `python -m pip install -e ".[dev,ui]"`
Expected: openpyxl, streamlit, pandas resolve and install.

- [ ] **Step 3: Expand `config/questionnaire.yaml`**

Replace the file contents with this (keeps the existing two sections byte-compatible in shape and adds three more):

```yaml
spec_version: "2026-01"
sections:
  - id: financing_need
    title: "2. Financing Need"
    fields:
      - {slug: fn_external_need, type: likert_5, required: true, scoring_role: financing_need, label: "External Financing Need", section: "2. Financing Need", aliases: {form_column_d: "2.1"}}
      - {slug: fn_cashflow_constraint, type: likert_5, required: true, scoring_role: financing_need, label: "Cash-flow / Budget Constraint", section: "2. Financing Need", aliases: {form_column_d: "2.2"}}
      - {slug: fn_payment_preference, type: likert_5, required: true, scoring_role: financing_need, label: "Payment Preference", section: "2. Financing Need", aliases: {form_column_d: "2.3"}}
      - {slug: fn_support_requirement, type: likert_5, required: true, scoring_role: financing_need, label: "External Support Requirement", section: "2. Financing Need", aliases: {form_column_d: "2.4"}}
  - id: risk_profile
    title: "3. Risk Profile"
    fields:
      - {slug: rp_ownership, type: likert_5, required: true, scoring_role: risk_profile, label: "Ownership Preference", section: "3. Risk Profile", aliases: {form_column_d: "3.1"}}
      - {slug: rp_technology, type: likert_5, required: true, scoring_role: risk_profile, label: "Technology Risk Tolerance", section: "3. Risk Profile", aliases: {form_column_d: "3.2"}}
      - {slug: rp_battery, type: likert_5, required: true, scoring_role: risk_profile, label: "Battery Risk Tolerance", section: "3. Risk Profile", aliases: {form_column_d: "3.3"}}
      - {slug: rp_residual, type: likert_5, required: true, scoring_role: risk_profile, label: "Residual Value Risk Tolerance", section: "3. Risk Profile", aliases: {form_column_d: "3.4"}}
      - {slug: rp_maintenance, type: likert_5, required: true, scoring_role: risk_profile, label: "Maintenance Risk Tolerance", section: "3. Risk Profile", aliases: {form_column_d: "3.5"}}
      - {slug: rp_downtime, type: likert_5, required: true, scoring_role: risk_profile, label: "Performance / Downtime Risk Tolerance", section: "3. Risk Profile", aliases: {form_column_d: "3.6"}}
  - id: tco
    title: "4-6. TCO Inputs"
    fields:
      - {slug: tco_annual_km, type: numeric, required: true, label: "Annual Mileage", section: "4. Operation", unit: "km/year", min: 0, max: 1000000, aliases: {form_column_d: "4.4"}}
      - {slug: tco_years, type: numeric, required: true, label: "Expected Vehicle Lifetime", section: "4. Operation", unit: "years", min: 1, max: 30, aliases: {form_column_d: "4.5"}}
      - {slug: tco_diesel_capex, type: numeric, required: true, label: "Diesel Vehicle Purchase CAPEX", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "5.1"}}
      - {slug: tco_diesel_subsidy, type: numeric, required: true, label: "Diesel Subsidy / Incentive", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "5.2"}}
      - {slug: tco_diesel_energy_idr_km, type: numeric, required: true, label: "Diesel Energy / Fuel Cost per km", section: "5. TCO Diesel", unit: "Rp/km", min: 0, max: 100000, aliases: {form_column_d: "5.3"}}
      - {slug: tco_diesel_maintenance_idr_m_yr, type: numeric, required: true, label: "Diesel Maintenance Cost per Year", section: "5. TCO Diesel", unit: "Rp million/yr", min: 0, max: 100000, aliases: {form_column_d: "5.4"}}
      - {slug: tco_diesel_insurance_idr_m_yr, type: numeric, required: true, label: "Diesel Insurance + Tax per Year", section: "5. TCO Diesel", unit: "Rp million/yr", min: 0, max: 100000, aliases: {form_column_d: "5.5"}}
      - {slug: tco_diesel_infra_idr_m, type: numeric, required: true, label: "Diesel Refuelling Infrastructure CAPEX", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "5.6"}}
      - {slug: tco_diesel_battery_idr_m, type: numeric, required: true, label: "Diesel Battery Replacement Cost", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000}
      - {slug: tco_diesel_residual_idr_m, type: numeric, required: true, label: "Diesel Residual Value at End of Life", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "5.7"}}
      - {slug: tco_diesel_financing_idr_m, type: numeric, required: true, label: "Diesel Financing Cost", section: "5. TCO Diesel", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "5.8"}}
      - {slug: tco_ev_capex, type: numeric, required: true, label: "EV Vehicle Purchase CAPEX", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.1"}}
      - {slug: tco_ev_subsidy, type: numeric, required: true, label: "EV Subsidy / Incentive", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.2"}}
      - {slug: tco_ev_energy_idr_km, type: numeric, required: true, label: "EV Energy Cost per km", section: "6. TCO EV", unit: "Rp/km", min: 0, max: 100000, aliases: {form_column_d: "6.3"}}
      - {slug: tco_ev_maintenance_idr_m_yr, type: numeric, required: true, label: "EV Maintenance Cost per Year", section: "6. TCO EV", unit: "Rp million/yr", min: 0, max: 100000, aliases: {form_column_d: "6.4"}}
      - {slug: tco_ev_insurance_idr_m_yr, type: numeric, required: true, label: "EV Insurance + Tax per Year", section: "6. TCO EV", unit: "Rp million/yr", min: 0, max: 100000, aliases: {form_column_d: "6.5"}}
      - {slug: tco_ev_infra_idr_m, type: numeric, required: true, label: "Charging Infrastructure CAPEX", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.6"}}
      - {slug: tco_ev_battery_idr_m, type: numeric, required: true, label: "Battery Replacement Cost", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.7"}}
      - {slug: tco_ev_residual_idr_m, type: numeric, required: true, label: "EV Residual Value at End of Life", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.8"}}
      - {slug: tco_ev_financing_idr_m, type: numeric, required: true, label: "EV Financing Cost", section: "6. TCO EV", unit: "Rp million", min: 0, max: 100000, aliases: {form_column_d: "6.9"}}
  - id: market_access
    title: "8. Financing Supply"
    fields:
      - {slug: fs_green_loan, type: choice, required: true, label: "Access to Bank / Green Loan", section: "8. Financing Supply", options: [Low, Medium, High, None], aliases: {form_column_d: "8.1"}}
      - {slug: fs_lease_rent, type: choice, required: true, label: "Lease / Rent Availability", section: "8. Financing Supply", options: [Low, Medium, High, None], aliases: {form_column_d: "8.2"}}
      - {slug: fs_baas, type: choice, required: true, label: "Battery-as-a-Service Availability", section: "8. Financing Supply", options: [Low, Medium, High, None], aliases: {form_column_d: "8.3"}}
      - {slug: fs_project_finance, type: choice, required: true, label: "Project Finance Availability", section: "8. Financing Supply", options: [Low, Medium, High, None], aliases: {form_column_d: "8.4"}}
      - {slug: fs_blended_finance, type: choice, required: true, label: "Blended Finance / VGF Availability", section: "8. Financing Supply", options: [Low, Medium, High, None], aliases: {form_column_d: "8.5"}}
  - id: readiness_context
    title: "1. Existing Readiness"
    fields:
      - {slug: consumer_readiness, type: numeric, required: false, context_source: true, label: "Consumer Readiness Score", section: "1. Existing Readiness", unit: "0-100", min: 0, max: 100, aliases: {form_column_d: "1.1"}}
      - {slug: city_cri, type: numeric, required: false, context_source: true, label: "City / Ecosystem CRI", section: "1. Existing Readiness", unit: "0-100", min: 0, max: 100, aliases: {form_column_d: "1.3"}}
```

- [ ] **Step 4: Add a config coverage test**

Append to `tests/test_config.py`:

```python
ENGINE_TCOS = [
    f"{p}{f}" for p in ("tco_diesel_", "tco_ev_")
    for f in ("capex", "subsidy", "energy_idr_km", "maintenance_idr_m_yr",
              "insurance_idr_m_yr", "infra_idr_m", "battery_idr_m",
              "residual_idr_m", "financing_idr_m")
]
ENGINE_SLUGS = (
    ["fn_external_need", "fn_cashflow_constraint", "fn_payment_preference",
     "fn_support_requirement"]
    + ["rp_ownership", "rp_technology", "rp_battery", "rp_residual",
       "rp_maintenance", "rp_downtime"]
    + ["tco_annual_km", "tco_years"]
    + ENGINE_TCOS
    + ["fs_green_loan", "fs_lease_rent", "fs_baas", "fs_project_finance",
       "fs_blended_finance"]
)


def test_questionnaire_covers_all_engine_slugs(bundle):
    slugs = {
        f["slug"]
        for sec in bundle.questionnaire["sections"]
        for f in sec["fields"]
    }
    assert set(ENGINE_SLUGS) <= slugs


def test_every_field_has_label_and_type(bundle):
    for sec in bundle.questionnaire["sections"]:
        for f in sec["fields"]:
            assert f["type"] in {"likert_5", "numeric", "choice", "text", "date"}
            assert f["label"]
            if f["type"] == "choice":
                assert f["options"]
```

- [ ] **Step 5: Run the config tests and full suite**

Run: `python -m pytest tests/test_config.py -v` then `python -m pytest -q`
Expected: new tests pass; all previous tests still pass (config shape change is additive).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml config/questionnaire.yaml tests/test_config.py
git commit -m "feat: expand questionnaire config and add UI dependencies"
```

---

### Task 2: Input types and validation

**Files:**
- Create: `src/fpb/input_types.py`
- Create: `src/fpb/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: config `sections[].fields[]` shape from Task 1.
- Produces:
  - `input_types.FieldIssue(slug, label, message, value)`
  - `input_types.CaseInput(record, context, issues, source)`
  - `validate.iter_fields(questionnaire) -> Iterator[dict]`
  - `validate.validate_value(field, value) -> list[FieldIssue]`
  - `validate.validate_record(values, questionnaire) -> tuple[FieldIssue, ...]` (missing-required included)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validate.py`:

```python
import pytest

from fpb.validate import iter_fields, validate_record, validate_value


def _field(**kw):
    base = {"slug": "x", "type": "likert_5", "required": False,
            "label": "X", "section": "S"}
    base.update(kw)
    return base


def test_likert_accepts_int_one_to_five():
    assert validate_value(_field(), 3) == []


def test_likert_rejects_out_of_range():
    issues = validate_value(_field(), 6)
    assert len(issues) == 1
    assert "1-5" in issues[0].message


def test_numeric_accepts_float_and_int():
    f = _field(type="numeric", min=0, max=100)
    assert validate_value(f, 12) == []
    assert validate_value(f, 12.5) == []


def test_numeric_rejects_non_numeric():
    f = _field(type="numeric", min=0, max=100)
    issues = validate_value(f, "abc")
    assert issues and "number" in issues[0].message


def test_numeric_rejects_out_of_range():
    f = _field(type="numeric", min=0, max=100)
    assert validate_value(f, -1)
    assert validate_value(f, 101)


def test_choice_rejects_unknown_case_insensitively():
    f = _field(type="choice", options=["Low", "Medium", "High", "None"])
    assert validate_value(f, "Low") == []
    assert validate_value(f, "low") == []
    assert validate_value(f, "hight")


def test_required_missing_is_an_issue():
    issues = validate_record({}, {"sections": [{"fields": [_field(required=True)]}]})
    assert len(issues) == 1
    assert "required" in issues[0].message


def test_iter_fields_flattens_sections():
    q = {"sections": [{"fields": [_field(slug="a")]}, {"fields": [_field(slug="b")]}]}
    assert [f["slug"] for f in iter_fields(q)] == ["a", "b"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_validate.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/fpb/input_types.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldIssue:
    slug: str
    label: str
    message: str
    value: object | None = None


@dataclass(frozen=True)
class CaseInput:
    record: dict[str, object]
    context: dict[str, object]
    issues: tuple[FieldIssue, ...]
    source: str
```

- [ ] **Step 4: Implement `src/fpb/validate.py`**

```python
from __future__ import annotations

from collections.abc import Iterator

from .input_types import FieldIssue


def iter_fields(questionnaire: dict) -> Iterator[dict]:
    for section in questionnaire["sections"]:
        yield from section["fields"]


def validate_value(field: dict, value: object) -> list[FieldIssue]:
    slug = field["slug"]
    label = field.get("label", slug)
    ftype = field.get("type")
    raw = "" if value is None else str(value).strip()

    if ftype == "likert_5":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return [FieldIssue(slug, label, f"{label} must be an integer 1-5", value)]
        if not 1 <= v <= 5:
            return [FieldIssue(slug, label, f"{label} must be an integer 1-5, got {value!r}", value)]
        return []

    if ftype == "numeric":
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return [FieldIssue(slug, label, f"{label} must be a number", value)]
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and v < lo:
            return [FieldIssue(slug, label, f"{label} must be >= {lo}, got {value!r}", value)]
        if hi is not None and v > hi:
            return [FieldIssue(slug, label, f"{label} must be <= {hi}, got {value!r}", value)]
        return []

    if ftype == "choice":
        allowed = {str(o).strip().lower() for o in field.get("options", [])}
        if raw.lower() not in allowed:
            return [FieldIssue(slug, label, f"{label} must be one of {sorted(allowed)}, got {value!r}", value)]
        return []

    return []


def validate_record(values: dict, questionnaire: dict) -> tuple[FieldIssue, ...]:
    issues: list[FieldIssue] = []
    for field in iter_fields(questionnaire):
        slug = field["slug"]
        if slug not in values:
            if field.get("required"):
                issues.append(
                    FieldIssue(slug, field.get("label", slug), f"Required field {slug} is missing")
                )
            continue
        issues.extend(validate_value(field, values[slug]))
    return tuple(issues)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_validate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/fpb/input_types.py src/fpb/validate.py tests/test_validate.py
git commit -m "feat: questionnaire record validation"
```

---

### Task 3: Ingestion (Excel form reader, JSON reader, resolver)

**Files:**
- Create: `src/fpb/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `validate.validate_record`, `validate.iter_fields`, `input_types.FieldIssue/CaseInput`.
- Produces:
  - `ingest.ReaderError(Exception)`
  - `ingest.read_excel_form(path) -> dict[str, object]` (alias: value)
  - `ingest.read_json_record(src: str | Path) -> dict[str, object]` (slug: value)
  - `ingest.build_case_input(raw: dict, questionnaire: dict, source: str) -> CaseInput`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest.py`:

```python
import json
from pathlib import Path

import openpyxl
import pytest

from fpb.ingest import build_case_input, read_excel_form, read_json_record, ReaderError


def _make_form(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Questionnaire"
    ws.append(["No.", "Question / Parameter", "Response options", "Your answer", "Unit"])
    ws.append(["2.1", "External Financing Need", "", "5", ""])
    ws.append(["2.2", "Cash-flow", "", "4", ""])
    ws.append(["2.3", "Payment Preference", "", "5", ""])
    ws.append(["2.4", "External Support", "", "5", ""])
    ws.append(["8.1", "Green Loan", "", "High", ""])
    ws.append(["99.9", "Unknown question", "", "1", ""])
    wb.save(path)


def test_read_excel_form_reads_aliases(tmp_path):
    p = tmp_path / "form.xlsx"
    _make_form(p)
    raw = read_excel_form(p)
    assert raw["2.1"] == "5"
    assert raw["8.1"] == "High"
    assert "99.9" in raw


def test_read_excel_form_missing_sheet_raises(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Other"
    p = tmp_path / "bad.xlsx"
    wb.save(p)
    with pytest.raises(ReaderError, match="Questionnaire"):
        read_excel_form(p)


def test_read_json_record_from_text():
    raw = read_json_record('{"fn_external_need": 5}')
    assert raw == {"fn_external_need": 5}


def test_read_json_record_from_path(tmp_path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps({"fn_external_need": 5}))
    assert read_json_record(p) == {"fn_external_need": 5}


def test_build_case_input_resolves_aliases(bundle):
    raw = {"2.1": "5", "2.2": "4", "2.3": "5", "2.4": "5",
           "8.1": "High", "8.2": "High", "8.3": "Medium",
           "8.4": "Low", "8.5": "Medium",
           "1.1": "57", "1.3": "40.4"}
    case = build_case_input(raw, bundle.questionnaire, "excel")
    assert case.record["fn_external_need"] == 5
    assert case.record["fs_green_loan"] == "High"
    assert case.context == {"consumer_readiness": 57.0, "city_cri": 40.4}
    assert case.source == "excel"


def test_build_case_input_unknown_alias_is_issue(bundle):
    case = build_case_input({"99.9": "1"}, bundle.questionnaire, "excel")
    assert any(i.slug == "99.9" for i in case.issues)


def test_build_case_input_excludes_invalid_values(bundle):
    raw = {"2.1": "not-a-number", "2.2": "4", "2.3": "5", "2.4": "5"}
    case = build_case_input(raw, bundle.questionnaire, "json")
    assert "fn_external_need" not in case.record
    assert any(i.slug == "fn_external_need" for i in case.issues)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/fpb/ingest.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

import openpyxl

from .input_types import CaseInput, FieldIssue
from .validate import iter_fields, validate_record, validate_value


class ReaderError(Exception):
    """Raised when an input file cannot be read."""


def read_excel_form(path: str | Path) -> dict[str, object]:
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several file-specific errors
        raise ReaderError(f"Could not open workbook: {exc}") from exc
    if "Questionnaire" not in wb.sheetnames:
        raise ReaderError("Workbook has no 'Questionnaire' sheet")
    ws = wb["Questionnaire"]
    header = None
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        first = str(row[0]).strip() if row and row[0] is not None else ""
        if first == "No.":
            header = i
            continue
        if header is not None and row[0] is not None and len(row) >= 4:
            rows.append((str(row[0]).strip(), row[3]))
    if header is None:
        raise ReaderError("Could not find header row (column A = 'No.') in Questionnaire sheet")
    out: dict[str, object] = {}
    for no, val in rows:
        if val is None or str(val).strip() == "":
            continue
        out[no] = val
    return out


def read_json_record(src: str | Path) -> dict[str, object]:
    try:
        text = Path(src).read_text() if isinstance(src, Path) else src
    except OSError as exc:
        raise ReaderError(f"Could not read file: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReaderError(f"Not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReaderError("JSON record must be an object of slug: value")
    return data


def _resolve(raw: dict, questionnaire: dict) -> tuple[dict[str, object], list[FieldIssue]]:
    resolved: dict[str, object] = {}
    issues: list[FieldIssue] = []
    alias_to_slug = {}
    slug_labels = {}
    for field in iter_fields(questionnaire):
        slug = field["slug"]
        slug_labels[slug] = field.get("label", slug)
        alias = (field.get("aliases") or {}).get("form_column_d")
        if alias is not None:
            alias_to_slug[str(alias).strip()] = slug
    for key, value in raw.items():
        slug = None
        if str(key).strip() in alias_to_slug:
            slug = alias_to_slug[str(key).strip()]
        elif str(key) in slug_labels:
            slug = str(key)
        if slug is None:
            issues.append(FieldIssue(str(key), str(key), f"Unknown field or question {key!r}", value))
        else:
            resolved[slug] = value
    return resolved, issues


def build_case_input(raw: dict, questionnaire: dict, source: str) -> CaseInput:
    resolved, issues = _resolve(raw, questionnaire)
    issues += list(validate_record(resolved, questionnaire))
    record: dict[str, object] = {}
    context: dict[str, object] = {}
    for field in iter_fields(questionnaire):
        slug = field["slug"]
        if slug not in resolved:
            continue
        if field.get("context_source"):
            context[slug] = float(str(resolved[slug]).strip())
        elif validate_value(field, resolved[slug]):
            continue  # invalid -> excluded, engine reports insufficient below
        else:
            if field["type"] == "likert_5":
                record[slug] = int(str(resolved[slug]).strip())
            elif field["type"] == "numeric":
                record[slug] = float(str(resolved[slug]).strip())
            else:
                record[slug] = str(resolved[slug]).strip()
    return CaseInput(record=record, context=context, issues=tuple(issues), source=source)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fpb/ingest.py tests/test_ingest.py
git commit -m "feat: questionnaire ingestion for Excel forms and JSON records"
```

---

### Task 4: Display helpers

**Files:**
- Create: `src/fpb/display.py`
- Test: `tests/test_display.py`

**Interfaces:**
- Consumes: `fpb.types.Metric`, `fpb.types.SchemeResult`, `fpb.types` state constants.
- Produces:
  - `display.fmt_metric(m: Metric) -> str`
  - `display.fmt_rupiah(value: float | None) -> str`
  - `display.state_badge(state: str) -> str`
  - `display.pct(value: float | None) -> str`
  - `display.band_label(value: float | None, bands: dict) -> str`
  - `display.scheme_frame(results: list[SchemeResult], weights: dict) -> pandas.DataFrame`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_display.py`:

```python
import pytest

from fpb.display import (
    band_label, fmt_metric, fmt_rupiah, pct, scheme_frame, state_badge,
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
        scheme_id="5", name="Blended Finance / VGF", status="active",
        fits={"total": 83.75}, fit_details={}, total=83.75,
        rank=1, is_primary=True, tie_with=None,
    )
    df = scheme_frame([r], {"need": 0.2})
    assert list(df.columns) == ["Rank", "Scheme", "Status", "Fit", "Primary", "Tie"]
    assert df.iloc[0]["Primary"] == "Primary"
    assert df.iloc[0]["Fit"] == 83.75
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_display.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/fpb/display.py`**

```python
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
        rows.append({
            "Rank": r.rank if r.rank else "",
            "Scheme": f"{r.scheme_id}. {r.name}",
            "Status": r.status,
            "Fit": r.total,
            "Primary": "Primary" if r.is_primary else "",
            "Tie": r.tie_with or "",
        })
    return pd.DataFrame(rows, columns=["Rank", "Scheme", "Status", "Fit", "Primary", "Tie"])
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_display.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fpb/display.py tests/test_display.py
git commit -m "feat: pure display helpers for the dashboard"
```

---

### Task 5: Streamlit dashboard app

**Files:**
- Create: `src/fpb/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `load_config`, `score`, `build_case_input`, `read_excel_form`, `read_json_record`, `ReaderError`, display helpers.
- Produces: a runnable `app.py` whose first screen defaults to the bundled example (`tests/fixtures/workbook_case.json` + context `{"consumer_readiness": 57, "city_cri": 40.4}`).

- [ ] **Step 1: Write the smoke test**

Create `tests/test_app.py`:

```python
from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parents[1]


def test_app_renders_golden_example():
    at = AppTest.from_file(str(REPO / "src" / "fpb" / "app.py"), default_timeout=15)
    at.run()
    assert not at.exception
    joined = "\n".join(m.value for m in at.markdown)
    assert "Overall Financing Fit" in joined
    assert "Blended Finance / VGF" in joined
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL (module or app not found / no such file).

- [ ] **Step 3: Implement `src/fpb/app.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from .config import load_config, validate_config
from .display import band_label, fmt_metric, fmt_rupiah, pct, scheme_frame, state_badge
from .engine import score
from .ingest import ReaderError, build_case_input, read_excel_form, read_json_record

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
    return raw, DEFAULT_CONTEXT, "example"


def main() -> None:
    st.set_page_config(page_title="Financing Playbook", layout="wide")
    bundle = _load_bundle()
    st.title("Financing Playbook")

    with st.sidebar:
        st.header("Input")
        mode = st.radio("Source", ["Example", "Excel form", "JSON record"])
        xlsx = st.file_uploader("Respondent questionnaire (.xlsx)", type=["xlsx"]) if mode == "Excel form" else None
        jfile = st.file_uploader("Record (.json)", type=["json"]) if mode == "JSON record" else None

    try:
        if mode == "Excel form":
            if xlsx is None:
                st.info("Upload the respondent questionnaire Excel form to start.")
                return
            raw = read_excel_form(xlsx)  # file-like accepted by openpyxl
            source = f"excel: {xlsx.name}"
        elif mode == "JSON record":
            if jfile is None:
                st.info("Upload a JSON record to start.")
                return
            raw = read_json_record(jfile.getvalue().decode("utf-8"))
            source = f"json: {jfile.name}"
        else:
            raw, DEFAULT_CONTEXT, source = _example_input()
            source = "example: workbook_case.json"

        case = build_case_input(raw, bundle.questionnaire, source)
        result = score(case.record, bundle, case.context)
    except ReaderError as exc:
        st.error(str(exc))
        return

    st.caption(f"Source: {source}  ·  spec {result.spec_version}  ·  config {result.config_version}")

    if case.issues:
        st.warning(
            f"{len(case.issues)} validation issue(s) found — invalid values were excluded, "
            "so some panels may be incomplete."
        )
        for issue in case.issues:
            st.warning(f"**{issue.label}** ({issue.slug}): {issue.message}")
    else:
        st.success("Record validated — all fields accepted.")

    m = result.metrics
    st.header("Overall Financing Fit")
    c1, c2 = st.columns(2)
    c1.metric("Overall Financing Fit", fmt_metric(result.overall),
              band_label(result.overall.value, bundle.scoring["bands"]))
    if result.primary_id:
        primary = next(s for s in result.schemes if s.scheme_id == result.primary_id)
        c2.metric("Primary scheme", f"{primary.scheme_id}. {primary.name}",
                  fmt_metric(primary.total))
    else:
        c2.metric("Primary scheme", "—", "No eligible recommendation")

    st.subheader("Indices and market access")
    cards = st.columns(4)
    for col, key in zip(cards, ["financing_need_index", "risk_profile_index", "market_access",
                                 "readiness_context"]):
        metric = m[key]
        col.metric(key.replace("_", " ").title(),
                   fmt_metric(metric),
                   band_label(metric.value, bundle.scoring["bands"]))

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
        b1.metric("Payback", f"{t['payback_years']:.1f} yrs" if t["payback_years"] is not None else "—")
        b2.metric("Break-even", f"{t['break_even_km']:,.0f} km" if t["break_even_km"] is not None else "—")
        b3.metric("Recovered in horizon", "Yes" if t["recovered_within_horizon"] else "No")

    st.subheader("Scheme ranking")
    st.dataframe(scheme_frame(result.schemes, bundle.schemes["weights"]),
                 use_container_width=True, hide_index=True)

    if result.warnings:
        for w in result.warnings:
            st.warning(w)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the smoke test**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS — app renders with no exceptions and the golden scheme/headline appear.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: 40+ tests pass (41 existing + new).

- [ ] **Step 6: Commit**

```bash
git add src/fpb/app.py tests/test_app.py
git commit -m "feat: Streamlit dashboard rendering the assessment"
```

---

### Task 6: README web-app section and final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Run the web app" section**

Append to `README.md`:

```markdown
## Run the web app

Install the UI extras and launch Streamlit:

```bash
python -m pip install -e ".[ui]"
streamlit run src/fpb/app.py
```

The dashboard opens on the bundled example. Use the sidebar to upload a respondent
questionnaire Excel form (`Financing_Playbook_Respondent_Questionnaire.xlsx`) or a
JSON record (same shape as `tests/fixtures/workbook_case.json`). Validation issues
are shown; invalid values are excluded so the engine reports incomplete panels
instead of silently defaulting.
```

Note the nested code fence — write it as a real fenced block in the README.

- [ ] **Step 2: Verify the whole suite green and smoke the CLI**

Run: `python -m pytest -q` and
`python -m fpb.cli score --config config --record tests/fixtures/workbook_case.json | head -5`
Expected: all tests pass; CLI still prints the assessment JSON (engine untouched).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: web app setup instructions"
```

---

## Self-review notes

**Spec coverage.** §2 scope: Excel form upload (Task 3), JSON upload (Task 3), bundled example (Task 5), validation with exclusion (Task 2/3), dashboard panels (Task 5). §4 modules map 1:1 to Tasks 2–5; `app.py` is the only streamlit import. §5 data model = `input_types.py`. §6 readers/resolver = `ingest.py`. §7 validation = `validate.py`. §8 rendering = `app.py` + `display.py`. §9 errors: ReaderError → `st.error`; issues → amber banner with degraded dashboard; ties → `Tie` column badge; missing readiness → metric renders state. §10 tests: ingest round-trip, validate per-type, display, AppTest smoke. §11 deps: pyproject extras. §12 config growth = Task 1.

**Placeholder scan.** No TBD/TODO; every step has real code or an exact command. The README nested-fence note in Task 6 is intentional guidance, not a placeholder.

**Type consistency.** `CaseInput(record, context, issues, source)` and `FieldIssue(slug, label, message, value)` are defined once in `input_types.py` and used identically in `validate.py`, `ingest.py`, and `app.py`. `validate_record(values, questionnaire) -> tuple[FieldIssue, ...]`; `build_case_input(raw, questionnaire, source) -> CaseInput`; `read_excel_form(path) -> dict[str, object]`; `read_json_record(src) -> dict[str, object]`. Display helpers' signatures match their tests exactly. The `fs_*` choice options in config (`Low/Medium/High/None`, YAML unquoted strings) compare case-insensitively and pass `"High"` through unchanged, matching engine expectation.
