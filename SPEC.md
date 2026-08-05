# Specification — Monthly S&OP Briefing Automation

Written **before** the implementation. Every requirement below has at least one test in
`tests/`, named after the requirement it covers, so the trace from spec to code to proof is
explicit.

**Goal:** turn a monthly sales and inventory extract into a briefing a non-technical executive
can read in five minutes and act on. The system must answer three questions: *what changed, what
is at risk, and what should we do next.*

## Design principle

> **Arithmetic is deterministic Python. The language model only writes prose.**

Every number — demand, trend, cover, revenue opportunity, reorder quantity, priority — is
computed in tested Python and passed to the model as validated input. The model never calculates
and never invents a figure. This makes the output verifiable, keeps the system working when the
model is unavailable, and is the reason the whole analysis can run with no API key.

---

## REQ-001 — Load and validate the input extract

The system reads a CSV with one row per SKU and the columns of the supplied extract.

- Reject the run with a clear message if a required column is missing.
- Reject non-numeric values in numeric columns rather than coercing them silently.
- Fail on an empty file rather than emitting an empty briefing.

**Rationale:** a briefing generated from a malformed extract is worse than no briefing, because
it looks authoritative.

## REQ-002 — Pooled channel demand

Shopify and Amazon draw from a single inventory position, so monthly demand per SKU is the sum of
both channels for that month.

- Channel-level figures are retained for narrative purposes, but every inventory calculation uses
  the pooled figure.

## REQ-003 — Trend, honouring product-launch exceptions

Compute month-over-month growth per SKU from pooled demand.

- Default: growth is measured across M1→M4.
- **Bioactive Blend SKUs launched mid-January 2026 (mid-M2), so their trend is measured M2→M4
  only.** Including M1 would distort the growth rate for these products.
- Channel divergence is detected and reported: a SKU whose channels move in opposite directions
  is flagged, because a pooled figure can hide a failing channel.

## REQ-004 — Forward demand projection

Project demand forward from the M4 baseline using each SKU's own average month-over-month growth.

- The projection horizon is **capped at 3 months**. Four observations do not support compounding a
  double-digit monthly growth rate over a longer horizon, and doing so would produce confident
  nonsense.
- M4 remains the stated sell-through baseline; the projection is used for risk timing, not to
  replace the baseline.
- The projection method and its horizon cap are reported in the output so the reader knows which
  figures are observed and which are modelled.

## REQ-005 — Time-phased inventory cover

Cover is calculated by simulating stock forward month by month, deducting projected demand and
adding incoming orders in the month they arrive.

- **`Order_Arrival_Months = 0` means no order exists.** It must never be read as an immediate
  arrival. Units on order are only credited in their arrival month.
- A naive `(stock + units_on_order) / demand` calculation is explicitly rejected: stock arriving in
  one month does not prevent a stockout that happens in three weeks.
- The output reports the projected month of stockout, not only a cover ratio.

## REQ-006 — Per-SKU inventory policy

Target cover is read per SKU rather than assumed uniform, and documented exceptions are applied.

- **MGO 1700+ 100g targets 3 months of cover**, not 2, because of its premium price point and
  longer supplier lead times.
- **Propolis Tincture 30ml is being phased out in Q2 2026.** Flag it if it risks a stockout before
  then, but do not recommend reordering unless cover falls below 30 days.

## REQ-007 — Revenue opportunity and reorder priority

Revenue opportunity is `retail price x projected monthly demand`.

- Reorder candidates are SKUs projected to fall below their target cover.
- Candidates are ranked by revenue opportunity, not by cover risk alone.
- Where the two rankings disagree, the tension is surfaced rather than silently resolved.
- A SKU with high revenue opportunity but weakening demand is flagged rather than optimised for
  blindly.

## REQ-008 — Reorder recommendation with quantity and timing

For each recommended SKU the system states how much to order and when to place the order.

- Quantity covers the gap to target cover plus projected consumption during the supplier lead
  time.
- Lead time is not supplied in the extract. It is inferred from the arrival months of open orders
  and recorded as an assumption.
- Order-by date is derived from the projected stockout month minus the lead time.

## REQ-009 — Data-quality reporting

Contradictions between the stated business context and the data are reported in the output rather
than silently resolved.

- Specifically: the brief states the Bioactive Blends launched mid-January 2026, yet the extract
  records December 2025 (M1) sales for them. The system reports the conflict, states the
  assumption adopted, and continues.
- Any SKU whose figures cannot support a requested calculation is named rather than dropped.

## REQ-010 — Executive narrative

The briefing is generated from the validated figures and is structured for a five-minute read:
what changed, what is at risk, what to do next, and the reasoning behind each recommendation.

- The model receives only computed values. It is instructed not to introduce numbers.
- Generated output is validated: any figure appearing in the narrative that does not match a
  computed value causes the run to fail loudly rather than ship a wrong briefing.
- Recommendations state business impact in dollars, not only units.

## REQ-011 — Runs without credentials

The full analysis runs with no API key and no network access.

- With a key, the narrative is written by the model.
- Without one, a deterministic template renders the same validated figures, and the briefing is
  still produced and still correct.
- The test suite runs entirely offline.

## REQ-012 — Command-line entry point and artifact

A single command runs the pipeline end to end and writes the briefing to `output/` as Markdown.

- The generated briefing is committed to the repository so it can be read without running
  anything.
- The run prints a short summary of what was produced and any warnings raised.

---

## Out of scope for this exercise

Declared, not forgotten: no web interface or API, no database, no live Shopify or Amazon
connectors, no authentication, no multi-period history beyond the four months supplied, and no
margin-based prioritisation — unit costs are not in the extract, so priority is expressed in
revenue as instructed.
