"""REQ-001 loading and validation, REQ-002 pooled channel demand."""

import pytest

from sop.loader import ExtractError, load_extract

from .conftest import DATA, make_row

HEADER = (
    "SKU,Shopify_M1,Shopify_M2,Shopify_M3,Shopify_M4,"
    "Amazon_M1,Amazon_M2,Amazon_M3,Amazon_M4,"
    "Stock_On_Hand,Units_On_Order,Order_Arrival_Months,Target_Months_Cover,Retail_Price_USD"
)
GOOD_ROW = "Test SKU,10,10,10,10,5,5,5,5,100,0,0,2,9.99"


def _write(tmp_path, text):
    path = tmp_path / "extract.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_req_001_loads_every_supplied_sku(rows):
    assert len(rows) == 12


def test_req_001_missing_column_names_the_column(tmp_path):
    broken = HEADER.replace(",Stock_On_Hand", "") + "\n"
    with pytest.raises(ExtractError, match="Stock_On_Hand"):
        load_extract(_write(tmp_path, broken))


def test_req_001_non_numeric_value_is_rejected_not_coerced(tmp_path):
    bad = f"{HEADER}\nTest SKU,10,10,10,ten,5,5,5,5,100,0,0,2,9.99\n"
    with pytest.raises(ExtractError, match="Shopify_M4"):
        load_extract(_write(tmp_path, bad))


def test_req_001_empty_file_does_not_produce_an_empty_briefing(tmp_path):
    with pytest.raises(ExtractError, match="no SKU rows"):
        load_extract(_write(tmp_path, HEADER + "\n"))


def test_req_001_blank_sku_is_rejected(tmp_path):
    bad = f"{HEADER}\n,10,10,10,10,5,5,5,5,100,0,0,2,9.99\n"
    with pytest.raises(ExtractError, match="empty SKU"):
        load_extract(_write(tmp_path, bad))


def test_req_001_valid_file_round_trips(tmp_path):
    loaded = load_extract(_write(tmp_path, f"{HEADER}\n{GOOD_ROW}\n"))
    assert loaded[0].sku == "Test SKU"
    assert loaded[0].retail_price_usd == 9.99


def test_req_002_demand_pools_both_channels(by_sku):
    row = by_sku["Manuka Honey MGO 263+ 250g"]
    # M4: 956 Shopify + 648 Amazon
    assert row.demand[4] == 1604
    assert row.demand[1] == 1328


def test_req_002_channel_figures_remain_available_for_narrative(by_sku):
    row = by_sku["Manuka Honey MGO 100+ 250g"]
    assert row.shopify[4] == 644
    assert row.amazon[4] == 388
    assert row.demand[4] == 1032


def test_req_002_open_order_requires_both_units_and_an_arrival_month():
    """Order_Arrival_Months = 0 means no order exists, not immediate arrival."""
    assert make_row(units_on_order=0, order_arrival_months=0).has_open_order is False
    assert make_row(units_on_order=500, order_arrival_months=0).has_open_order is False
    assert make_row(units_on_order=500, order_arrival_months=1).has_open_order is True


def test_req_002_supplied_extract_has_six_skus_without_an_order(rows):
    """Guards the trap in the brief: six rows carry 0/0 and must not be credited."""
    without = [r.sku for r in rows if not r.has_open_order]
    assert len(without) == 6
    assert "Manuka Honey MGO 850+ 500g" in without
    assert DATA.exists()
