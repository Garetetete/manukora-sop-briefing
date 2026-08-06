# Monthly S&OP Briefing Automation

Turns a monthly sales and inventory extract into a briefing a non-technical executive can read in
five minutes and act on: what changed, what is at risk, what to do next.

**[Read the generated briefing →](output/sop-briefing-2026-03.md)** — no setup required.

**[Part 2: Morning Intelligence Brief architecture →](docs/part2-morning-intelligence-brief.md)**

---

## The design decision everything rests on

> **Arithmetic is deterministic Python. The model only writes prose.**

Demand, trend, cover, revenue opportunity, reorder quantity and priority are all computed in
tested Python and handed to the model as fact. The model is never asked to calculate.

Then the output is checked rather than trusted: every number in the returned narrative is matched
against the computed set. An invented figure triggers one corrective retry, then falls back to a
deterministic template rather than shipping a briefing that reads well and is wrong.

Three things follow from this. The output is **verifiable** — every figure traces to a formula
with a test. The system **works without a model**, so the full analysis runs with no API key and
no network. And a model failure **degrades** instead of breaking.

## How it flows

```mermaid
flowchart TD
    CSV["data/mock_sales.csv"] --> LOADER

    subgraph DET["Deterministic Python — tested, no model involved"]
        direction TB
        LOADER["loader.py<br/>validate · pool Shopify + Amazon"]
        METRICS["metrics.py<br/>trend · bounded projection<br/>time-phased cover · revenue"]
        RULES["rules.py<br/>reorder + quantity + timing<br/>priority · tensions · data quality"]
        LOADER --> METRICS --> RULES
    end

    RULES --> FACTS["Computed facts<br/>the only figures that may be stated"]

    subgraph MODEL["Model layer"]
        direction TB
        PROMPT["narrative.py<br/>writes prose, never calculates"]
        GUARD{"Numeric guard<br/>is every figure<br/>in the facts?"}
        PROMPT --> GUARD
    end

    FACTS --> PROMPT
    GUARD -->|yes| OUT["output/sop-briefing-2026-03.md"]
    GUARD -->|"no · retry once"| PROMPT
    GUARD -->|"no · again"| TPL
    FACTS --> TPL["Deterministic template<br/>same figures, no model"]
    TPL --> OUT
```

The template is not a stub. It is a full second path to the same briefing, held to the same
numeric standard by the same test, which is what makes `--template-only` a real mode rather than
a degraded one.

## Why this is a Python CLI and not an n8n workflow

Manukora runs on n8n, so the choice deserves a reason rather than a preference.

**n8n earns its place in orchestration**: maintained connectors for Shopify, Amazon SP-API, Cin7,
Klaviyo, Gorgias and Slack, with OAuth, pagination and rate limits handled; scheduling, retries
and alerting as infrastructure instead of code; and a run history someone outside engineering can
read and re-run. That is exactly how [Part 2](docs/part2-morning-intelligence-brief.md) proposes
building the daily brief.

**It is the wrong home for this part.** The work here is business logic — a month-by-month
inventory simulation, per-SKU policy exceptions, revenue ranking, and a numeric guard on the
model's output. In n8n that becomes JavaScript inside code nodes: no unit tests, no meaningful
diffs, nothing reusable. The brief asks how the maths and the output were verified, and a canvas
cannot be tested.

So: **n8n orchestrates, Python decides.** Fetching, scheduling, delivery and retries belong to
the workflow engine; computation and correctness belong in tested code. The two parts of this
submission are the same argument seen from both ends.

## What it produces

From the twelve-SKU extract it flags four reorders, ranked by revenue at stake:

| # | SKU | Order | By | Cover | Revenue at stake |
|---|---|---:|---|---:|---:|
| 1 | MGO 514+ 500g | 650 units | April 2026 | 1.75 mo | $34,316/mo |
| 2 | MGO 850+ 500g | 450 units | April 2026 | 1.58 mo | $29,477/mo |
| 3 | Bioactive Energy 250g | 750 units | April 2026 | 1.62 mo | $17,396/mo |
| 4 | Bioactive Recovery 250g | 800 units | April 2026 | 1.42 mo | $16,476/mo |

Plus two judgement calls and three data-quality conflicts it refused to resolve silently.

## Four decisions worth explaining

**Cover is simulated, not divided.** The obvious formula is
`(stock + units_on_order) / monthly_demand`. It is wrong twice over: it credits stock that has not
arrived, and it assumes demand stays flat while every SKU here grows 6–13% a month.

Cover is instead walked forward month by month, crediting an inbound order only in the month it
lands. **This changes an answer.** MGO 1700+ reads as short on the static ratio — 840 units
against 300 a month is 2.80 months against a three-month target — but 400 units arrive in month
two, lifting real cover to 3.35. The static calculation would have triggered an unnecessary
purchase order on the most expensive line in the range. That case is a named test.

**`Order_Arrival_Months = 0` means no order exists.** Six of the twelve rows carry it. Read as an
immediate arrival it inflates every cover figure that depends on it, and nothing errors. There is
a deliberate contrast test showing the naive formula returning 52 months of cover where the honest
one returns under 3.

**Target cover is read per SKU.** MGO 1700+ targets three months, not two. Hard-coding two would
quietly mis-handle the premium line, so a test asserts the target actually drives the decision.

**A discontinued line is not restocked on autopilot.** Propolis is being phased out in Q2 2026 and
sits at 1.20 months of cover — above its 30-day floor, so it is flagged and not reordered. It is
also the fastest-growing SKU in the range at +40%, which the briefing raises as a question for the
business rather than resolving.

## Running it

Python 3.11+. No database, no containers, no credentials required.

```bash
git clone https://github.com/Garetetete/manukora-sop-briefing.git
cd manukora-sop-briefing
python -m sop.cli --template-only
```

That is the whole setup. **No dependencies, no virtualenv, no API key, no network** — the
deterministic path uses only the standard library, and it writes the full briefing to `output/`.

To have the narrative written by the model instead of the template:

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...                # free key at aistudio.google.com
python -m sop.cli
```

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini Developer API. Free key at aistudio.google.com |
| `GCP_PROJECT` | Vertex AI, using application default credentials |
| `GCP_LOCATION` | Defaults to `global` — Gemini 3.x is not served from regional endpoints |
| `SOP_MODEL` | Defaults to `gemini-3.1-pro-preview` |

`--template-only` skips the model entirely. The output is the same figures rendered
deterministically, and it is held to the same numeric standard by the same test.

## Tests

**67 tests, no network, no credentials, no database.**

```bash
python -m pytest
```

Organised by requirement of [`SPEC.md`](SPEC.md), which was written before the code, so the trace
from specification to implementation to proof is explicit.

| File | Covers |
|---|---|
| `test_req_001_002_loading.py` | Validation, rejection of malformed input, pooled channel demand |
| `test_req_003_004_trend_projection.py` | Launch-date exceptions, channel divergence, bounded projection |
| `test_req_005_006_cover_policy.py` | Time-phased cover, the `0` arrival trap, per-SKU targets, phase-out |
| `test_req_007_008_priority_reorder.py` | Revenue ranking, tensions, quantity and order-by timing |
| `test_req_009_data_quality.py` | Detecting the launch-date contradiction |
| `test_req_010_011_012_narrative.py` | Numeric guard, retry, fallback, CLI |

Three bugs were found by these tests rather than by reading code, including two cases where my own
assumption was wrong and the implementation was right. Both are written up in
[`docs/prompt-log.md`](docs/prompt-log.md).

## How verification was done

Beyond the suite: the deterministic template is run through the same numeric guard as the model,
so the fallback cannot drift; the generated briefing is re-checked against the computed figures
after every run; and the reorder arithmetic was reproduced by hand against the extract before the
thresholds were fixed.

## Layout

```
SPEC.md                     twelve numbered requirements, written before the code
data/mock_sales.csv         the supplied extract
output/                     the generated briefing, committed
docs/
  prompt-log.md             prompt v1 to v2, and where the AI was wrong
  assumptions.md            every judgement call, and what the extract lacks
  part2-...md               Morning Intelligence Brief architecture
sop/
  policy.py                 business exceptions, declarative and in one place
  loader.py                 read and validate; refuses to guess
  metrics.py                trend, projection, cover, revenue — no AI
  rules.py                  reorder decisions, priority, tensions, data quality — no AI
  narrative.py              the only layer that talks to a model
  cli.py                    entry point
```

Full reasoning for every assumption is in [`docs/assumptions.md`](docs/assumptions.md).
