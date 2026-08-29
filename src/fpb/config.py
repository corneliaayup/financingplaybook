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
        problems.append(
            f"economic_readiness weights sum to {sum(er_w.values())}, expected 1.0"
        )

    of_w = s["overall_fit"]["weights"]
    if not _close(sum(of_w.values()), 1.0):
        problems.append(f"overall_fit weights sum to {sum(of_w.values())}, expected 1.0")

    bands = s["bands"]
    if [tuple(bands[k]) for k in ("low", "medium", "high")] != [(0, 33), (34, 66), (67, 100)]:
        problems.append("bands must be low [0,33], medium [34,66], high [67,100]")

    sw = bundle.schemes["weights"]
    if not _close(sum(sw.values()), 1.0):
        problems.append(f"scheme weights sum to {sum(sw.values())}, expected 1.0")

    priorities = [
        x["library_priority"] for x in bundle.schemes["schemes"] if x["status"] == "active"
    ]
    if len(priorities) != len(set(priorities)):
        problems.append("library_priority must be unique among active schemes")

    known = {"target_band", "parity_or_gap", "constant", "support_fit", "weighted_sum"}
    for x in bundle.schemes["schemes"]:
        for dim, rule in x["fit"].items():
            if dim != "total" and next(iter(rule)) not in known:
                problems.append(f"scheme {x['id']}: unknown primitive in {dim}")
    return problems
