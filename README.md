# Financing Playbook

A single-analyst web tool that reproduces the Financing Playbook assessment: upload a questionnaire, validate it, score it against a deterministic, config-driven engine, and get a financing scheme recommendation.

The repository is at an early stage. The current milestone (v0.1) is the **scoring engine**: a pure-Python package that turns a normalized questionnaire record (JSON) into a full assessment — financing need and risk-profile indices, TCO analysis, market access and economic readiness, and a ranked list of financing schemes with fit scores. Config lives in versioned YAML files so the questionnaire structure can change without touching Python. The upload UI (CSV/Excel ingestion), validation screens, and report export are later milestones.

## Project layout

```
config/*.yaml      versioned field definitions, weights, bands, and scheme rules
src/fpb/           the scoring engine (pure Python, no I/O)
tests/             pytest suite, incl. golden-value tests from the reference workbooks
docs/superpowers/  design spec and implementation plan
resouce/           reference Excel workbooks (not tracked)
```

## Prerequisites

- Python 3.11 or newer
- Git (to clone the repository)

## Setup

Create and activate a virtual environment, then install the package in editable mode (with dev extras for testing):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows, activate with `.venv\Scripts\activate` instead.

The package has one runtime dependency (`PyYAML`); the dev extra adds `pytest`. The install pulls from PyPI, so a fresh environment needs network access.

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

To run everything (tests plus the dashboard), install both extra groups:

```bash
python -m pip install -e ".[dev,ui]"
```
