from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parents[1]


def test_app_renders_golden_example():
    at = AppTest.from_file(str(REPO / "src" / "fpb" / "app.py"), default_timeout=15)
    at.run()
    assert not at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels.get("Overall Financing Fit") == "80.1"
    assert labels.get("Primary scheme") == "5. Blended Finance / VGF"
