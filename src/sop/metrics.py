"""Deterministic arithmetic: trend, projection, cover and revenue opportunity.

Nothing in this module talks to a language model. Every figure the briefing
quotes is produced here and can be reproduced by hand from the extract, which
is what makes the output verifiable (REQ-003, REQ-004, REQ-005, REQ-007).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .loader import SkuRow
from .policy import (
    ACTUAL_MONTHS,
    BASELINE_MONTH,
    MAX_PROJECTION_MONTHS,
    policy_for,
)

# Guard for the cover simulation. No real SKU here carries two years of stock;
# this only stops a pathological input from looping forever.
_MAX_SIMULATED_MONTHS = 24


@dataclass(frozen=True)
class SkuMetrics:
    """Everything computed for one SKU, ready to be described in prose."""

    sku: str
    demand: dict[int, int]
    baseline_demand: int
    trend_window: tuple[int, int]
    monthly_growth: float
    total_trend_change: float
    projected_demand: dict[int, int]
    channel_divergence: str | None
    current_cover_months: float
    projected_cover_months: float
    stockout_month: int | None
    revenue_opportunity_usd: float
    target_months_cover: int
    retail_price_usd: float
    stock_on_hand: int
    units_on_order: int
    order_arrival_months: int
    has_open_order: bool
    notes: list[str] = field(default_factory=list)


def trend_window(sku: str) -> tuple[int, int]:
    """Months across which growth is meaningful for this SKU (REQ-003).

    Products that launched partway through the series would show a distorted
    growth rate if measured from M1, so their window starts at the first month
    they traded normally.
    """
    return policy_for(sku).first_full_month, BASELINE_MONTH


def average_monthly_growth(demand: dict[int, int], window: tuple[int, int]) -> float:
    """Mean month-over-month growth across the window.

    A mean of the observed steps, not a fitted curve: with four observations a
    regression would imply more confidence than the data carries.
    """
    first, last = window
    steps = [
        demand[m + 1] / demand[m] - 1.0
        for m in range(first, last)
        if demand[m] > 0
    ]
    return sum(steps) / len(steps) if steps else 0.0


def total_change(demand: dict[int, int], window: tuple[int, int]) -> float:
    """Total growth across the whole window, for narrative context."""
    first, last = window
    return demand[last] / demand[first] - 1.0 if demand[first] > 0 else 0.0


def project_demand(baseline: int, growth: float, months: int = MAX_PROJECTION_MONTHS) -> dict[int, int]:
    """Project demand forward from the baseline month (REQ-004).

    The horizon is capped: beyond it the compounded figure would look precise
    while being unsupported by four observations.
    """
    months = min(months, MAX_PROJECTION_MONTHS)
    projected: dict[int, int] = {}
    value = float(baseline)
    for step in range(1, months + 1):
        value *= 1.0 + growth
        projected[BASELINE_MONTH + step] = max(0, round(value))
    return projected


def demand_for_month(month: int, baseline: int, projected: dict[int, int]) -> int:
    """Expected demand in a future month.

    Inside the projection horizon we use the projected figure. Beyond it we hold
    demand flat at the last projected month rather than compounding further,
    which keeps the cover simulation honest about what is modelled and what is
    merely extended.
    """
    if month in projected:
        return projected[month]
    if projected:
        return projected[max(projected)]
    return baseline


def detect_channel_divergence(row: SkuRow) -> str | None:
    """Report channels moving in opposite directions (REQ-003).

    A pooled figure can rise while one channel is failing. That is a decision
    the exec needs, and it disappears if only the total is reported.
    """
    prev, last = BASELINE_MONTH - 1, BASELINE_MONTH
    shopify_delta = row.shopify[last] - row.shopify[prev]
    amazon_delta = row.amazon[last] - row.amazon[prev]
    if shopify_delta > 0 and amazon_delta < 0:
        return (
            f"Shopify grew by {shopify_delta} units while Amazon fell by "
            f"{abs(amazon_delta)} in the latest month"
        )
    if amazon_delta > 0 and shopify_delta < 0:
        return (
            f"Amazon grew by {amazon_delta} units while Shopify fell by "
            f"{abs(shopify_delta)} in the latest month"
        )
    return None


def simulate_cover(
    row: SkuRow, baseline: int, projected: dict[int, int]
) -> tuple[float, int | None]:
    """Walk stock forward month by month (REQ-005).

    Incoming orders are credited only in the month they arrive, so a shipment
    landing in two months cannot rescue a stockout that happens next month. A
    naive (stock + units_on_order) / demand would miss exactly that.

    Assumption: an arriving order is available for that month's demand.

    Returns the months of cover and the month a stockout is projected, if any.
    """
    stock = float(row.stock_on_hand)
    arrival_month = (
        BASELINE_MONTH + row.order_arrival_months if row.has_open_order else None
    )
    cover = 0.0

    for step in range(1, _MAX_SIMULATED_MONTHS + 1):
        month = BASELINE_MONTH + step
        if arrival_month is not None and month == arrival_month:
            stock += row.units_on_order

        need = demand_for_month(month, baseline, projected)
        if need <= 0:
            cover += 1.0
            continue

        if stock >= need:
            stock -= need
            cover += 1.0
        else:
            cover += stock / need
            return round(cover, 2), month

    return float(_MAX_SIMULATED_MONTHS), None


def compute(row: SkuRow) -> SkuMetrics:
    """Compute every figure for one SKU."""
    demand = row.demand
    window = trend_window(row.sku)
    growth = average_monthly_growth(demand, window)
    baseline = demand[BASELINE_MONTH]
    projected = project_demand(baseline, growth)

    projected_cover, stockout_month = simulate_cover(row, baseline, projected)
    current_cover = baseline and row.stock_on_hand / baseline or 0.0

    # REQ-007. Revenue opportunity uses projected demand for the month ahead,
    # priced at retail. Unit costs are not in the extract, so this is revenue at
    # stake rather than margin at stake, as the brief specifies.
    next_month_demand = projected.get(BASELINE_MONTH + 1, baseline)
    revenue_opportunity = next_month_demand * row.retail_price_usd

    notes: list[str] = []
    policy = policy_for(row.sku)
    if policy.note:
        notes.append(policy.note)

    return SkuMetrics(
        sku=row.sku,
        demand=demand,
        baseline_demand=baseline,
        trend_window=window,
        monthly_growth=growth,
        total_trend_change=total_change(demand, window),
        projected_demand=projected,
        channel_divergence=detect_channel_divergence(row),
        current_cover_months=round(current_cover, 2),
        projected_cover_months=projected_cover,
        stockout_month=stockout_month,
        revenue_opportunity_usd=round(revenue_opportunity, 2),
        target_months_cover=row.target_months_cover,
        retail_price_usd=row.retail_price_usd,
        stock_on_hand=row.stock_on_hand,
        units_on_order=row.units_on_order,
        order_arrival_months=row.order_arrival_months,
        has_open_order=row.has_open_order,
        notes=notes,
    )


def compute_all(rows: list[SkuRow]) -> list[SkuMetrics]:
    return [compute(row) for row in rows]
