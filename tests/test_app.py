from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO = Path(__file__).resolve().parents[1]
APP = str(REPO / "src" / "fpb" / "app.py")


def _rendered_html(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def _run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    return at


def test_app_renders_example_dashboard_on_first_load():
    at = _run_app()
    assert not at.exception
    html = _rendered_html(at)
    # The initial dashboard is the approval mockup with temporary example values.
    assert "Overall Financing Fit Score" in html
    assert "SCHEME 3" in html
    assert "PRIMARY RECOMMENDATION" in html


def test_tabs_separate_questionnaire_and_dashboard():
    at = _run_app()
    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["📝 Kuesioner", "📊 Dashboard Hasil"]
    assert at.selectbox(key="q_fn_external_need").value == 5
    assert any("Calculate" in (b.label or "") for b in at.button)


def test_dashboard_kpi_cards_show_computed_scores():
    at = _run_app()
    assert not at.exception
    html = _rendered_html(at)
    for label in (
        "Financing Need Index",
        "Risk Profile Index",
        "TCO Competitiveness",
        "Investment Burden",
        "Economic Readiness",
    ):
        assert label in html


def test_questionnaire_input_drives_dashboard_scoring():
    at = _run_app()
    # Lower the external financing need; the dashboard score must update on submit.
    at.selectbox(key="q_fn_external_need").set_value(1)
    at.radio[0].set_value("Hasil kuesioner terakhir")
    submit = next(b for b in at.button if "Calculate" in (b.label or ""))
    submit.click().run()
    assert not at.exception
    html = _rendered_html(at)
    assert "Perhitungan selesai" in "\n".join(s.value for s in at.success)
    assert "Assessment Detail" in html
    assert "PRIMARY RECOMMENDATION" in html
    # 1, 4, 5, 5 = 3.75 on the 1-5 scale, i.e. a 68.75 Need Index.
    assert 'kpi-value green">69 <small>' in html


def test_questionnaire_shows_workbook_options_and_instructions():
    at = _run_app()
    assert not at.exception
    assert any("Petunjuk Pengisian" in (e.label or "") for e in at.expander)
    # An optional dropdown exposes the source workbook's options and blank choice.
    stake = at.selectbox(key="q_form_0_4")
    assert "(choose one)" in stake.options
    assert "Logistics / Cold Chain Company" in stake.options
    # A required scored dropdown has no blank option.
    assert "(choose one)" not in at.selectbox(key="q_fs_green_loan").options
    # Section guidance is visible.
    assert any("Rate each statement from 1 to 5" in (c.value or "") for c in at.caption)


def test_all_workbook_question_numbers_are_in_questionnaire_config():
    """Every numbered question in the respondent workbook is represented in config."""
    import yaml

    cfg = yaml.safe_load((REPO / "config" / "questionnaire.yaml").read_text())
    actual = {str(f.get("qno")) for s in cfg["sections"] for f in s["fields"]}
    expected = {
        *(f"0.{i}" for i in range(1, 10)),
        *(f"1.{i}" for i in range(1, 8)),
        *(f"2.{i}" for i in range(1, 6)),
        *(f"3.{i}" for i in range(1, 8)),
        *(f"4.{i}" for i in range(1, 9)),
        *(f"5.{i}" for i in range(1, 9)),
        *(f"6.{i}" for i in range(1, 12)),
        *(f"7.{i}" for i in range(1, 8)),
        *(f"8.{i}" for i in range(1, 11)),
        *(f"9.{i}" for i in range(1, 6)),
        *(f"10.{i}" for i in range(1, 7)),
        *(f"11.{i}" for i in range(1, 4)),
    }
    assert expected <= actual


def test_identity_fields_flow_to_dashboard_and_banned_names_are_absent():
    at = _run_app()
    assert at.text_input(key="q_form_0_5").value == "Surabaya"
    assert at.text_input(key="q_form_0_2").value == "Cornelia Ayu"
    at.text_input(key="q_form_0_5").set_value("Bandung")
    at.text_input(key="q_form_0_2").set_value("Budi Santoso")
    at.radio[0].set_value("Hasil kuesioner terakhir")
    next(b for b in at.button if "Calculate" in (b.label or "")).click().run()
    assert not at.exception
    html = _rendered_html(at)
    assert "Bandung" in html
    assert "Budi Santoso" in html
    assert "Bu Andani" not in html
    assert "Pak Tilaka" not in html
    assert "Smart Freight Centre" not in html
