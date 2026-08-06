"""REQ-010 narrative guard, REQ-011 running without credentials, REQ-012 CLI."""

import pytest

from sop.cli import main
from sop.narrative import (
    BriefingFacts,
    TemplateProvider,
    allowed_numbers,
    build_facts,
    build_prompt,
    find_unsupported_numbers,
    generate_briefing,
    render_template,
)


class FakeModel:
    """Returns whatever it was told to, so the guard can be tested offline."""

    name = "fake"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, facts, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else ""


class BrokenModel:
    name = "broken"

    def generate(self, facts, prompt):
        raise RuntimeError("provider unavailable")


@pytest.fixture
def facts(rows) -> BriefingFacts:
    return build_facts(rows)


def test_req_010_prompt_carries_the_computed_figures(facts):
    prompt = build_prompt(facts)
    assert "Manuka Honey MGO 514+ 500g" in prompt
    assert "Every number you write must appear verbatim" in prompt
    assert "order 650 units" in prompt


def test_req_010_invented_figures_are_detected(facts):
    allowed = allowed_numbers(facts)
    assert find_unsupported_numbers("Order 650 units of the 500g line.", allowed) == []
    assert "987654" in find_unsupported_numbers("Revenue was 987654 dollars.", allowed)


def test_req_010_month_indices_and_years_are_not_flagged(facts):
    allowed = allowed_numbers(facts)
    assert find_unsupported_numbers("In April 2026, month 5 of the series.", allowed) == []


def test_req_010_a_hallucinated_number_triggers_a_retry(facts):
    model = FakeModel("Sales reached 987654 units.", "Sales reached 1604 units.")
    text, source, warnings = generate_briefing(facts, provider=model)
    assert source == "fake"
    assert "1604" in text
    assert len(model.prompts) == 2
    assert "not in the FACTS" in model.prompts[1]
    assert any("987654" in w for w in warnings)


def test_req_010_persistent_hallucination_falls_back_to_the_template(facts):
    model = FakeModel("Revenue was 111222 dollars.", "Still 111222 dollars.")
    text, source, warnings = generate_briefing(facts, provider=model)
    assert source == "template"
    assert "Monthly S&OP Briefing" in text
    assert any("kept inventing" in w for w in warnings)


def test_req_010_a_failing_provider_degrades_instead_of_crashing(facts):
    text, source, warnings = generate_briefing(facts, provider=BrokenModel())
    assert source == "template"
    assert "provider unavailable" in warnings[0]
    assert text.startswith("# Monthly S&OP Briefing")


def test_req_011_template_needs_no_credentials_and_no_network(facts):
    text, source, warnings = generate_briefing(facts, provider=TemplateProvider())
    assert source == "template"
    assert warnings == []
    assert len(text) > 1000


def test_req_011_template_output_contains_only_computed_figures(facts):
    """The fallback is held to the same standard as the model."""
    assert find_unsupported_numbers(render_template(facts), allowed_numbers(facts)) == []


def test_req_011_template_states_every_recommendation(facts):
    text = render_template(facts)
    for rec in facts.recommendations:
        assert rec.sku in text
        assert f"{rec.reorder_units} units" in text


def test_req_011_template_reports_the_data_conflict(facts):
    text = render_template(facts)
    assert "Bioactive Blend Energy 250g" in text
    assert "before the stated launch" in text


def test_req_012_cli_writes_the_briefing(tmp_path, capsys):
    out = tmp_path / "briefing.md"
    code = main(["--input", "data/mock_sales.csv", "--output", str(out), "--template-only"])
    assert code == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "Read 12 SKUs" in printed
    assert "Reorder recommendations: 4" in printed


def test_req_012_cli_reports_a_bad_extract_and_exits_non_zero(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("SKU\nonly-a-name\n", encoding="utf-8")
    code = main(["--input", str(bad), "--output", str(tmp_path / "x.md")])
    assert code == 2
    assert "missing required column" in capsys.readouterr().err


def test_req_012_title_is_added_when_the_model_omits_it(facts):
    model = FakeModel("## Headline\nAll quiet this month.")
    text, _, _ = generate_briefing(facts, provider=model)
    assert text.startswith("# Monthly S&OP Briefing \u2014 March 2026")


def test_req_012_method_note_is_added_when_the_model_omits_it(facts):
    model = FakeModel("## Headline\nAll quiet this month.")
    text, _, _ = generate_briefing(facts, provider=model)
    assert "## Method" in text
    assert "counts only in the month it arrives" in text


def test_req_012_a_title_supplied_by_the_model_is_not_duplicated(facts):
    model = FakeModel("# My own title\n\n## Headline\nQuiet.\n\n## Method\nStated.")
    text, _, _ = generate_briefing(facts, provider=model)
    assert text.count("# My own title") == 1
    assert text.count("## Method") == 1


# --- REQ-011: any provider, or none -----------------------------------------

def test_req_011_provider_is_chosen_explicitly_when_requested(monkeypatch):
    from sop.narrative import TemplateProvider, select_provider

    monkeypatch.setenv("SOP_PROVIDER", "template")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "would-otherwise-win")
    assert isinstance(select_provider(), TemplateProvider)


def test_req_011_unknown_provider_names_the_valid_options(monkeypatch):
    from sop.narrative import select_provider

    monkeypatch.setenv("SOP_PROVIDER", "llama")
    with pytest.raises(ValueError, match="anthropic, gemini, openai, template"):
        select_provider()


def test_req_011_no_credentials_means_the_template(monkeypatch):
    from sop.narrative import TemplateProvider, select_provider

    for var in ("SOP_PROVIDER", "GEMINI_API_KEY", "GCP_PROJECT",
                "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert isinstance(select_provider(), TemplateProvider)


def test_req_011_a_missing_sdk_degrades_instead_of_crashing(monkeypatch):
    """A reviewer with a key but without the package still gets a briefing."""
    from sop.narrative import TemplateProvider, select_provider

    monkeypatch.delenv("SOP_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    assert isinstance(select_provider(), TemplateProvider)


def test_req_011_every_provider_satisfies_the_interface():
    from sop.narrative import PROVIDERS

    for name, cls in PROVIDERS.items():
        assert cls.name == name
        assert callable(cls.generate)
