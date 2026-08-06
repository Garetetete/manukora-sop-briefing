"""The only layer that talks to a language model (REQ-010, REQ-011).

The model receives figures that are already computed and validated, and is asked
to write prose. It is never asked to calculate. Whatever it returns is then
checked against the computed values: a number in the narrative that does not
appear in the facts fails the run rather than shipping a wrong briefing.

If no credentials are available the same facts are rendered by a deterministic
template, so the briefing is always produced and always correct.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .loader import SkuRow
from .metrics import SkuMetrics, compute_all
from .policy import BASELINE_MONTH, MAX_PROJECTION_MONTHS, month_label
from .rules import (
    DataQualityIssue,
    Recommendation,
    build_recommendation,
    find_data_quality_issues,
    find_tensions,
    needs_reorder,
    rank_recommendations,
    Tension,
)


@dataclass
class BriefingFacts:
    """Everything the briefing may state. Nothing outside this is permitted."""

    period_label: str
    metrics: list[SkuMetrics]
    recommendations: list[Recommendation]
    tensions: list[Tension]
    data_quality: list[DataQualityIssue]
    top_growth: list[SkuMetrics] = field(default_factory=list)
    slowest_growth: list[SkuMetrics] = field(default_factory=list)
    total_revenue_at_risk: float = 0.0


def build_facts(rows: list[SkuRow]) -> BriefingFacts:
    metrics = compute_all(rows)
    by_sku = {r.sku: r for r in rows}

    recs = [
        build_recommendation(by_sku[m.sku], m) for m in metrics if needs_reorder(m)
    ]
    recs = rank_recommendations(recs)

    ranked_growth = sorted(metrics, key=lambda m: m.monthly_growth, reverse=True)

    return BriefingFacts(
        period_label=month_label(BASELINE_MONTH),
        metrics=metrics,
        recommendations=recs,
        tensions=find_tensions(metrics),
        data_quality=find_data_quality_issues(rows),
        top_growth=ranked_growth[:3],
        slowest_growth=ranked_growth[-3:][::-1],
        total_revenue_at_risk=round(sum(r.revenue_opportunity_usd for r in recs), 2),
    )


# --------------------------------------------------------------------------
# Numeric guard (REQ-010)
# --------------------------------------------------------------------------

# Thousand separators must be followed by exactly three digits, so a trailing
# comma in prose ("April 2026, month 5") is not swallowed into the number.
NEAR_TERM_LAST_MONTH = BASELINE_MONTH + MAX_PROJECTION_MONTHS

_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

# Month indices, list positions and calendar years are structural, not claims
# about the business, so they are always permitted.
_STRUCTURAL = {str(n) for n in range(0, 13)} | {"2025", "2026"}


def _variants(value: float) -> set[str]:
    """String forms a figure may legitimately take in prose."""
    out: set[str] = set()
    as_int = round(value)
    out.add(f"{as_int}")
    out.add(f"{as_int:,}")
    out.add(f"{value:.1f}")
    out.add(f"{value:.2f}")
    out.add(f"{value:,.0f}")
    out.add(f"{value:,.1f}")
    out.add(f"{value:,.2f}")
    return out


def allowed_numbers(facts: BriefingFacts) -> set[str]:
    """Every numeric token the narrative is allowed to contain."""
    allowed: set[str] = set(_STRUCTURAL)

    for m in facts.metrics:
        for value in (
            *m.demand.values(),
            *m.projected_demand.values(),
            m.baseline_demand,
            m.stock_on_hand,
            m.units_on_order,
            m.order_arrival_months,
            m.target_months_cover,
            m.current_cover_months,
            m.projected_cover_months,
            m.revenue_opportunity_usd,
            m.retail_price_usd,
            m.overstock_units,
            m.overstock_value_usd,
            abs(m.monthly_growth) * 100,
            abs(m.total_trend_change) * 100,
        ):
            allowed |= _variants(float(value))

    for r in facts.recommendations:
        for value in (
            r.reorder_units,
            r.lead_time_months,
            r.projected_cover_months,
            r.target_months_cover,
            r.revenue_opportunity_usd,
        ):
            allowed |= _variants(float(value))

    allowed |= _variants(facts.total_revenue_at_risk)
    allowed |= _variants(float(len(facts.recommendations)))
    allowed |= _variants(float(MAX_PROJECTION_MONTHS))

    # Product codes are identifiers, not claims: "MGO 514+ 500g" is a name.
    # And any figure this pipeline already wrote into its own reasoning was
    # derived from a computed value, so it is supported by construction.
    derived: list[str] = [m.sku for m in facts.metrics]
    derived += [m.channel_divergence or "" for m in facts.metrics]
    derived += [r.reasoning for r in facts.recommendations]
    derived += [t.description for t in facts.tensions]
    derived += [i.description + " " + i.assumption for i in facts.data_quality]
    for text in derived:
        allowed |= {m.group(0) for m in _NUMBER.finditer(text)}

    return allowed


def find_unsupported_numbers(text: str, allowed: set[str]) -> list[str]:
    """Numbers in the narrative that do not correspond to a computed figure."""
    found = [m.group(0) for m in _NUMBER.finditer(text)]
    return sorted({n for n in found if n not in allowed and n.rstrip("0").rstrip(".") not in allowed})


class NarrativeError(RuntimeError):
    """The model produced a briefing that cannot be trusted."""


# --------------------------------------------------------------------------
# Prompt (REQ-010)
# --------------------------------------------------------------------------

SYSTEM_INSTRUCTION = (
    "You are writing a monthly S&OP briefing for a non-technical executive at a "
    "consumer wellness brand. The reader has five minutes and needs to make "
    "decisions, not study a spreadsheet.\n\n"
    "Hard rules:\n"
    "1. Every number you write must appear verbatim in the FACTS below. Never "
    "calculate, never estimate, never round a figure that is given to you.\n"
    "2. If a figure is not in the FACTS, do not mention it.\n"
    "3. Say what the numbers mean for revenue, risk and timing. Do not restate "
    "the data.\n"
    "4. Lead with the decision, then the reason.\n"
    "5. Plain business English. No jargon, no bullet-point soup, no filler like "
    "'in today's fast-moving market'.\n"
)

_SECTIONS = (
    "## Headline\n"
    "Two or three sentences: what changed this month and the single most "
    "important thing to act on.\n\n"
    "## What sold well and what did not\n"
    "Name the strongest and weakest performers and say why it matters.\n\n"
    "## What is at risk\n"
    "SKUs heading for a stockout, when, and what revenue is exposed.\n\n"
    "## Recommended actions\n"
    "One short paragraph per SKU, in the order given. State the quantity, the "
    "order-by month, and the business reasoning.\n\n"
    "## Judgement calls\n"
    "The tensions listed in the facts, and what you would do about each.\n\n"
    "## Data quality\n"
    "Any conflict found in the source data, the assumption taken, and what "
    "should be confirmed.\n"
)


def facts_block(facts: BriefingFacts) -> str:
    """Render the computed figures as the model's only source of truth."""
    lines = [f"PERIOD: {facts.period_label} (most recent actual month)", ""]

    lines.append("PERFORMANCE BY SKU")
    for m in facts.metrics:
        lines.append(
            f"- {m.sku}: sold {m.baseline_demand} units this month "
            f"(trend {m.total_trend_change * 100:+.1f}% across the measured window, "
            f"{m.monthly_growth * 100:+.1f}% per month); "
            f"retail ${m.retail_price_usd:.2f}; "
            f"stock {m.stock_on_hand} units; "
            f"cover {m.projected_cover_months:.2f} months against a target of "
            f"{m.target_months_cover}; "
            f"revenue opportunity ${m.revenue_opportunity_usd:,.0f} per month"
            + (
                f"; projected stockout in {month_label(m.stockout_month)}"
                if m.stockout_month
                else ""
            )
        )

    near = [m for m in facts.metrics if m.stockout_month and m.stockout_month <= NEAR_TERM_LAST_MONTH]
    lines += ["", "NEAR-TERM RISK (stockout within three months)"]
    if near:
        for m in sorted(near, key=lambda m: m.revenue_opportunity_usd, reverse=True):
            lines.append(
                f"- {m.sku}: runs out in {month_label(m.stockout_month)}, "
                f"${m.revenue_opportunity_usd:,.0f} per month exposed"
            )
    else:
        lines.append("- None.")

    overstocked = [m for m in facts.metrics if m.overstock_units > 0]
    lines += ["", "CAPITAL TIED UP (stock beyond twice the cover target)"]
    if overstocked:
        for m in sorted(overstocked, key=lambda m: m.overstock_value_usd, reverse=True):
            lines.append(
                f"- {m.sku}: {m.overstock_units} units above a healthy level, "
                f"${m.overstock_value_usd:,.0f} at retail, with "
                f"{m.projected_cover_months:.2f} months of cover against a target "
                f"of {m.target_months_cover}"
            )
    else:
        lines.append("- None.")

    lines += ["", "REORDER RECOMMENDATIONS, ranked by revenue at stake"]
    if facts.recommendations:
        for i, r in enumerate(facts.recommendations, 1):
            lines.append(
                f"{i}. {r.sku}: order {r.reorder_units} units, place by "
                f"{r.order_by_label} (lead time {r.lead_time_months} month(s)). {r.reasoning}"
            )
        lines.append(
            f"Total monthly revenue covered by these actions: "
            f"${facts.total_revenue_at_risk:,.0f}"
        )
    else:
        lines.append("None required this month.")

    lines += ["", "JUDGEMENT CALLS"]
    lines += [f"- {t.sku}: {t.description}" for t in facts.tensions] or ["- None."]

    lines += ["", "DATA QUALITY"]
    lines += [
        f"- {i.sku}: {i.description} Assumption taken: {i.assumption}"
        for i in facts.data_quality
    ] or ["- No conflicts found."]

    lines += [
        "",
        "METHOD",
        f"- Demand is Shopify plus Amazon pooled, since stock is shared.",
        f"- The latest month is the sell-through baseline; demand is projected "
        f"forward at each SKU's own growth rate for at most {MAX_PROJECTION_MONTHS} months.",
        "- Cover is simulated month by month; incoming orders count only in the "
        "month they arrive.",
    ]
    return "\n".join(lines)


def build_prompt(facts: BriefingFacts) -> str:
    return (
        f"{SYSTEM_INSTRUCTION}\n"
        f"Write the briefing with exactly these sections:\n\n{_SECTIONS}\n"
        f"---\nFACTS\n---\n{facts_block(facts)}\n"
    )


# --------------------------------------------------------------------------
# Providers (REQ-011)
# --------------------------------------------------------------------------


class TemplateProvider:
    """Deterministic renderer. No network, no credentials, always available."""

    name = "template"

    def generate(self, facts: BriefingFacts, prompt: str) -> str:  # noqa: ARG002
        return render_template(facts)


class GeminiProvider:
    """Gemini via API key, or via Vertex AI when a GCP project is configured."""

    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        from google import genai  # imported lazily so the package stays optional

        api_key = os.getenv("GEMINI_API_KEY")
        project = os.getenv("GCP_PROJECT")
        if api_key:
            self._client = genai.Client(api_key=api_key)
        elif project:
            self._client = genai.Client(
                # Gemini 3.x publisher models are served from the "global"
                # endpoint; regional endpoints return 404 for them.
                vertexai=True, project=project, location=os.getenv("GCP_LOCATION", "global")
            )
        else:
            raise RuntimeError("no credentials: set GEMINI_API_KEY or GCP_PROJECT")
        # One model call per run, so the stronger model is worth it.
        self._model = model or os.getenv("SOP_MODEL", "gemini-3.1-pro-preview")

    def generate(self, facts: BriefingFacts, prompt: str) -> str:  # noqa: ARG002
        response = self._client.models.generate_content(model=self._model, contents=prompt)
        return (response.text or "").strip()


def select_provider() -> object:
    """Use the model when credentials exist, otherwise the template."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GCP_PROJECT")):
        return TemplateProvider()
    try:
        return GeminiProvider()
    except Exception:  # missing package, bad credentials: degrade, do not crash
        return TemplateProvider()


# --------------------------------------------------------------------------
# Deterministic rendering
# --------------------------------------------------------------------------


def render_template(facts: BriefingFacts) -> str:
    """The same validated figures, rendered without a model."""
    best = facts.top_growth[0] if facts.top_growth else None
    worst = facts.slowest_growth[0] if facts.slowest_growth else None
    at_risk = [m for m in facts.metrics if m.stockout_month and m.stockout_month <= 7]

    out = [f"# Monthly S&OP Briefing — {facts.period_label}", ""]

    out += ["## Headline", ""]
    if facts.recommendations:
        top = facts.recommendations[0]
        out.append(
            f"{len(facts.recommendations)} SKUs need a purchase order this month, covering "
            f"${facts.total_revenue_at_risk:,.0f} of monthly revenue. The most urgent is "
            f"{top.sku}: {top.reorder_units} units, to be placed by {top.order_by_label}."
        )
    else:
        out.append("No reorder is required this month. Every SKU is at or above its cover target.")
    if best:
        out.append(
            f"Demand is growing across the range, led by {best.sku} at "
            f"{best.monthly_growth * 100:.1f}% per month."
        )
    out.append("")

    out += ["## What sold well and what did not", ""]
    for m in facts.top_growth:
        out.append(
            f"- **{m.sku}** — {m.baseline_demand} units, {m.monthly_growth * 100:+.1f}% per month, "
            f"${m.revenue_opportunity_usd:,.0f} of monthly revenue."
        )
    if worst:
        out.append(
            f"- **{worst.sku}** is the slowest mover at {worst.monthly_growth * 100:+.1f}% per month."
            + (f" {worst.channel_divergence}." if worst.channel_divergence else "")
        )
    out.append("")

    out += ["## What is at risk", ""]
    if at_risk:
        for m in sorted(at_risk, key=lambda m: m.revenue_opportunity_usd, reverse=True):
            out.append(
                f"- **{m.sku}** runs out in {month_label(m.stockout_month)} at "
                f"{m.projected_cover_months:.2f} months of cover, exposing "
                f"${m.revenue_opportunity_usd:,.0f} per month."
            )
    else:
        out.append("- No SKU is projected to run out within the next three months.")
    for m in sorted(facts.metrics, key=lambda m: m.overstock_value_usd, reverse=True):
        if m.overstock_units > 0:
            out.append(
                f"- **{m.sku}** holds {m.overstock_units} units more than a healthy level "
                f"(${m.overstock_value_usd:,.0f} at retail) at {m.projected_cover_months:.2f} "
                f"months of cover against a target of {m.target_months_cover}."
            )
    out.append("")

    out += ["## Recommended actions", ""]
    for i, r in enumerate(facts.recommendations, 1):
        out.append(
            f"**{i}. {r.sku} — order {r.reorder_units} units by {r.order_by_label}.** {r.reasoning}"
        )
        out.append("")

    out += ["## Judgement calls", ""]
    for t in facts.tensions:
        out.append(f"- **{t.sku}** — {t.description}")
    if not facts.tensions:
        out.append("- None this month.")
    out.append("")

    out += ["## Data quality", ""]
    for issue in facts.data_quality:
        out.append(f"- **{issue.sku}** — {issue.description} {issue.assumption}")
    if not facts.data_quality:
        out.append("- No conflicts found in the source data.")
    out.append("")

    out += [
        "## Method",
        "",
        "Demand is Shopify and Amazon pooled, because stock is shared. The latest month is the "
        "sell-through baseline, and demand is projected forward at each SKU's own growth rate for "
        f"at most {MAX_PROJECTION_MONTHS} months. Cover is simulated month by month, so an incoming "
        "order counts only in the month it arrives.",
    ]
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# Entry point for this layer
# --------------------------------------------------------------------------


METHOD_NOTE = (
    "Demand is Shopify and Amazon pooled, because stock is shared. The most recent month is "
    "the sell-through baseline, and demand is projected forward at each SKU's own average "
    f"growth rate for at most {MAX_PROJECTION_MONTHS} months; beyond that it is held flat rather "
    "than compounded. Cover is simulated month by month, so an incoming order counts only in "
    "the month it arrives. Figures for the four months to date are observed; anything beyond "
    "them is modelled."
)


def ensure_structure(text: str, facts: BriefingFacts) -> str:
    """Guarantee the title and method note regardless of what the model returns.

    Both are factual and belong to us, so they are added deterministically
    rather than left to the model to remember.
    """
    title = f"# Monthly S&OP Briefing — {facts.period_label}"
    body = text.strip()
    if not body.startswith("# "):
        body = f"{title}\n\n{body}"
    if "## Method" not in body:
        body = f"{body}\n\n## Method\n\n{METHOD_NOTE}"
    return body + "\n"


def generate_briefing(
    facts: BriefingFacts, provider: object | None = None, retries: int = 1
) -> tuple[str, str, list[str]]:
    """Produce the briefing.

    Returns the text, the provider that produced it, and any warnings raised on
    the way. If the model invents a figure the run retries once with a
    correction, then falls back to the deterministic template rather than
    shipping a briefing that cannot be trusted.
    """
    provider = provider or select_provider()
    allowed = allowed_numbers(facts)
    warnings: list[str] = []

    if isinstance(provider, TemplateProvider):
        return render_template(facts), provider.name, warnings

    prompt = build_prompt(facts)
    for attempt in range(retries + 1):
        try:
            text = provider.generate(facts, prompt)
        except Exception as exc:
            warnings.append(f"model call failed ({exc}); falling back to the template")
            return render_template(facts), TemplateProvider.name, warnings

        unsupported = find_unsupported_numbers(text, allowed)
        if not unsupported:
            return ensure_structure(text, facts), getattr(provider, "name", "model"), warnings

        warnings.append(
            f"attempt {attempt + 1}: narrative contained figures absent from the "
            f"computed facts: {', '.join(unsupported[:8])}"
        )
        prompt = (
            f"{build_prompt(facts)}\n\nYour previous answer contained numbers that are "
            f"not in the FACTS: {', '.join(unsupported[:8])}. Rewrite it using only "
            f"figures that appear verbatim above."
        )

    warnings.append("model kept inventing figures; using the deterministic template")
    return render_template(facts), TemplateProvider.name, warnings
