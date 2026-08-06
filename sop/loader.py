"""Reading and validating the monthly extract (REQ-001, REQ-002).

A briefing built on a malformed extract is worse than no briefing, because it
still looks authoritative. So this module refuses to guess: a missing column, a
non-numeric value or an empty file stops the run with a message naming the
problem.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .policy import ACTUAL_MONTHS

INT_COLUMNS = (
    [f"Shopify_M{m}" for m in ACTUAL_MONTHS]
    + [f"Amazon_M{m}" for m in ACTUAL_MONTHS]
    + ["Stock_On_Hand", "Units_On_Order", "Order_Arrival_Months", "Target_Months_Cover"]
)
FLOAT_COLUMNS = ["Retail_Price_USD"]
REQUIRED_COLUMNS = ["SKU"] + INT_COLUMNS + FLOAT_COLUMNS


class ExtractError(ValueError):
    """The extract cannot be trusted, so the run stops."""


@dataclass(frozen=True)
class SkuRow:
    """One SKU as supplied, with pooled demand derived (REQ-002)."""

    sku: str
    shopify: dict[int, int]
    amazon: dict[int, int]
    stock_on_hand: int
    units_on_order: int
    order_arrival_months: int
    target_months_cover: int
    retail_price_usd: float

    @property
    def demand(self) -> dict[int, int]:
        """Pooled monthly demand.

        Shopify and Amazon draw from one inventory position, so every inventory
        calculation uses the sum. Channel figures stay available for narrative
        purposes, but never drive the arithmetic.
        """
        return {m: self.shopify[m] + self.amazon[m] for m in ACTUAL_MONTHS}

    @property
    def has_open_order(self) -> bool:
        """True when a confirmed shipment exists.

        `Order_Arrival_Months = 0` means no order is placed. It does not mean
        the order arrives immediately, and treating it that way would inflate
        every cover figure that depends on it.
        """
        return self.units_on_order > 0 and self.order_arrival_months > 0


def _to_int(value: str, column: str, sku: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ExtractError(
            f"{sku!r}: column {column!r} expects a whole number, got {value!r}"
        ) from None


def _to_float(value: str, column: str, sku: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ExtractError(
            f"{sku!r}: column {column!r} expects a number, got {value!r}"
        ) from None


def load_extract(path: str | Path) -> list[SkuRow]:
    """Read the CSV extract into validated rows.

    Raises ExtractError when the file is empty, a required column is missing or
    a numeric field cannot be parsed.
    """
    path = Path(path)
    if not path.is_file():
        raise ExtractError(f"{path}: no such file")
    # utf-8-sig: a CSV saved from Excel carries a byte-order mark, which would
    # otherwise turn the first header into "﻿SKU" and report SKU missing.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ExtractError(
                f"{path.name}: missing required column(s): {', '.join(missing)}"
            )

        rows: list[SkuRow] = []
        for raw in reader:
            sku = (raw.get("SKU") or "").strip()
            if not sku:
                raise ExtractError(f"{path.name}: a row has an empty SKU")
            rows.append(
                SkuRow(
                    sku=sku,
                    shopify={m: _to_int(raw[f"Shopify_M{m}"], f"Shopify_M{m}", sku) for m in ACTUAL_MONTHS},
                    amazon={m: _to_int(raw[f"Amazon_M{m}"], f"Amazon_M{m}", sku) for m in ACTUAL_MONTHS},
                    stock_on_hand=_to_int(raw["Stock_On_Hand"], "Stock_On_Hand", sku),
                    units_on_order=_to_int(raw["Units_On_Order"], "Units_On_Order", sku),
                    order_arrival_months=_to_int(
                        raw["Order_Arrival_Months"], "Order_Arrival_Months", sku
                    ),
                    target_months_cover=_to_int(
                        raw["Target_Months_Cover"], "Target_Months_Cover", sku
                    ),
                    retail_price_usd=_to_float(
                        raw["Retail_Price_USD"], "Retail_Price_USD", sku
                    ),
                )
            )

    if not rows:
        raise ExtractError(f"{path.name}: no SKU rows found")
    return rows
