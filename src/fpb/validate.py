from __future__ import annotations

from collections.abc import Iterator

from .input_types import FieldIssue


def iter_fields(questionnaire: dict) -> Iterator[dict]:
    for section in questionnaire["sections"]:
        yield from section["fields"]


def validate_value(field: dict, value: object) -> list[FieldIssue]:
    slug = field["slug"]
    label = field.get("label", slug)
    ftype = field.get("type")
    raw = "" if value is None else str(value).strip()

    if ftype == "likert_5":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return [
                FieldIssue(slug, label, f"{label} must be an integer 1-5", value)
            ]
        if not 1 <= v <= 5:
            return [
                FieldIssue(
                    slug, label, f"{label} must be an integer 1-5, got {value!r}", value
                )
            ]
        return []

    if ftype == "numeric":
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return [FieldIssue(slug, label, f"{label} must be a number", value)]
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and v < lo:
            return [
                FieldIssue(
                    slug, label, f"{label} must be >= {lo}, got {value!r}", value
                )
            ]
        if hi is not None and v > hi:
            return [
                FieldIssue(
                    slug, label, f"{label} must be <= {hi}, got {value!r}", value
                )
            ]
        return []

    if ftype == "choice":
        allowed = {str(o).strip().lower() for o in field.get("options", [])}
        if raw.lower() not in allowed:
            return [
                FieldIssue(
                    slug,
                    label,
                    f"{label} must be one of {sorted(allowed)}, got {value!r}",
                    value,
                )
            ]
        return []

    return []


def validate_record(values: dict, questionnaire: dict) -> tuple[FieldIssue, ...]:
    issues: list[FieldIssue] = []
    for field in iter_fields(questionnaire):
        slug = field["slug"]
        if slug not in values:
            if field.get("required"):
                issues.append(
                    FieldIssue(
                        slug,
                        field.get("label", slug),
                        f"Required field {slug} is missing",
                    )
                )
            continue
        issues.extend(validate_value(field, values[slug]))
    return tuple(issues)
