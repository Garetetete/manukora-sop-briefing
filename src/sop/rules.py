"""Turning figures into decisions: reorder calls, priority and data-quality flags.

This is where the arithmetic from `metrics` becomes a recommendation an exec can
act on (REQ-006, REQ-007, REQ-008, REQ-009). Still no language model: the model
receives these decisions already made and only writes them up.
"""

from __future__ import annotations

from dataclasses import dataclass

from .loader import SkuRow
from .metrics import SkuMetrics, demand_for_month
from .policy import (
    BASELINE_MONTH,
    DEFAULT_LEAD_TIME_MONTHS,
    month_label,
    policy_for,
)

# Reorder quantities are rounded up to a round number: recommending 863 units
# implies a precision the forecast does not have.
_ROUNDING_UNITS = 50


@dataclass(frozen=True)
class Recommendation:
    sku: str
    reorder_units: int
    lead_time_months: int
    order_by_month: int
    order_by_label: str
    is_overdue: bool
    stockout_month: int | None
    stockout_label: str | None
    projected_cover_months: float
    target_months_cover: int
    revenue_opportunity_usd: float
    reasoning: str


@dataclass(frozen=True)
class Tension:
    sku: str
    description: str


@dataclass(frozen=True)
class DataQualityIssue:
    sku: str
    description: str
    assumption: str


def lead_time_months(row: SkuRow) -> int:
    """Observed lead time, or the default when no order is open (REQ-008).

    The extract does not state lead times. Open orders reveal them: where a
    shipment is in flight we take its arrival month as the SKU's lead time,
    otherwise we assume the shortest observed value.
    """
    return row.order_arrival_months if row.has_open_order else DEFAULT_LEAD_TIME_MONTHS


def _round_up(units: float) -> int:
    if units <= 0:
        return 0
    return int(-(-units // _ROUNDING_UNITS) * _ROUNDING_UNITS)


def needs_reorder(metrics: SkuMetrics) -> bool:
    """Whether the SKU should be restocked (REQ-006).

    Target cover is read per SKU rather than assumed uniform, so a premium line
    with a three-month target is judged against three months, not two. A SKU
    being phased out is only restocked if it falls below its own floor.
    """
    policy = policy_for(metrics.sku)
    if policy.reorder_only_below_cover_months is not None:
        return metrics.projected_cover_months < policy.reorder_only_below_cover_months
    return metrics.projected_cover_months < metrics.target_months_cover


def reorder_quantity(row: SkuRow, metrics: SkuMetrics) -> int:
    """Units to order: the gap to target cover plus consumption during lead time.

    Ordering only the shortfall would leave the SKU below target again by the
    time the shipment lands, so the lead-time window is included.
    """
    lead = lead_time_months(row)
    horizon = lead + metrics.target_months_cover

    required = sum(
        demand_for_month(BASELINE_MONTH + step, metrics.baseline_demand, metrics.projected_demand)
        for step in range(1, horizon + 1)
    )

    available = row.stock_on_hand
    if row.has_open_order and row.order_arrival_months <= horizon:
        available += row.units_on_order

    return _round_up(required - available)


def build_recommendation(row: SkuRow, metrics: SkuMetrics) -> Recommendation:
    lead = lead_time_months(row)
    units = reorder_quantity(row, metrics)

    if metrics.stockout_month is not None:
        order_by = metrics.stockout_month - lead
    else:
        order_by = BASELINE_MONTH + max(1, int(metrics.projected_cover_months) - lead)
    is_overdue = order_by <= BASELINE_MONTH
    order_by = max(order_by, BASELINE_MONTH + 1)

    cover = metrics.projected_cover_months
    reasoning = (
        f"Projected cover is {cover:.2f} months against a target of "
        f"{metrics.target_months_cover}. "
    )
    if metrics.stockout_month is not None:
        reasoning += f"Stock is projected to run out in {month_label(metrics.stockout_month)}. "
    if not row.has_open_order:
        reasoning += "No order is currently placed. "
    else:
        reasoning += (
            f"{row.units_on_order} units arrive in {month_label(BASELINE_MONTH + row.order_arrival_months)}, "
            "which is already accounted for. "
        )
    reasoning += (
        f"Demand is growing {metrics.monthly_growth * 100:.1f}% per month, so "
        f"${metrics.revenue_opportunity_usd:,.0f} of monthly revenue is at stake."
    )

    return Recommendation(
        sku=metrics.sku,
        reorder_units=units,
        lead_time_months=lead,
        order_by_month=order_by,
        order_by_label=month_label(order_by),
        is_overdue=is_overdue,
        stockout_month=metrics.stockout_month,
        stockout_label=month_label(metrics.stockout_month) if metrics.stockout_month else None,
        projected_cover_months=cover,
        target_months_cover=metrics.target_months_cover,
        revenue_opportunity_usd=metrics.revenue_opportunity_usd,
        reasoning=reasoning,
    )


def rank_recommendations(recs: list[Recommendation]) -> list[Recommendation]:
    """Order by revenue at stake, not by cover risk alone (REQ-007)."""
    return sorted(recs, key=lambda r: r.revenue_opportunity_usd, reverse=True)


def find_tensions(all_metrics: list[SkuMetrics]) -> list[Tension]:
    """Surface cases where the obvious ranking would mislead (REQ-007).

    Optimising purely on revenue would restock a line the business is
    discontinuing, and would treat a decelerating SKU like a growing one.
    """
    tensions: list[Tension] = []
    growths = [m.monthly_growth for m in all_metrics if m.monthly_growth > 0]
    median_growth = sorted(growths)[len(growths) // 2] if growths else 0.0

    for m in all_metrics:
        policy = policy_for(m.sku)

        if policy.phase_out_after_month is not None:
            tensions.append(
                Tension(
                    sku=m.sku,
                    description=(
                        f"Demand is growing {m.total_trend_change * 100:.0f}% across the series, "
                        f"the fastest in the range, yet the line is being discontinued after "
                        f"{month_label(policy.phase_out_after_month)}. Worth confirming the "
                        f"phase-out decision was made with this trend visible."
                    ),
                )
            )

        if m.channel_divergence:
            tensions.append(
                Tension(
                    sku=m.sku,
                    description=(
                        f"{m.channel_divergence}. Pooled demand still grew, so the total hides "
                        f"a channel problem worth investigating."
                    ),
                )
            )
        elif m.monthly_growth < median_growth / 2 and m.revenue_opportunity_usd > 20_000:
            tensions.append(
                Tension(
                    sku=m.sku,
                    description=(
                        f"High revenue at stake (${m.revenue_opportunity_usd:,.0f}/month) but growth "
                        f"of only {m.monthly_growth * 100:.1f}% per month, well below the range median. "
                        f"Volume is flattening, so do not size reorders on past growth."
                    ),
                )
            )

    return tensions


def find_data_quality_issues(rows: list[SkuRow]) -> list[DataQualityIssue]:
    """Report contradictions instead of resolving them silently (REQ-009)."""
    issues: list[DataQualityIssue] = []
    for row in rows:
        policy = policy_for(row.sku)
        if policy.first_full_month > 1:
            pre_launch = sum(
                row.demand[m] for m in range(1, policy.first_full_month)
            )
            if pre_launch > 0:
                issues.append(
                    DataQualityIssue(
                        sku=row.sku,
                        description=(
                            f"The brief states this product launched mid-January 2026 (mid-M2), "
                            f"but the extract records {pre_launch} units sold in M1 "
                            f"({month_label(1)}), before the stated launch."
                        ),
                        assumption=(
                            "Trend is measured from M2 onwards as instructed, and the M1 figures "
                            "are excluded from growth. They are left in the totals unchanged. "
                            "Worth confirming whether the launch date or the extract is wrong "
                            "before this feeds a real reorder decision."
                        ),
                    )
                )
    return issues
