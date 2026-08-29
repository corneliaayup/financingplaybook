from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldIssue:
    slug: str
    label: str
    message: str
    value: object | None = None


@dataclass(frozen=True)
class CaseInput:
    record: dict[str, object]
    context: dict[str, object]
    issues: tuple[FieldIssue, ...]
    source: str
