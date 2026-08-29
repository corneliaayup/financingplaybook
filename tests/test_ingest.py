import json
from pathlib import Path

import openpyxl
import pytest

from fpb.ingest import (
    ReaderError,
    build_case_input,
    read_excel_form,
    read_json_record,
)


def _make_form(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Questionnaire"
    ws.append(
        ["No.", "Question / Parameter", "Response options", "Your answer", "Unit"]
    )
    ws.append(["2.1", "External Financing Need", "", "5", ""])
    ws.append(["2.2", "Cash-flow", "", "4", ""])
    ws.append(["2.3", "Payment Preference", "", "5", ""])
    ws.append(["2.4", "External Support", "", "5", ""])
    ws.append(["8.1", "Green Loan", "", "High", ""])
    ws.append(["99.9", "Unknown question", "", "1", ""])
    wb.save(path)


def test_read_excel_form_reads_aliases(tmp_path):
    p = tmp_path / "form.xlsx"
    _make_form(p)
    raw = read_excel_form(p)
    assert raw["2.1"] == "5"
    assert raw["8.1"] == "High"
    assert "99.9" in raw


def test_read_excel_form_missing_sheet_raises(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Other"
    p = tmp_path / "bad.xlsx"
    wb.save(p)
    with pytest.raises(ReaderError, match="Questionnaire"):
        read_excel_form(p)


def test_read_json_record_from_text():
    raw = read_json_record('{"fn_external_need": 5}')
    assert raw == {"fn_external_need": 5}


def test_read_json_record_from_path(tmp_path):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps({"fn_external_need": 5}))
    assert read_json_record(p) == {"fn_external_need": 5}


def test_build_case_input_resolves_aliases(bundle):
    raw = {
        "2.1": "5",
        "2.2": "4",
        "2.3": "5",
        "2.4": "5",
        "8.1": "High",
        "8.2": "High",
        "8.3": "Medium",
        "8.4": "Low",
        "8.5": "Medium",
        "1.1": "57",
        "1.3": "40.4",
    }
    case = build_case_input(raw, bundle.questionnaire, "excel")
    assert case.record["fn_external_need"] == 5
    assert case.record["fs_green_loan"] == "High"
    assert case.context == {"consumer_readiness": 57.0, "city_cri": 40.4}
    assert case.source == "excel"


def test_build_case_input_unknown_alias_is_issue(bundle):
    case = build_case_input({"99.9": "1"}, bundle.questionnaire, "excel")
    assert any(i.slug == "99.9" for i in case.issues)


def test_build_case_input_excludes_invalid_values(bundle):
    raw = {"2.1": "not-a-number", "2.2": "4", "2.3": "5", "2.4": "5"}
    case = build_case_input(raw, bundle.questionnaire, "json")
    assert "fn_external_need" not in case.record
    assert any(i.slug == "fn_external_need" for i in case.issues)


def test_build_case_input_text_metadata_stays_out_of_record(bundle):
    case = build_case_input(
        {"0.1": "PT Maju", "2.1": "5", "2.2": "4", "2.3": "5", "2.4": "5"},
        bundle.questionnaire,
        "excel",
    )
    assert "form_0_1" not in case.record
    assert "form_0_1" not in case.context
    assert not any(i.slug == "form_0_1" for i in case.issues)
    assert case.record["fn_external_need"] == 5
