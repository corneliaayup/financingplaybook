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


ENGINE_TCOS = [
    f"{p}{f}"
    for p in ("tco_diesel_", "tco_ev_")
    for f in (
        "capex",
        "subsidy",
        "energy_idr_km",
        "maintenance_idr_m_yr",
        "insurance_idr_m_yr",
        "infra_idr_m",
        "battery_idr_m",
        "residual_idr_m",
        "financing_idr_m",
    )
]
ENGINE_SLUGS = (
    [
        "fn_external_need",
        "fn_cashflow_constraint",
        "fn_payment_preference",
        "fn_support_requirement",
    ]
    + [
        "rp_ownership",
        "rp_technology",
        "rp_battery",
        "rp_residual",
        "rp_maintenance",
        "rp_downtime",
    ]
    + ["tco_annual_km", "tco_years"]
    + ENGINE_TCOS
    + [
        "fs_green_loan",
        "fs_lease_rent",
        "fs_baas",
        "fs_project_finance",
        "fs_blended_finance",
    ]
)


def test_questionnaire_covers_all_engine_slugs(bundle):
    slugs = {
        f["slug"] for sec in bundle.questionnaire["sections"] for f in sec["fields"]
    }
    assert set(ENGINE_SLUGS) <= slugs


def test_every_field_has_label_and_type(bundle):
    for sec in bundle.questionnaire["sections"]:
        for f in sec["fields"]:
            assert f["type"] in {"likert_5", "numeric", "choice", "text", "date"}
            assert f["label"]
            if f["type"] == "choice":
                assert f["options"]
