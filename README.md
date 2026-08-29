# Financing Playbook

A single-analyst web tool that reproduces the Financing Playbook assessment: upload a questionnaire, validate it, score it against a deterministic, config-driven engine, and get a financing scheme recommendation.

The current milestone (v0.1) is the **scoring engine plus a Streamlit dashboard**: a
pure-Python engine turns a normalized questionnaire record into a full assessment —
financing need and risk-profile indices, TCO analysis, market access and economic
readiness, and a ranked list of financing schemes with fit scores — and a web app
ingests the data (respondent Excel form or JSON), validates it, and renders the
assessment detail view. Config lives in versioned YAML files so the questionnaire
structure can change without touching Python. Report export and multi-case
persistence are later milestones.

## Project layout

```
config/*.yaml      versioned field definitions, weights, bands, and scheme rules
src/fpb/           the scoring engine (pure Python) + Streamlit dashboard (app.py)
tests/             pytest suite, incl. golden-value tests from the reference workbooks
docs/superpowers/  design spec and implementation plan
resouce/           reference Excel workbooks (not tracked)
```

## Prerequisites

- Python 3.11 or newer
- Git (to clone the repository)

Check your versions:

```bash
python3 --version   # must be 3.11+
git --version
```

## Local setup

**Step 1 — clone the repository**

```bash
git clone git@github.com:corneliaayup/financingplaybook.git
cd financingplaybook
```

**Step 2 — create and activate a virtual environment**

```bash
python3 -m venv .venv
```

Activate it:

- macOS / Linux: `source .venv/bin/activate`
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd): `.venv\Scripts\activate.bat`

You'll know it worked when your prompt is prefixed with `(.venv)`.

**Step 3 — install the project**

The project is installed in editable mode so code changes apply immediately. For
everything (tests plus the web dashboard), install both extra groups:

```bash
python -m pip install -e ".[dev,ui]"
```

Or just one group if you only need part of it:

- `python -m pip install -e ".[ui]"` — the dashboard only
- `python -m pip install -e ".[dev]"` — tests only (engine + CLI work with this)

This pulls dependencies from PyPI, so you need network access on first install.
Runtime dependencies are `PyYAML` and `openpyxl`; the `ui` extra adds `streamlit`
and `pandas`; the `dev` extra adds `pytest`.

**Step 4 — verify the install**

```bash
python -c "import fpb; print('fpb ok')"
python -m fpb.cli --help
```

No errors and a usage message means everything is installed.

## Quick start

The fastest way to see the tool working is to launch the dashboard (it opens on a
bundled example case) and, separately, see the raw JSON the engine produces:

```bash
streamlit run src/fpb/app.py
```

Then in a second terminal:

```bash
python -m fpb.cli score --config config --record tests/fixtures/workbook_case.json
```

## Run the tests

```bash
python -m pytest
```

## Try the engine from the command line

The CLI takes a record as JSON plus the config directory and prints the full assessment as JSON:

```bash
python -m fpb.cli score --config config --record tests/fixtures/workbook_case.json
```

Optional flags:

- `--context <file>` — JSON with city/context data (e.g. `city_cri`, `consumer_readiness`) used by the market-access and economic-readiness metrics.
- `--config <dir>` — override the config directory (default is `config`).

### Example record

`tests/fixtures/workbook_case.json` is a complete sample record — a dict of questionnaire field slugs to numeric answers (abbreviated here):

```json
{
  "fn_external_need": 5,
  "fn_cashflow_constraint": 4,
  "rp_ownership": 5,
  "rp_technology": 4,
  "tco_annual_km": 50000,
  "tco_diesel_capex": 500,
  "...": "all other questionnaire fields"
}
```

## Using the engine as a library

```python
from pathlib import Path
from fpb.config import load_config, validate_config
from fpb.engine import score

bundle = load_config(Path("config"))
result = score(record, bundle, context={})
```

`validate_config(bundle)` returns a list of configuration problems; the CLI exits with status 3 if any are found.

## What the engine computes

- Financing Need Index and Risk Profile Index (config-driven weights and bands)
- TCO comparison (diesel vs EV), operating saving, payback, and break-even kilometres
- Market Access score and Economic Readiness score
- Fit score per financing scheme, ranked with a primary recommendation
- Everything stamped with `spec_version` and `config_version`

Each metric reports one of three states — `computed`, `not_applicable`, or `insufficient_inputs` (naming the missing fields) — so results never silently default.

## Run the web app

Launch the dashboard from the repository root (make sure your venv is active and
you installed the `ui` extra):

```bash
streamlit run src/fpb/app.py
```

Expected output:

```text
You can now view your Streamlit app in your browser.

Local URL: http://localhost:8501
```

Open **http://localhost:8501** in your browser. The dashboard loads the bundled
example (the golden `workbook_case` fixture). To run your own assessment, use the
sidebar:

- **Example** — the bundled sample case (default).
- **Excel form** — upload the respondent questionnaire
  (`Financing_Playbook_Respondent_Questionnaire.xlsx`); question numbers in column
  A, answers in column D.
- **JSON record** — upload a flat JSON file of field slugs to values (same shape as
  `tests/fixtures/workbook_case.json`).

Validation issues are shown in an amber banner and the offending values are
excluded, so incomplete panels are reported as `insufficient_inputs` rather than
silently defaulted. Stop the server with `Ctrl+C`.

If port 8501 is already in use, pick another one:

```bash
streamlit run src/fpb/app.py --server.port 8502
```
