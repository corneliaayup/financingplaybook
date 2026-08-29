# Financing Playbook — Dashboard (UI slice) Design

Date: 2026-08-29
Status: approved direction, written as implementation spec
Classification: architectural (new subsystem)

## 1. Summary

The single-analyst web dashboard for the Financing Playbook. It ingests a
questionnaire (an `xlsx` respondent form, a JSON record, or the bundled example),
validates it against the questionnaire config, runs the existing deterministic
scoring engine, and renders an assessment detail view: headline financing fit,
primary scheme recommendation, index cards, TCO comparison, market-access panel,
scheme ranking with tie badges, readiness context, warnings, and config stamps.

This is the first UI slice of the approved full design. It deliberately ships
**one case at a time with no persistence**: every run starts from an uploaded or
selected input and the result lives for the session only. Assessment history,
scenario analysis, the data library, and export are out of scope for this slice and
remain in the full design.

## 2. Scope

### In scope for this slice

| Item | Behaviour |
|---|---|
| Upload: respondent Excel form | Read `Financing_Playbook_Respondent_Questionnaire.xlsx` from `resouce/`: question numbers in column A, answers in column D, one case per file. |
| Upload: JSON record | A flat dict of canonical slugs to values (the same shape the CLI accepts). |
| Bundled example | Populate the app with the canonical `workbook_case.json` fixture and its context in one click. |
| Validation | Check every submitted value against the questionnaire config: type, range, allowed options, required-ness. Report issues with the human label and an index; excluded values are never coerced or defaulted, so the engine degrades per panel (spec §9.2) instead of producing wrong confident numbers. |
| Dashboard | Render `AssessmentResult`: headline fit + primary scheme, index cards, TCO comparison, market-access levels, scheme ranking, readiness context, warnings, stamps. |
| CSV/Excel-export, case list, scenario analysis | Deferred (out of scope). |

### Explicitly out of scope

- Persistence / SQLite (assessments list, saved cases, reference data store)
- Scenario analysis and result diffing
- HTML/Excel report export
- Data library screens
- Editing scoring rules in the UI
- The "flat reader" (many cases per CSV/XLSX) — only the respondent form reader and
  the JSON record reader in this slice
- Plotly charts (Streamlit's built-in primitives cover this slice)

## 3. Context and constraints

The engine (`src/fpb/engine.py`) is a pure function: `score(record, config, context)
-> AssessmentResult`, no I/O, no `streamlit` import. Everything in this slice sits
**upstream** (ingest/validate) or **downstream** (UI/display) of it. The engine
module tree must not import `streamlit`, `pandas`, `openpyxl`, or `sqlite3` — a
constraint the existing `tests/test_properties.py` enforces and this slice must
keep.

The engine fixture `tests/fixtures/workbook_case.json` is a dict of 35 canonical
slugs (10 likert, 20 TCO numeric, 5 market-access choices). The respondent
questionnaire workbook (128 rows; question numbers in column A, headers in row 8,
answers in column D) is the ground truth for the alias map:

| Workbook section | Question numbers | Engine slugs |
|---|---|---|
| 2. Financing Need | 2.1–2.4 | `fn_external_need`, `fn_cashflow_constraint`, `fn_payment_preference`, `fn_support_requirement` |
| 3. Risk Profile | 3.1–3.6 | `rp_ownership`, `rp_technology`, `rp_battery`, `rp_residual`, `rp_maintenance`, `rp_downtime` |
| 5 / 6. TCO | 4.4–4.5 → `tco_annual_km`/`tco_years`; 5.x diesel, 6.x EV | `tco_*` (20 fields) |
| 8. Financing Supply | 8.1–8.5 | `fs_green_loan`, `fs_lease_rent`, `fs_baas`, `fs_project_finance`, `fs_blended_finance` |
| 1. Existing Readiness | 1.1, 1.3 | `consumer_readiness`, `city_cri` (context) |

The current `config/questionnaire.yaml` describes only the 10 likert fields and has
no aliases, units, or labels. This slice extends that file to cover all engine
inputs; **the extension is additive** — the existing definitions and scoring config
stay byte-identical, so the engine and its golden tests are untouched.

## 4. Architecture

Five new modules plus config, keeping the engine at the center:

```
             ┌───────────────  src/fpb/ingest.py  ───────────────┐
 xlsx form ──►  read_excel_form(path) -> {alias: value}          │
 json rec ──►  read_json_record(path|text) -> {alias: value}     │
             └─────────────────────┬─────────────────────────────┘
                                   └──► {slug: value} + issues
                                            │
             ┌────────────  src/fpb/validate.py  ────────────────┐
             │  validate_record(record, questionnaire) -> issues │
             └─────────────────────┬─────────────────────────────┘
                                   │  CaseInput{record, context, issues}
                                   ▼
             ┌────────────────  engine.score(record, config, context)  ────────┐
             │                     (untouched, pure)                           │
             └────────────────────────────┬─────────────────────────────────────┘
                                          ▼
             ┌────────────  src/fpb/display.py  ────────────────┐   (pure formatters)
             │  fmt_metric, fmt_rupiah, band_color, ...          │
             └────────────────────────────┬─────────────────────┘
                                          ▼
             ┌────────────  src/fpb/app.py  ────────────────────┐
             │  Streamlit UI; the ONLY streamlit import         │
             └──────────────────────────────────────────────────┘
```

* `ingest.py` — dumb readers + alias resolver. Returns typed `CaseInput` and a list
  of `FieldIssue`s. Holds no scoring knowledge.
* `validate.py` — pure validation against the questionnaire config (types required
  by the engine: likert 1–5, numeric with plausible bounds, choice options).
* `display.py` — pure presentation helpers: number/currency formatting, metric state
  → badge, band → color. Unit-testable without Streamlit.
* `app.py` — the only file that imports Streamlit. Renders `CaseInput` (issues) and
  `AssessmentResult` (dashboard). No arithmetic beyond what `display.py` formats.

The engine stays a pure function; the UI is a thin rendering layer. This is what
makes the full design's scenario-analysis nearly free later, and it keeps every
scoring decision unit-testable.

## 5. Data model

```python
@dataclass(frozen=True)
class FieldIssue:
    slug: str            # canonical slug (or alias when before resolution)
    label: str           # human label from questionnaire config
    message: str         # why the value is invalid
    value: object | None # the offending raw value

@dataclass(frozen=True)
class CaseInput:
    record: dict[str, object]        # canonical slugs -> typed values
    context: dict[str, object]       # readiness context (consumer_readiness, city_cri)
    issues: tuple[FieldIssue, ...]   # validation issues (empty = clean)
    source: str                      # "excel" | "json" | "example"
```

Questionnaire config gains per-field metadata. Additive keys with safe defaults:

```yaml
fields:
  - slug: fn_external_need
    type: likert_5
    required: true
    label: "External Financing Need"
    section: "2. Financing Need"
    unit: ""                 # optional; e.g. "Rp million" for numeric
    min: 1                   # numeric bounds
    max: 100000               # only for numeric type
    aliases: {form_column_d: "2.1", master_id: FN1, csv: external_financing_need}
    options: ["Low", "Medium", "High", "None"]   # only for choice type
    scoring_role: financing_need
```

The resolver maps `form_column_d` aliases from the workbook (column A question
numbers) to slugs; unknown aliases and duplicate slugs across sections are
validation errors. `consumer_readiness` and `city_cri` are ordinary questionnaire
fields of type `numeric`, but they feed the `context` dict rather than the TCO
record.

## 6. Ingestion

### 6.1 Excel respondent form reader

Locates the `Questionnaire` sheet, finds the header row (the row containing `No.`
in column A), then reads each data row: question number from column A, answer from
column D. Skips section headers and blank rows. Returns `{question_number:
str(value)}`. One case per file. A missing `Questionnaire` sheet, missing header
row, or unreadable file raises a `ReaderError` with a human message.

The reader is intentionally dumb — it emits `{alias: value}` and lets the resolver
own vocabulary.

### 6.2 JSON record reader

Accepts the same shape the CLI uses (`tests/fixtures/workbook_case.json`): a flat
dict of canonical slugs to values. Accepts either a JSON string or a `Path`.
Unknown slugs are kept as issues (so a typo of a slug surfaces), not silently
dropped.

## 7. Validation

`validate_record(record, questionnaire)` returns a tuple of `FieldIssue`s:

- **Type:** a likert field must be an integer 1–5 (or a numeric string that parses
  to such); a numeric field must parse to a number; a choice field must be one of
  its allowed options (case-insensitive, trimmed).
- **Range:** numeric fields are constrained by `min`/`max` (e.g. 5,000 operating
  days/yr or negative CAPEX is implausible).
- **Option list:** market-access fields (`fs_*`) must be one of
  `Low/Medium/High/None`; anything else (e.g. `"hight"`) is an issue.
- **Required:** a missing required field is an issue (`fn_external_need` blank).

Nothing is silently defaulted. A value that fails validation is **excluded from
the record passed to the engine** — the engine then reports the metric as
`insufficient_inputs` naming the missing slug (spec §9.2). The UI shows every
issue on the screen before the dashboard, so an analyst can correct or override.

The engine modules remain untouched: scoring never runs on coerced values, and the
engine's existing tests keep passing with a note that the config now covers more
fields.

## 8. Dashboard rendering

`app.py` renders, top to bottom:

1. **Header** — tool name and source: which file/example produced this result.
2. **Validity banner** — if issues exist, a clearing message ("cannot recommend a
   scheme yet: questionnaire sections 5–6 are empty" per spec §9.2) with the issue
   list; a green banner when the record passes validation.
3. **Headline** — `overall_financing_fit` value + band, and the primary scheme
   (`primary_id`) with its fit.
4. **Index cards** — `financing_need_index`, `risk_profile_index`, `market_access`,
   `readiness_context` metric value + band.
5. **TCO panel** — table of the diesel vs EV `TcoTotals`, `operating_saving_pct`,
   `payback_years`, `break_even_km`, and `recovered_within_horizon` verdict, with
   a warning when not recovered within the horizon.
6. **Scheme ranking** — table of all schemes (active + draft), rank, fit, `is_primary`,
   and a tie badge when `tie_with` is set.
7. **Warnings + stamps** — engine warnings plus `spec_version` / `config_version`.

Pure formatters in `display.py` keep the Streamlit file thin; every formatting
decision is unit-tested.

## 9. Error handling

- **ReaderError** with a human message → shown as a top-level error, no dashboard.
- **Validation issues** → shown as an amber banner with the dashboard degraded
  (per-panel `insufficient_inputs`); never a silent default.
- **Tie** → badge on the tied alternatives with the reason (`library_priority`
  tie-break), unresolved, mirroring spec §9.1.
- **Missing readiness context** → readiness card shows state `insufficient_inputs`
  without crashing.

## 10. Testing

- **Unit: ingest** — round-trip a generated Excel form (write a temp workbook with
  the same shape, read it back, assert the `{alias: value}` map); JSON reader happy
  path + malformed/unknown slug.
- **Unit: validate** — a passing record yields no issues; each failure type
  (type, range, option, required) yields the right issue.
- **Unit: display** — formatting helpers produce expected strings; metric state →
  badge mapping.
- **Unit: resolver** — alias → slug resolution, duplicate-slug and unknown-alias
  failures.
- **Streamlit AppTest smoke** — load the bundled example through the app entry
  point and assert the golden result is present (primary id `"5"`, overall fit
  `≈ 80.12`). This is the integration proof that the UI consumes the engine
  correctly without launching a browser or server.

## 11. Dependencies

- `openpyxl` moves from the main venv (already present, currently untracked as a
  dependency) to the core runtime dependencies.
- `streamlit` and `pandas` are added under a `[project.optional-dependencies]`
  `ui` extra, so the engine can install/build without them.
- `pytest` remains in the `dev` extra. No new runtime deps beyond those.

Concretely the split is: `pip install -e ".[ui]"` for the app, `pip install -e
".[dev]"` for tests, `pip install -e ".[dev,ui]"` for both.

## 12. Configuration surface

`config/questionnaire.yaml` is the single source of field vocabulary: slugs, types,
units, bounds, options, aliases, sections, and labels. This is exactly the
mutability the design requires — a new questionnaire version is a config edit that
flows through to ingestion, validation, and labels without touching Python.

## 13. Known limitations / deferred

- No persistence: refresh discards the session result (accepted for v0.1).
- No export, scenario analysis, or data library (full-design v1 scope).
- The flat reader (many cases per file) is deferred; the Excel form reader and JSON
  reader cover the single-analyst flow.
- Plotly deferred; Streamlit primitives are sufficient for six panels.
