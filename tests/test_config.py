import copy

import yaml

from fpb.config import load_config, validate_config


def test_load_config_versions(bundle):
    assert bundle.spec_version == "2026-01"
    assert bundle.config_version == "2026-01"


def test_valid_config_has_no_problems(bundle):
    assert validate_config(bundle) == []


def test_validate_catches_bad_weights(bundle, tmp_path):
    bad = copy.deepcopy(bundle.scoring)
    bad["financing_need"]["weights"] = [0.25, 0.25, 0.25, 0.20]
    (tmp_path / "questionnaire.yaml").write_text(yaml.safe_dump(bundle.questionnaire))
    (tmp_path / "scoring.yaml").write_text(yaml.safe_dump(bad))
    (tmp_path / "schemes.yaml").write_text(yaml.safe_dump(bundle.schemes))
    problems = validate_config(load_config(tmp_path))
    assert any("financing_need" in p and "1.0" in p for p in problems)
