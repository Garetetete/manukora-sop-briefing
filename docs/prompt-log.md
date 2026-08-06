# Prompt and AI usage log

Two different things are recorded here: the instruction stack the automation sends to the model,
and how I used AI to build the system. Working notes were in Spanish; this log is written in
English.

---

## Phase 0 — interrogating the brief before writing code

I did not start with code. I started by checking the stated context rules against the CSV, which
changed the design three times:

- **The launch dates contradict the data.** The brief says the Bioactive Blends launched
  mid-January 2026 (mid-M2), but the extract records December 2025 sales for all three. That
  became REQ-009: report the conflict, state the assumption, continue.
- **The tension the brief warns about is not present.** It asks to flag a SKU with high revenue
  opportunity but clearly declining demand. No SKU declines; measured the way the brief
  specifies, every one grows between 11.7% and 40.0% across its window. The real tensions are different — Propolis is the fastest-growing line in the range and
  is being discontinued, and MGO 100+ is the only SKU where a channel goes backwards.
- **Both static formulas mislead.** With demand growing 3.9–13.2% a month, `stock / last month`
  understates cover for anything with stock in transit, while `(stock + on order) / last month`
  overstates it for everything. That is why cover is simulated forward rather than divided.

Checking the rules against the data before designing was the highest-value hour of the exercise.

---

## The product prompt

### v1 — what I started with

```
Write a monthly S&OP briefing for a non-technical executive from the data below.
Cover what sold well, what is at risk, and what to reorder. Explain your reasoning.

[CSV pasted]
```

This is the obvious first attempt and it is wrong in a specific way: it hands the model the raw
extract and asks it to do arithmetic. The output read fluently and the numbers could not be
trusted — cover ratios that did not reconcile, and units-on-order treated as stock in hand.

### v2 — what the system actually uses

The full text is in [`sop/narrative.py`](../sop/narrative.py) (`SYSTEM_INSTRUCTION`,
`_SECTIONS`, `facts_block`). The shape:

```
You are writing a monthly S&OP briefing for a non-technical executive...

Hard rules:
1. Every number you write must appear verbatim in the FACTS below. Never calculate,
   never estimate, never round a figure that is given to you.
2. If a figure is not in the FACTS, do not mention it.
3. Say what the numbers mean for revenue, risk and timing. Do not restate the data.
4. Lead with the decision, then the reason.
5. Plain business English...

Write the briefing with exactly these sections: [seven named sections; Method is
appended in code rather than requested of the model]

--- FACTS ---
PERFORMANCE BY SKU        (computed demand, trend, cover, revenue opportunity)
NEAR-TERM RISK            (only stockouts within three months)
CAPITAL TIED UP           (overstock, computed)
REORDER RECOMMENDATIONS   (ranked, with quantity, order-by month and reasoning)
JUDGEMENT CALLS / DATA QUALITY / METHOD
```

### What changed and why

**The model stopped calculating.** Every figure is computed in tested Python and passed in as
fact. This is the whole design, not a prompt tweak: it is what makes the output verifiable and
what lets the system run correctly with no model at all.

**The output is checked, not trusted.** Numbers in the returned text are matched against the
computed set. An invented figure triggers one corrective retry, then falls back to a
deterministic template. In the final run the guard passed on the first attempt.

**Risk was scoped after reading the first real output.** v2a listed every stockout the simulation
found, including ones eight to twelve months away. Technically true, useless to an executive. The
facts block now carries near-term risk in its own section, and the prompt instructs the model to
use only that section for the risk narrative.

**Overstock was added because the model found it.** In an early run it observed that MGO 100+ was
tying up working capital — a fair inference, but one the model had made rather than been given.
Rather than remove the observation I made it a computed field, so the insight survives with a
number behind it.

---

## Where AI helped, where it was wrong

**On reconstructing this from git:** items 1 to 5 were found and fixed during development, before
the module they affect was first committed, so they are not visible as fix commits. The tests
written to catch them are in the suite and are named for what they check. Item 6 is visible in
history, as commit `32651c9`.

**Helped:** scaffolding the module layout from the spec, generating the bulk of the test suite,
and drafting prose. The `docs` and `README` were drafted with AI and edited by hand.

**Wrong, and how I found it:**

1. **The numeric guard's regex swallowed trailing commas.** `"April 2026, month 5"` was read as
   the number `2026,` and flagged as unsupported. Caught by a test written for exactly that
   sentence. Fixed by requiring thousand separators to be followed by three digits.

2. **The guard flagged the system's own output.** SKU names contain digits — `MGO 514+ 500g` — and
   the channel-divergence sentence contains a computed delta. Both were reported as invented
   figures. Caught by a test that runs the guard over the deterministic template, which by
   definition cannot hallucinate. Fixed by admitting identifiers and pipeline-derived strings.

3. **Two of my own test assertions were wrong, and the code was right.** I asserted that a SKU
   with a large inbound order would never stock out; over a 24-month simulation it eventually
   does. And I asserted MGO 1700+ needed reordering based on static cover of 2.80 against a target
   of 3 — but time-phasing the 400 units in transit lifts it to 3.35, so it does not. **The static
   calculation would have triggered an unnecessary purchase order on the premium line.** That is
   now a named test.

4. **The model ignored two explicit instructions.** It omitted the title and the Method section
   despite both being in the prompt. Rather than escalate the wording, both are now added in code:
   they are our facts, not something the model should have to remember.

5. **Wrong model and wrong region.** `gemini-2.0-flash` returned 404, and so did Gemini 3.x on
   `us-central1`. The 3.x publisher models are served from the `global` Vertex endpoint. Found by
   probing candidates directly rather than guessing.

6. **The documented run command did not work.** I had been running with `PYTHONPATH=src` in my
   own shell the whole time, so a src-layout import error never surfaced. Cloning the published
   repository into a clean directory and following my own README produced
   `ModuleNotFoundError: No module named 'sop'` on the very first command. The package now lives
   at the repository root, so `python -m sop.cli --template-only` works from a fresh clone with
   no install step at all.

Items 1 to 3 were found by tests, not by reading code. That is the argument for writing them.
Item 6 was found by using the artifact the way a stranger would, which no test would have caught:
the suite passed the entire time.
