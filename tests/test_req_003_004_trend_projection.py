"""REQ-003 trend with launch exceptions, REQ-004 bounded forward projection."""

from sop.metrics import (
    average_monthly_growth,
    compute,
    demand_for_month,
    detect_channel_divergence,
    project_demand,
    trend_window,
)
from sop.policy import MAX_PROJECTION_MONTHS

from .conftest import make_row


def test_req_003_default_trend_window_covers_the_whole_series():
    assert trend_window("Manuka Honey MGO 263+ 250g") == (1, 4)


def test_req_003_bioactive_trend_starts_at_m2_because_it_launched_mid_m2():
    for sku in (
        "Bioactive Blend Immunity 250g",
        "Bioactive Blend Energy 250g",
        "Bioactive Blend Recovery 250g",
    ):
        assert trend_window(sku) == (2, 4), sku


def test_req_003_launch_exception_changes_the_reported_growth(by_sku):
    """Measuring a mid-series launch from M1 would understate its real growth."""
    row = by_sku["Bioactive Blend Recovery 250g"]
    from_m1 = average_monthly_growth(row.demand, (1, 4))
    from_m2 = average_monthly_growth(row.demand, (2, 4))
    assert from_m2 != from_m1
    assert compute(row).monthly_growth == from_m2


def test_req_003_growth_is_the_mean_of_observed_steps():
    row = make_row(shopify=(100, 110, 121, 133))
    # steps: +10%, +10%, ~+9.9%
    assert 0.099 < compute(row).monthly_growth < 0.101


def test_req_003_zero_baseline_does_not_divide_by_zero():
    row = make_row(shopify=(0, 0, 0, 0))
    assert compute(row).monthly_growth == 0.0


def test_req_003_channel_divergence_is_reported():
    """A pooled figure can rise while one channel falls; that must not be hidden."""
    diverging = make_row(shopify=(100, 100, 100, 200), amazon=(100, 100, 100, 50))
    message = detect_channel_divergence(diverging)
    assert message is not None
    assert "Amazon fell" in message


def test_req_003_mgo_100_is_the_diverging_sku_in_the_extract(by_sku):
    """Amazon dropped 404 to 388 while Shopify grew: the only channel decline present."""
    assert compute(by_sku["Manuka Honey MGO 100+ 250g"]).channel_divergence is not None
    assert compute(by_sku["Manuka Honey MGO 263+ 250g"]).channel_divergence is None


def test_req_004_projection_applies_compound_growth():
    projected = project_demand(baseline=1000, growth=0.10, months=3)
    assert projected == {5: 1100, 6: 1210, 7: 1331}


def test_req_004_horizon_is_capped_even_when_more_is_requested():
    projected = project_demand(baseline=1000, growth=0.10, months=12)
    assert len(projected) == MAX_PROJECTION_MONTHS
    assert max(projected) == 4 + MAX_PROJECTION_MONTHS


def test_req_004_beyond_the_horizon_demand_is_held_flat_not_compounded():
    """Extending a modelled trend indefinitely would look precise and be unfounded."""
    projected = project_demand(baseline=1000, growth=0.10)
    last = projected[max(projected)]
    assert demand_for_month(20, 1000, projected) == last


def test_req_004_zero_growth_projects_the_baseline():
    assert project_demand(baseline=500, growth=0.0) == {5: 500, 6: 500, 7: 500}


def test_req_004_projection_never_goes_negative():
    projected = project_demand(baseline=100, growth=-0.9, months=3)
    assert all(v >= 0 for v in projected.values())
