import pytest

from fpb.validate import iter_fields, validate_record, validate_value


def _field(**kw):
    base = {
        "slug": "x",
        "type": "likert_5",
        "required": False,
        "label": "X",
        "section": "S",
    }
    base.update(kw)
    return base


def test_likert_accepts_int_one_to_five():
    assert validate_value(_field(), 3) == []


def test_likert_rejects_out_of_range():
    issues = validate_value(_field(), 6)
    assert len(issues) == 1
    assert "1-5" in issues[0].message


def test_numeric_accepts_float_and_int():
    f = _field(type="numeric", min=0, max=100)
    assert validate_value(f, 12) == []
    assert validate_value(f, 12.5) == []


def test_numeric_rejects_non_numeric():
    f = _field(type="numeric", min=0, max=100)
    issues = validate_value(f, "abc")
    assert issues and "number" in issues[0].message


def test_numeric_rejects_out_of_range():
    f = _field(type="numeric", min=0, max=100)
    assert validate_value(f, -1)
    assert validate_value(f, 101)


def test_choice_rejects_unknown_case_insensitively():
    f = _field(type="choice", options=["Low", "Medium", "High", "None"])
    assert validate_value(f, "Low") == []
    assert validate_value(f, "low") == []
    assert validate_value(f, "hight")


def test_required_missing_is_an_issue():
    issues = validate_record(
        {}, {"sections": [{"fields": [_field(required=True)]}]}
    )
    assert len(issues) == 1
    assert "required" in issues[0].message.lower()


def test_iter_fields_flattens_sections():
    q = {
        "sections": [
            {"fields": [_field(slug="a")]},
            {"fields": [_field(slug="b")]},
        ]
    }
    assert [f["slug"] for f in iter_fields(q)] == ["a", "b"]
