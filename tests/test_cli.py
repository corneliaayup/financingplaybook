import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


def _env():
    return dict(os.environ, PYTHONPATH=str(REPO / "src"))


def test_cli_scores_workbook_case(bundle, tmp_path):
    ctx = tmp_path / "ctx.json"
    ctx.write_text(json.dumps({"consumer_readiness": 57, "city_cri": 40.4}))
    out = subprocess.run(
        [
            sys.executable, "-m", "fpb.cli", "score",
            "--config", str(REPO / "config"),
            "--record", str(REPO / "tests/fixtures/workbook_case.json"),
            "--context", str(ctx),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=_env(),
        check=True,
    ).stdout
    r = json.loads(out)
    assert r["primary_id"] == "5"
    assert r["metrics"]["overall_financing_fit"]["value"] == pytest.approx(
        80.12458110657028
    )
    assert r["metrics"]["overall_financing_fit"]["state"] == "computed"
    assert r["config_version"] == "2026-01"


def test_cli_config_validation_failure_exits_3(bundle, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    for name, data in (
        ("questionnaire", bundle.questionnaire),
        ("schemes", bundle.schemes),
        ("scoring", bundle.scoring),
    ):
        (cfg / f"{name}.yaml").write_text(yaml.safe_dump(data))
    bad = yaml.safe_load((cfg / "scoring.yaml").read_text())
    bad["financing_need"]["weights"][0] = 0.10
    (cfg / "scoring.yaml").write_text(yaml.safe_dump(bad))
    proc = subprocess.run(
        [
            sys.executable, "-m", "fpb.cli", "score",
            "--config", str(cfg),
            "--record", str(REPO / "tests/fixtures/workbook_case.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=_env(),
    )
    assert proc.returncode == 3
    assert "config:" in proc.stderr
