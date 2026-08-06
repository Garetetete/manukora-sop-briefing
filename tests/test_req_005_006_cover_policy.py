"""REQ-005 time-phased cover, REQ-006 per-SKU inventory policy.

These are the two requirements the brief plants traps for, so they carry the
most explicit tests.
"""

from sop.metrics import compute
from sop.rules import needs_reorder

from .conftest import make_row


def test_req_005_units_on_order_with_zero_arrival_are_never_credited():
    """`Order_Arrival_Months = 0` means no order exists.

    Reading it as an immediate arrival is the single easiest way to produce a
    confidently wrong briefing, so it is asserted directly.
    """
    no_order = make_row(shopify=(100, 100, 100, 100), stock_on_hand=200,
                        units_on_order=5000, order_arrival_months=0)
    assert compute(no_order).stockout_month is not None
    assert compute(no_order).projected_cover_months < 3


def test_req_005_naive_stock_plus_on_order_would_have_passed_here():
    """Contrast case: the naive formula gives 52 months, the honest one gives ~2."""
    row = make_row(shopify=(100, 100, 100, 100), stock_on_hand=200,
                   units_on_order=5000, order_arrival_months=0)
    naive = (row.stock_on_hand + row.units_on_order) / row.demand[4]
    assert naive > 50
    assert compute(row).projected_cover_months < 3


def test_req_005_an_order_is_credited_only_in_its_arrival_month():
    late = make_row(shopify=(100, 100, 100, 100), stock_on_hand=150,
                    units_on_order=1000, order_arrival_months=3)
    metrics = compute(late)
    # Stock covers month 5 and part of month 6; the shipment lands in month 7.
    assert metrics.stockout_month == 6


def test_req_005_an_arriving_order_pushes_the_stockout_out():
    """The same stock with a shipment landing in time survives far longer."""
    without = make_row(shopify=(100, 100, 100, 100), stock_on_hand=150)
    saved = make_row(shopify=(100, 100, 100, 100), stock_on_hand=150,
                     units_on_order=1000, order_arrival_months=1)
    assert compute(without).stockout_month == 6
    assert compute(saved).stockout_month > 12


def test_req_005_stockout_month_is_reported_not_only_a_ratio():
    row = make_row(shopify=(100, 100, 100, 100), stock_on_hand=250)
    metrics = compute(row)
    assert metrics.stockout_month == 7
    assert metrics.projected_cover_months > 2


def test_req_005_growing_demand_consumes_cover_faster_than_a_static_ratio():
    """Static cover flatters a growing SKU, which is why the simulation projects."""
    row = make_row(shopify=(100, 120, 144, 173), stock_on_hand=692)
    metrics = compute(row)
    static = row.stock_on_hand / row.demand[4]
    assert metrics.projected_cover_months < static


def test_req_006_target_cover_is_read_per_sku_not_assumed_uniform(by_sku):
    assert compute(by_sku["Manuka Honey MGO 1700+ 100g"]).target_months_cover == 3
    assert compute(by_sku["Manuka Honey MGO 263+ 250g"]).target_months_cover == 2


def test_req_006_the_target_actually_drives_the_decision():
    """A SKU at 2.5 months of cover is short against a 3-month target and fine
    against a 2-month one. Hard-coding 2 would silently mis-handle the premium
    line."""
    base = dict(shopify=(100, 100, 100, 100), amazon=(0, 0, 0, 0), stock_on_hand=250)
    assert needs_reorder(compute(make_row(**base, target_months_cover=3))) is True
    assert needs_reorder(compute(make_row(**base, target_months_cover=2))) is False


def test_req_006_premium_sku_clears_its_three_month_target_once_inbound_stock_counts(by_sku):
    """MGO 1700+ reads as short on a static ratio (840 / 300 = 2.80 months), but
    400 units land in month two, and time-phasing them lifts it to 3.35 months.
    The static view would have triggered an unnecessary purchase order."""
    metrics = compute(by_sku["Manuka Honey MGO 1700+ 100g"])
    static = metrics.stock_on_hand / metrics.baseline_demand
    assert static < metrics.target_months_cover
    assert metrics.projected_cover_months > metrics.target_months_cover
    assert needs_reorder(metrics) is False


def test_req_006_phase_out_sku_is_not_reordered_above_its_floor(by_sku):
    """Propolis sits near 36 days of cover: flagged, but above the 30-day floor."""
    metrics = compute(by_sku["Propolis Tincture 30ml"])
    assert metrics.projected_cover_months < metrics.target_months_cover
    assert metrics.projected_cover_months > 1.0
    assert needs_reorder(metrics) is False


def test_req_006_phase_out_sku_is_reordered_if_it_drops_below_thirty_days():
    critical = make_row(sku="Propolis Tincture 30ml", shopify=(76, 88, 96, 104),
                        amazon=(44, 52, 56, 64), stock_on_hand=100,
                        target_months_cover=2, retail_price_usd=34.99)
    assert compute(critical).projected_cover_months < 1.0
    assert needs_reorder(compute(critical)) is True


def test_req_006_healthy_sku_is_not_flagged(by_sku):
    assert needs_reorder(compute(by_sku["Manuka Honey MGO 100+ 250g"])) is False
