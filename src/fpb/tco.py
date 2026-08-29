from __future__ import annotations

from dataclasses import dataclass

from .types import Metric, TcoTotals


@dataclass(frozen=True)
class PowertrainInputs:
    capex_idr_m: float
    subsidy_idr_m: float
    energy_idr_km: float
    maintenance_idr_m_yr: float
    insurance_idr_m_yr: float
    infra_idr_m: float
    battery_idr_m: float
    residual_idr_m: float
    financing_idr_m: float


@dataclass(frozen=True)
class TcoResult:
    diesel: TcoTotals
    ev: TcoTotals
    competitiveness: Metric
    investment_burden: Metric
    operating_saving_pct: float
    payback_years: float | None
    break_even_km: float | None
    recovered_within_horizon: bool


def _totals(
    p: PowertrainInputs,
    annual_km: float,
    years: float,
    add_capex: float,
    add_energy_yr: float,
) -> TcoTotals:
    energy = p.energy_idr_km * annual_km / 1e6 + add_energy_yr
    total = (
        p.capex_idr_m
        - p.subsidy_idr_m
        + add_capex
        + energy * years
        + p.maintenance_idr_m_yr * years
        + p.insurance_idr_m_yr * years
        + p.infra_idr_m
        + p.battery_idr_m
        - p.residual_idr_m
        + p.financing_idr_m
    )
    opex = energy + p.maintenance_idr_m_yr + p.insurance_idr_m_yr
    return TcoTotals(total, total * 1e6 / (annual_km * years), opex,
                     p.capex_idr_m - p.subsidy_idr_m)


def run(
    diesel: PowertrainInputs,
    ev: PowertrainInputs,
    annual_km: float,
    years: float,
    cc_capex_idr_m: float = 0.0,
    cc_energy_idr_m_yr: float = 0.0,
    apply_to: tuple[str, ...] = ("ev", "diesel"),
) -> TcoResult:
    d = _totals(
        diesel, annual_km, years,
        cc_capex_idr_m if "diesel" in apply_to else 0.0,
        cc_energy_idr_m_yr if "diesel" in apply_to else 0.0,
    )
    e = _totals(
        ev, annual_km, years,
        cc_capex_idr_m if "ev" in apply_to else 0.0,
        cc_energy_idr_m_yr if "ev" in apply_to else 0.0,
    )

    if e.cost_per_km <= d.cost_per_km:
        comp = Metric(100.0, detail="EV at or below diesel cost/km")
    else:
        ratio = e.cost_per_km / d.cost_per_km
        comp = Metric(0.0 if ratio >= 1.5 else 100 - (ratio - 1) * 200)

    if e.net_capex_idr_m <= d.net_capex_idr_m:
        burden = Metric(100.0, detail="no incremental CAPEX premium")
    elif d.net_capex_idr_m <= 0:
        burden = Metric(0.0, detail="diesel net CAPEX zero with positive EV premium")
    elif e.net_capex_idr_m >= 2 * d.net_capex_idr_m:
        burden = Metric(0.0)
    else:
        burden = Metric(100 - ((e.net_capex_idr_m / d.net_capex_idr_m) - 1) * 100)

    saving = (d.annual_opex_idr_m - e.annual_opex_idr_m) / d.annual_opex_idr_m
    incremental = e.net_capex_idr_m - d.net_capex_idr_m
    annual_saving = d.annual_opex_idr_m - e.annual_opex_idr_m
    if annual_saving > 0:
        payback = incremental / annual_saving
        break_even = incremental / (annual_saving / annual_km)
    else:
        payback = None
        break_even = None
    recovered = payback is not None and payback <= years
    return TcoResult(d, e, comp, burden, saving, payback, break_even, recovered)
