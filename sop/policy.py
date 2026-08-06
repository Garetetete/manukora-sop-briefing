"""Business policy the arithmetic must respect.

Kept declarative and separate from the calculations, so that every exception is
visible in one place and adding a rule never means editing a formula.

Month index: M1 = December 2025 ... M4 = March 2026 (most recent actual).
Months 5 and beyond are projected.
"""

from __future__ import annotations

from dataclasses import dataclass

# M1 is December 2025; every other label is derived, so a month beyond the
# projection horizon still reads as a date instead of "M9".
_FIRST_MONTH = (2025, 12)
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

ACTUAL_MONTHS = (1, 2, 3, 4)
BASELINE_MONTH = 4

# REQ-004. Four observations do not support compounding a double-digit monthly
# growth rate indefinitely, so the projection horizon is capped rather than
# extended to whatever the caller asks for.
MAX_PROJECTION_MONTHS = 3

# REQ-008. Lead time is not supplied in the extract. Where a SKU has an open
# order we take its arrival month as the observed lead time; otherwise we fall
# back to this default, which matches the shortest observed arrival.
DEFAULT_LEAD_TIME_MONTHS = 1

# Q2 2026 covers April, May and June, i.e. projected months 5 to 7.
Q2_2026_LAST_MONTH = 7


@dataclass(frozen=True)
class SkuPolicy:
    """Per-SKU exceptions to the default treatment."""

    # First month the SKU traded normally. Growth before this month is not
    # meaningful and is excluded from the trend.
    first_full_month: int = 1

    # SKU is being discontinued after this projected month.
    phase_out_after_month: int | None = None

    # When phasing out, only recommend a reorder if cover falls below this many
    # months. Without it, a discontinued line would be restocked on autopilot.
    reorder_only_below_cover_months: float | None = None

    note: str = ""


DEFAULT_POLICY = SkuPolicy()

# Bioactive Blends launched mid-January 2026, which is mid-M2, so their trend is
# measured from M2 onwards (REQ-003). Note that the extract also records M1
# sales for them, which contradicts the stated launch date; that conflict is
# reported rather than silently resolved (REQ-009).
_BIOACTIVE = SkuPolicy(
    first_full_month=2,
    note="Launched mid-January 2026 (mid-M2); trend measured from M2 onwards.",
)

POLICIES: dict[str, SkuPolicy] = {
    "Bioactive Blend Immunity 250g": _BIOACTIVE,
    "Bioactive Blend Energy 250g": _BIOACTIVE,
    "Bioactive Blend Recovery 250g": _BIOACTIVE,
    "Propolis Tincture 30ml": SkuPolicy(
        phase_out_after_month=Q2_2026_LAST_MONTH,
        reorder_only_below_cover_months=1.0,  # 30 days
        note=(
            "Being phased out in Q2 2026. Flag stockout risk before then, but do "
            "not reorder unless cover drops below 30 days."
        ),
    ),
}


def policy_for(sku: str) -> SkuPolicy:
    """Return the policy for a SKU, or the default when none is declared."""
    return POLICIES.get(sku, DEFAULT_POLICY)


def month_label(month: int) -> str:
    """Human-readable label for a month index, for use in the briefing."""
    year, first = _FIRST_MONTH
    index = (first - 1) + (month - 1)
    return f"{_MONTH_NAMES[index % 12]} {year + index // 12}"
