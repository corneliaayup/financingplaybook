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
