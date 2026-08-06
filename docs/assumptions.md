# Assumptions and known limits

Everything here is a judgement I made because the extract or the brief did not settle it. Each is
implemented in code and covered by a test, so changing an assumption means changing one value,
not hunting through formulas.

## Conflicts found in the source data

**Bioactive Blends: the launch date and the sales data disagree.** The brief states these
launched mid-January 2026, which is mid-M2. The extract records M1 (December 2025) sales of 384,
272 and 248 units. Both cannot be true.

*Assumption taken:* trend is measured from M2 onwards as the brief instructs, so the pre-launch
months are excluded from growth. The M1 units are left in the historical totals unchanged, since
removing real recorded sales would be a larger claim than leaving them. **This should be resolved
before the output drives a real purchase order** — if the December sales are genuine, the growth
rates for these three SKUs are overstated; if the launch date is right, the extract has bad rows.
Reported in the briefing rather than resolved silently.

## Interpretation of the brief

**"Projected monthly demand" versus "M4 as the sell-through baseline."** The brief uses both. I
treat M4 as the baseline for current sell-through, as instructed, and use a forward projection for
risk timing and for revenue opportunity. Worth noting: **the priority ranking is identical either
way** — all twelve positions are unchanged whether ranked on M4 or on projected demand. The
projection changes *when* a SKU becomes urgent, not *which* SKU matters most.

**Projection horizon is capped at three months.** Four observations do not support compounding a
double-digit monthly growth rate further. Beyond the cap, demand is held flat rather than
compounded, so the cover simulation never implies precision the data cannot carry.

**Growth is the mean of observed month-over-month steps**, not a fitted regression. With four
points a regression would look more rigorous and mean less.

## Inventory and ordering

**An arriving order is available for that month's demand.** The extract gives arrival in whole
months, so a shipment landing in month *n* is credited at the start of month *n*.

**Lead time is inferred, because it is not supplied.** Where a SKU has an open order, its
`Order_Arrival_Months` is taken as the observed lead time. Where none is open, the default is one
month, which is the shortest arrival observed in the extract. MGO 1700+ carries a two-month
arrival, consistent with the brief's note about longer supplier lead times for that line.

**Reorder quantity covers lead time plus target cover.** Ordering only the shortfall would leave
the SKU below target again by the time the shipment lands. Quantities are rounded up to the
nearest 50 units, because recommending 863 units implies a precision the forecast does not have.

**A SKU within its lead time of falling below target is a watch item, not a reorder.** Clearing
the target today is not the same as needing no decision: at a one-month lead time, an order placed
after cover drops below target is already late. Without this the largest single revenue exposure
in the extract would have appeared nowhere in the briefing.

**Overstock is defined as stock beyond twice the target cover.** The brief does not ask for this,
but it asks what is at risk, and capital sitting in a warehouse is a risk of a different kind. The
threshold is a judgement call, not a standard.

## What the extract does not contain

- **Unit costs and margins.** Priority is therefore expressed as revenue at stake, as the brief
  specifies, not as profit at stake. A low-margin SKU and a high-margin one with the same revenue
  rank equally here, which would not be right in a real S&OP meeting.
- **Supplier minimum order quantities.** Recommended quantities may not be orderable as stated.
- **Explicit lead times.** Inferred, as above.
- **Warehouse capacity.** Nothing stops the system recommending more stock than there is room for.
- **Price changes, promotions or marketing spend.** Growth is treated as organic demand. A spike
  driven by a discount would be projected forward as if it were a trend.
- **Returns and refunds.** Units sold are treated as units consumed.

## Scope

Declared, not forgotten: no web interface, no API, no database, no live Shopify or Amazon
connectors, no authentication, no history beyond the four supplied months.
