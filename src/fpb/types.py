from __future__ import annotations

from dataclasses import dataclass, field

COMPUTED = "computed"
NOT_APPLICABLE = "not_applicable"
INSUFFICIENT = "insufficient_inputs"


@dataclass(frozen=True)
class Metric:
    value: float | None
    state: str = COMPUTED
    missing: tuple[str, ...] = ()
    detail: str = ""

    @staticmethod
    def insufficient(missing: tuple[str, ...]) -> Metric:
        return Metric(None, INSUFFICIENT, tuple(missing))


@dataclass(frozen=True)
class TcoTotals:
    total_idr_m: float
    cost_per_km: float
    annual_opex_idr_m: float
    net_capex_idr_m: float


@dataclass(frozen=True)
class SchemeResult:
    scheme_id: str
    name: str
    status: str
    fits: dict[str, float | None]
    fit_details: dict[str, str]
    total: float | None
    rank: int = 0
    is_primary: bool = False
    tie_with: str | None = None


@dataclass(frozen=True)
class AssessmentResult:
    spec_version: str
    config_version: str
    metrics: dict[str, Metric]
    tco: dict
    schemes: list[SchemeResult]
    overall: Metric
    primary_id: str | None
    warnings: list[str] = field(default_factory=list)
