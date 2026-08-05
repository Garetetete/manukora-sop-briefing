"""Shared fixtures and a builder for synthetic SKU rows."""

from pathlib import Path

import pytest

from sop.loader import SkuRow, load_extract

DATA = Path(__file__).resolve().parents[1] / "data" / "mock_sales.csv"


@pytest.fixture
def rows() -> list[SkuRow]:
    return load_extract(DATA)


@pytest.fixture
def by_sku(rows) -> dict[str, SkuRow]:
    return {r.sku: r for r in rows}


def make_row(
    sku="Test SKU",
    shopify=(100, 100, 100, 100),
    amazon=(0, 0, 0, 0),
    stock_on_hand=1000,
    units_on_order=0,
    order_arrival_months=0,
    target_months_cover=2,
    retail_price_usd=10.0,
) -> SkuRow:
    """Build a row with explicit values, so each test states its own scenario."""
    return SkuRow(
        sku=sku,
        shopify={i + 1: v for i, v in enumerate(shopify)},
        amazon={i + 1: v for i, v in enumerate(amazon)},
        stock_on_hand=stock_on_hand,
        units_on_order=units_on_order,
        order_arrival_months=order_arrival_months,
        target_months_cover=target_months_cover,
        retail_price_usd=retail_price_usd,
    )
