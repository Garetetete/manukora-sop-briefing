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
from .narrative import build_facts, generate_briefing, select_provider

DEFAULT_INPUT = Path("data/mock_sales.csv")
DEFAULT_OUTPUT = Path("output/sop-briefing-2026-03.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sop-briefing",
        description="Generate the monthly S&OP briefing from a sales and inventory extract.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV extract to read")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the briefing")
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="skip the model and render deterministically (no credentials needed)",
    )
    args = parser.parse_args(argv)

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

    text, source, warnings = generate_briefing(facts, provider=provider)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")

    print(f"Read {len(rows)} SKUs from {args.input}")
    print(f"Narrative written by: {source}")
    print(f"Reorder recommendations: {len(facts.recommendations)}")
    for rec in facts.recommendations:
        print(f"  - {rec.sku}: {rec.reorder_units} units by {rec.order_by_label}")
    print(f"Judgement calls raised: {len(facts.tensions)}")
    print(f"Data-quality conflicts: {len(facts.data_quality)}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Briefing written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
