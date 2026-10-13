"""The compiler: section location, the definitions graph, span fidelity.

The model is replaced with a stub that returns whatever a test wants it to, so
these tests exercise the parts that decide whether a draft is accepted - the
schema, the span verifier and the retry - without spending anything or
depending on a model's mood.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agreement.definitions import build_graph, referenced_terms
from backend.agreement.locate import (
    LocationError,
    covenant_mentions,
    definition_index,
    find_definition,
    locate_ebitda_definition,
    locate_financial_covenants,
)
from backend.agreement.normalise import html_to_text, normalise, text_hash
from backend.compiler.draft import CompileError, compile_agreement
from backend.compiler.score import score_components
from backend.compiler.spans import (
    SpanVerificationError,
    locate,
    relocate,
    require_verified,
    verify_span,
)
from backend.evaluator.schema import Span
from backend.pipeline import load_golden

GOLDEN = Path("data/golden/teleflex-2025q2")


@pytest.fixture(scope="module")
def agreement() -> str:
    return (GOLDEN / "agreement.txt").read_text(encoding="utf-8")


# -- normalisation -----------------------------------------------------------


def test_inline_tags_do_not_split_words():
    """Filers wrap single words in font tags; inserting a space there would
    turn one word into two and break every quote that contains it."""
    html = '<p><font>Consolidated</font><font> EBITDA</font><font>" means</font></p>'
    assert html_to_text(html) == 'Consolidated EBITDA" means'


def test_block_tags_do_not_join_words():
    html = "<p>first paragraph</p><p>second paragraph</p>"
    assert html_to_text(html) == "first paragraph\nsecond paragraph"


def test_typographic_characters_are_normalised():
    html = "<p>“Consolidated EBITDA” – the Borrower’s</p>"
    assert html_to_text(html) == '"Consolidated EBITDA" - the Borrower\'s'


def test_the_source_hash_covers_the_normalised_text_not_the_markup():
    first = normalise("<p>a clause</p>")
    second = normalise('<div style="color:red"><span>a clause</span></div>')
    assert first.source_hash == second.source_hash == text_hash("a clause")


# -- locating ----------------------------------------------------------------


def test_the_definition_index_finds_the_defined_terms(agreement):
    index = definition_index(agreement)
    assert len(index) > 300
    assert "Consolidated EBITDA" in index
    assert "Consolidated Total Funded Indebtedness" in index


def test_the_ebitda_definition_is_located_with_its_offsets(agreement):
    located = locate_ebitda_definition(agreement)
    assert located.label == "Consolidated EBITDA"
    assert agreement[located.start : located.end] == located.text
    assert located.text.startswith('"Consolidated EBITDA" means')
    assert "minus (c)" in located.text  # the deductions are inside the definition


def test_the_financial_covenant_section_is_located_and_names_both_ratios(agreement):
    section = locate_financial_covenants(agreement)
    ratios = [ratio for ratio, _ in covenant_mentions(section.text)]
    assert ratios == [
        "Consolidated Total Net Leverage Ratio",
        "Consolidated Interest Coverage Ratio",
    ]


def test_a_missing_definition_raises_rather_than_guessing(agreement):
    with pytest.raises(LocationError):
        find_definition(agreement, "Consolidated Fictional Ratio")


def test_an_agreement_with_no_definitions_cannot_be_located():
    with pytest.raises(LocationError):
        locate_financial_covenants("a letter with no covenants in it")


# -- definitions graph -------------------------------------------------------


def test_the_graph_resolves_the_terms_the_definition_uses(agreement):
    graph = build_graph(agreement, "Consolidated EBITDA")
    assert graph.unresolved == []
    assert graph.nodes["Consolidated EBITDA"].depth == 0
    assert "Consolidated Net Income" in graph.nodes
    assert "Consolidated Interest Expense" in graph.nodes


def test_the_graph_stops_at_depth_two(agreement):
    graph = build_graph(agreement, "Consolidated EBITDA")
    assert max(node.depth for node in graph.nodes.values()) <= 2


def test_a_term_with_no_definition_is_recorded_unresolved():
    text = '"Covenant EBITDA" means Adjusted Operating Profit for such period.\n'
    text += '"Adjusted Operating Profit" is not defined anywhere.\n'
    graph = build_graph(text, "Covenant EBITDA")
    assert graph.nodes["Covenant EBITDA"].resolved
    # The referenced term has no "means" clause, so it is not in the index and
    # is never claimed as resolved.
    assert "Adjusted Operating Profit" not in graph.nodes

    missing = build_graph(text, "Consolidated EBITDA")
    assert missing.unresolved == ["Consolidated EBITDA"]


def test_boilerplate_terms_are_not_sent_to_the_model(agreement):
    index = definition_index(agreement)
    body = find_definition(agreement, "Consolidated EBITDA").text
    terms = referenced_terms(body, index)
    assert "Restricted Subsidiaries" not in terms
    assert "Consolidated Net Income" in terms


# -- span verification -------------------------------------------------------


def test_a_correct_span_verifies(agreement):
    span = locate(agreement, "income tax expense")
    assert verify_span(span, agreement, target="t") is None


def test_a_fabricated_quote_is_rejected(agreement):
    span = Span(start=82_735, end=82_760, quote="income tax expense shall be doubled")
    failure = verify_span(span, agreement, target="component")
    assert failure is not None
    assert "does not appear in the agreement at all" in failure.reason


def test_a_corrupted_offset_is_rejected_and_the_real_position_reported(agreement):
    good = locate(agreement, "income tax expense")
    moved = Span(start=good.start + 500, end=good.end + 500, quote=good.quote)
    failure = verify_span(moved, agreement, target="component")
    assert failure is not None
    assert "the quote does appear at offset " + str(good.start) in failure.reason
    assert relocate(moved, agreement) == good.start


def test_a_span_past_the_end_of_the_text_is_rejected(agreement):
    span = Span(start=len(agreement) - 5, end=len(agreement) + 50, quote="anything")
    failure = verify_span(span, agreement, target="component")
    assert failure is not None
    assert "past the end" in failure.reason


def test_line_breaks_do_not_count_as_a_difference():
    source = "plus (a)\nincome tax expense for such period"
    span = Span(start=9, end=43, quote="income tax expense for such period")
    assert verify_span(span, source, target="t") is None


def test_require_verified_raises_on_a_corrupted_formula(agreement):
    _, version, _ = load_golden(GOLDEN)
    require_verified(version, agreement)  # the golden formula is clean

    corrupted = version.model_copy(deep=True)
    corrupted.ebitda.components[0].span = Span(
        start=10, end=40, quote="a quote that is not in the agreement"
    )
    with pytest.raises(SpanVerificationError) as excinfo:
        require_verified(corrupted, agreement)
    assert len(excinfo.value.failures) == 1


# -- the draft loop ----------------------------------------------------------


class StubModel:
    """A stand-in for the Anthropic client that returns scripted tool inputs."""

    def __init__(self, scripts: list[object]) -> None:
        self.scripts = list(scripts)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.scripts:
            raise AssertionError("the stub ran out of scripted responses")
        payload = self.scripts.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            return SimpleNamespace(content=[], stop_reason="end_turn", usage=None)
        name = "record_covenant" if "schedule" in payload else "record_ebitda_formula"
        block = SimpleNamespace(type="tool_use", name=name, input=payload)
        return SimpleNamespace(
            content=[block],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


MINI = (
    '"Covenant EBITDA" means Consolidated Net Income for such period plus (a) '
    "income tax expense; and (b) restructuring charges, provided that the "
    "amount added back under clause (b) shall not exceed $25,000,000.\n"
    '"Consolidated Net Income" means the net income of the Borrower.\n'
    "6.10 Financial Covenants.\n"
    "The Borrower will not permit the Total Leverage Ratio as at the last day "
    "of any fiscal quarter to exceed 4.00 to 1.00.\n"
    '"Total Leverage Ratio" means the ratio of Funded Debt to Covenant EBITDA.\n'
)


def _span_for(quote: str) -> dict:
    index = MINI.index(quote)
    return {"start": index, "end": index + len(quote), "quote": quote}


def _good_ebitda() -> dict:
    return {
        "base": {
            "item": "net_income",
            "clause": "(a)",
            "span": _span_for("Consolidated Net Income for such period"),
            "reason": "",
        },
        "components": [
            {
                "clause": "(a)",
                "item": "income_tax_expense",
                "sign": "+",
                "category": "standard",
                "cap_pool": "",
                "span": _span_for("income tax expense"),
                "reason": "",
            },
            {
                "clause": "(b)",
                "item": "restructuring_charges",
                "sign": "+",
                "category": "one_time",
                "cap_pool": "clause_b",
                "span": _span_for("restructuring charges"),
                "reason": "",
            },
        ],
        "cap_pools": [
            {
                "name": "clause_b",
                "kind": "fixed",
                "fixed_amount": "25000000",
                "pct": "",
                "basis": "",
                "label": "clause (b) cap",
                "span": _span_for("shall not exceed $25,000,000"),
            }
        ],
        "notes": "",
    }


def _good_covenant() -> dict:
    return {
        "id": "max_total_leverage",
        "name": "Total Leverage Ratio",
        "type": "max_ratio",
        "items": ["long_term_debt"],
        "items_span": _span_for("Funded Debt"),
        "net_of_cash": {"enabled": False, "cap": "", "span": _span_for("Funded Debt")},
        "schedule": [{"from": "2020-01-01", "threshold": "4.00"}],
        "span": _span_for("to exceed 4.00 to 1.00"),
        "reason": "",
    }


def test_a_clean_draft_compiles_to_a_formula_version():
    client = StubModel([_good_ebitda(), _good_covenant()])
    result = compile_agreement(
        MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA"
    )
    assert result.version.status == "draft"
    assert [c.item for c in result.version.ebitda.components] == [
        "income_tax_expense",
        "restructuring_charges",
    ]
    assert result.version.ebitda.cap_pools["clause_b"].kind == "fixed"
    assert result.version.covenants[0].threshold_at(
        __import__("datetime").date(2026, 3, 31)
    ) is not None
    assert result.logs[0].attempts == 1
    assert result.logs[0].prompt_version == "compile-v1"


def test_the_request_tells_the_model_the_absolute_offset():
    client = StubModel([_good_ebitda(), _good_covenant()])
    compile_agreement(MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA")
    request = client.calls[0]["messages"][0]["content"]
    offset = MINI.index('"Covenant EBITDA" means')
    assert "offset " + str(offset) in request
    assert client.calls[0]["tools"][0]["strict"] is True
    # Sampling parameters are rejected by current models; the draft is made
    # reproducible by validation and review, not by temperature.
    assert "temperature" not in client.calls[0]


def test_an_invalid_schema_is_rejected_and_retried():
    broken = _good_ebitda()
    broken["components"][0]["item"] = "ebitda_adjustment_i_invented"
    client = StubModel([broken, _good_ebitda(), _good_covenant()])
    result = compile_agreement(
        MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA"
    )
    assert result.logs[0].attempts == 2
    assert any("item" in error for error in result.logs[0].errors[0])


def test_an_unknown_field_is_rejected():
    broken = _good_ebitda()
    broken["components"][0]["confidence"] = "high"
    client = StubModel([broken, _good_ebitda(), _good_covenant()])
    result = compile_agreement(
        MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA"
    )
    assert result.logs[0].attempts == 2


def test_a_fabricated_span_is_rejected_and_the_retry_says_so():
    broken = _good_ebitda()
    broken["components"][0]["span"] = {
        "start": 10,
        "end": 40,
        "quote": "interest expense on the Mezzanine Notes",
    }
    client = StubModel([broken, _good_ebitda(), _good_covenant()])
    result = compile_agreement(
        MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA"
    )
    assert result.logs[0].attempts == 2
    assert any("does not appear" in error for error in result.logs[0].errors[0])
    retry = client.calls[1]["messages"][-1]["content"]
    assert "rejected" in retry


def test_two_fabricated_attempts_fail_the_compile():
    broken = _good_ebitda()
    broken["components"][0]["span"] = {"start": 1, "end": 20, "quote": "invented text here"}
    client = StubModel([broken, dict(broken)])
    with pytest.raises(CompileError, match="rejected"):
        compile_agreement(MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA")


def test_a_model_that_does_not_call_the_tool_fails_closed():
    client = StubModel([None, None])
    with pytest.raises(CompileError):
        compile_agreement(MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA")


def test_an_unsupported_construct_is_carried_through_as_unsupported():
    draft = _good_ebitda()
    draft["components"].append(
        {
            "clause": "(c)",
            "item": "unsupported",
            "sign": "+",
            "category": "pro_forma",
            "cap_pool": "",
            "span": _span_for("shall not exceed $25,000,000"),
            "reason": "the savings must be realised within 24 months, which the format cannot express",
        }
    )
    client = StubModel([draft, _good_covenant()])
    result = compile_agreement(
        MINI, deal_id="mini", client=client, ebitda_term="Covenant EBITDA"
    )
    unsupported = [c for c in result.version.ebitda.components if c.item == "unsupported"]
    assert len(unsupported) == 1
    assert "24 months" in (unsupported[0].reason or "")

    from backend.evaluator.approval import approval_blockers

    codes = {blocker.code for blocker in approval_blockers(result.version)}
    assert "unsupported" in codes


# -- the accuracy metric -----------------------------------------------------


def test_a_perfect_draft_scores_one(agreement):
    _, version, _ = load_golden(GOLDEN)
    card = score_components(version, version)
    assert card.accuracy() == 1.0
    assert card.missing_clauses == []
    assert all(row.correct for row in card.covenants)


def test_the_scorecard_names_the_fields_a_draft_got_wrong():
    _, golden, _ = load_golden(GOLDEN)
    drafted = golden.model_copy(deep=True)
    drafted.ebitda.components[0].category = "one_time"  # was standard
    drafted.ebitda.components[1].sign = "-"  # was +
    dropped = drafted.ebitda.components.pop()
    card = score_components(golden, drafted)

    assert card.component_total == len(golden.ebitda.components)
    assert card.component_correct == card.component_total - 3
    wrong = {row.clause: row.wrong_fields() for row in card.components if not row.correct}
    assert wrong[golden.ebitda.components[0].clause] == ["category"]
    assert wrong[golden.ebitda.components[1].clause] == ["sign"]
    assert card.missing_clauses == [dropped.clause]
    assert "wrong:" in card.report()


def test_a_wrong_cap_rule_is_counted_as_wrong():
    _, golden, _ = load_golden(GOLDEN)
    drafted = golden.model_copy(deep=True)
    drafted.ebitda.cap_pools["clause_x"].basis = "after_pool"
    card = score_components(golden, drafted)
    wrong = [row for row in card.components if not row.correct]
    assert len(wrong) == 1
    assert wrong[0].wrong_fields() == ["cap_rule"]


def test_the_scorecard_serialises_for_the_readme(tmp_path):
    _, golden, _ = load_golden(GOLDEN)
    card = score_components(golden, golden)
    payload = json.loads(json.dumps(card.as_dict()))
    assert payload["component_accuracy"] == 1.0
    assert payload["components_total"] == len(golden.ebitda.components)
