def test_load_config_versions(bundle):
    assert bundle.spec_version == "2026-01"
    assert bundle.config_version == "2026-01"
