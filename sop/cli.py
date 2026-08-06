"""Command-line entry point (REQ-012).

One command runs the whole pipeline and writes the briefing to disk. It prints a
short summary of what was produced and surfaces every warning, so a run that
degraded is never mistaken for a clean one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import ExtractError, load_extract
from .narrative import build_facts, generate_briefing

DEFAULT_INPUT = Path("data/mock_sales.csv")

# The model-written briefing is the committed deliverable. --template-only
# writes beside it rather than over it, so running the quickstart never
# destroys the artifact the README points at.
DEFAULT_OUTPUT = Path("output/sop-briefing-2026-03.md")
TEMPLATE_OUTPUT = Path("output/sop-briefing-2026-03-template.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sop-briefing",
        description="Generate the monthly S&OP briefing from a sales and inventory extract.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV extract to read")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write the briefing; defaults beside the committed one in --template-only",
    )
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="skip the model and render deterministically (no credentials needed)",
    )
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = TEMPLATE_OUTPUT if args.template_only else DEFAULT_OUTPUT

    try:
        rows = load_extract(args.input)
    except ExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    facts = build_facts(rows)

    provider = None
    if args.template_only:
        from .narrative import TemplateProvider

        provider = TemplateProvider()

    try:
        text, source, warnings = generate_briefing(facts, provider=provider)
    except ValueError as exc:  # e.g. an unknown SOP_PROVIDER
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")

    print(f"Read {len(rows)} SKUs from {args.input}")
    print(f"Narrative written by: {source}")
    print(f"Reorder recommendations: {len(facts.recommendations)}")
    for rec in facts.recommendations:
        print(f"  - {rec.sku}: {rec.reorder_units} units by {rec.order_by_label}")
    print(f"Watch list (decide before next month): {len(facts.watch_items)}")
    for item in facts.watch_items:
        print(f"  - {item.sku}: order by {item.order_by_label}")
    print(f"Judgement calls raised: {len(facts.tensions)}")
    print(f"Data-quality conflicts: {len(facts.data_quality)}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Briefing written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
