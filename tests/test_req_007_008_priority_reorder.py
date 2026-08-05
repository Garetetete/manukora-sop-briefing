"""REQ-007 revenue opportunity and priority, REQ-008 reorder quantity and timing."""

from sop.metrics import compute, compute_all
from sop.rules import (
    build_recommendation,
    find_tensions,
    lead_time_months,
    needs_reorder,
    rank_recommendations,
    reorder_quantity,
)

from .conftest import make_row


def _candidates(rows):
    out = []
    for row in rows:
        metrics = compute(row)
        if needs_reorder(metrics):
            out.append(build_recommendation(row, metrics))
    return rank_recommendations(out)


def test_req_007_revenue_opportunity_is_price_times_projected_demand():
    row = make_row(shopify=(100, 100, 100, 100), retail_price_usd=10.0)
    # flat demand, so projected month-ahead demand is 100
    assert compute(row).revenue_opportunity_usd == 1000.0


def test_req_007_at_least_three_skus_are_recommended(rows):
    assert len(_candidates(rows)) >= 3


def test_req_007_candidates_are_ranked_by_revenue_not_by_cover_risk(rows):
    ranked = _candidates(rows)
    values = [r.revenue_opportunity_usd for r in ranked]
    assert values == sorted(values, reverse=True)
    # The tightest cover is not automatically first.
    tightest = min(ranked, key=lambda r: r.projected_cover_months)
    assert ranked[0].revenue_opportunity_usd >= tightest.revenue_opportunity_usd


def test_req_007_the_top_candidate_is_the_one_with_most_revenue_at_stake(rows):
    ranked = _candidates(rows)
    assert ranked[0].sku == "Manuka Honey MGO 514+ 500g"


def test_req_007_phase_out_sku_is_excluded_from_recommendations(rows):
    assert "Propolis Tincture 30ml" not in [r.sku for r in _candidates(rows)]


def test_req_007_tension_is_raised_for_the_discontinued_growing_line(rows):
    tensions = find_tensions(compute_all(rows))
    propolis = [t for t in tensions if t.sku == "Propolis Tincture 30ml"]
    assert propolis and "discontinued" in propolis[0].description


def test_req_007_tension_is_raised_for_the_diverging_channel(rows):
    tensions = find_tensions(compute_all(rows))
    mgo100 = [t for t in tensions if t.sku == "Manuka Honey MGO 100+ 250g"]
    assert mgo100 and "Amazon" in mgo100[0].description


def test_req_008_lead_time_uses_the_open_order_when_one_exists(by_sku):
    assert lead_time_months(by_sku["Manuka Honey MGO 1700+ 100g"]) == 2
    assert lead_time_months(by_sku["Manuka Honey MGO 263+ 250g"]) == 1


def test_req_008_lead_time_falls_back_to_the_default_without_an_order(by_sku):
    assert lead_time_months(by_sku["Manuka Honey MGO 850+ 500g"]) == 1


def test_req_008_quantity_covers_lead_time_plus_target_not_just_the_gap():
    row = make_row(shopify=(100, 100, 100, 100), stock_on_hand=100, target_months_cover=2)
    metrics = compute(row)
    gap_only = metrics.target_months_cover * metrics.baseline_demand - row.stock_on_hand
    assert reorder_quantity(row, metrics) > gap_only


def test_req_008_quantity_is_rounded_to_a_round_number(rows):
    for rec in _candidates(rows):
        assert rec.reorder_units % 50 == 0


def test_req_008_a_sku_with_ample_stock_needs_nothing():
    row = make_row(shopify=(100, 100, 100, 100), stock_on_hand=10_000)
    assert reorder_quantity(row, compute(row)) == 0


def test_req_008_recommendation_states_when_to_place_the_order(rows):
    for rec in _candidates(rows):
        assert rec.order_by_label
        assert rec.reorder_units > 0
        assert "target of" in rec.reasoning


def test_req_008_open_order_is_acknowledged_in_the_reasoning(by_sku):
    row = by_sku["Manuka Honey MGO 1700+ 100g"]
    rec = build_recommendation(row, compute(row))
    assert "400 units arrive" in rec.reasoning
