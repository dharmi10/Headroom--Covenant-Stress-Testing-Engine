"""Fail-closed behaviour: a missing input never becomes a zero."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.evaluator.approval import approval_blockers, can_approve
from backend.evaluator.run import evaluate_run
from backend.evaluator.scenarios import evaluate_ebitda
from tests.conftest import (
    component,
    ebitda_formula,
    formula_version,
    inputs,
    leverage_covenant,
)


def _formula():
    return ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("income_tax_expense", "standard"),
            component("restructuring_charges", "one_time"),
        ]
    )


def _complete():
    return {
        "net_income": "40",
        "interest_expense": "25",
        "income_tax_expense": "10",
        "restructuring_charges": "15",
        "long_term_debt": "450",
    }


@pytest.mark.parametrize(
    "item, code",
    [
        ("net_income", "missing_quarter"),
        ("interest_expense", "incompatible_facts"),
        ("income_tax_expense", "ambiguous_mapping"),
        ("restructuring_charges", "missing_quarter"),
    ],
)
def test_a_missing_duration_item_makes_the_scenario_not_computable(item, code):
    values = _complete()
    values.pop(item)
    data = inputs(values, reasons={item: code})
    result = evaluate_ebitda(_formula(), data, "S0")
    assert result.value is None
    assert [reason.code for reason in result.reasons] == [code]
    assert [reason.item for reason in result.reasons] == [item]


def test_a_missing_debt_fact_makes_the_covenant_not_computable():
    values = _complete()
    values.pop("long_term_debt")
    data = inputs(values, reasons={"long_term_debt": "missing_instant"})
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, data)
    result = run.covenants["S0"]["max_total_leverage"]
    assert result.verdict == "NOT_COMPUTABLE"
    assert [r.code for r in result.reasons] == ["missing_instant"]
    # The EBITDA itself was computable; only the covenant failed.
    assert run.ebitda["S0"].value == Decimal("90")


def test_an_item_with_no_input_at_all_is_still_a_reason_not_a_zero():
    data = inputs({"net_income": "40", "interest_expense": "25", "long_term_debt": "450"})
    result = evaluate_ebitda(_formula(), data, "S0")
    assert result.value is None
    assert {reason.item for reason in result.reasons} == {
        "income_tax_expense",
        "restructuring_charges",
    }
    assert {reason.code for reason in result.reasons} == {"missing_quarter"}


def test_projected_savings_with_no_analyst_value_only_affects_s0():
    """Projected savings are in no filing. Without an analyst value, the
    contractual scenario fails closed and the other three still compute."""
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("run_rate_cost_savings", "pro_forma"),
        ]
    )
    data = inputs(
        {"net_income": "40", "interest_expense": "25", "long_term_debt": "450"},
        reasons={"run_rate_cost_savings": "missing_analyst_input"},
    )
    version = formula_version(formula, [leverage_covenant("5.00")])
    run = evaluate_run(version, data)
    assert run.ebitda["S0"].value is None
    assert [r.code for r in run.ebitda["S0"].reasons] == ["missing_analyst_input"]
    assert run.ebitda["S1"].value == Decimal("65")
    assert run.covenants["S0"]["max_total_leverage"].verdict == "NOT_COMPUTABLE"
    assert run.covenants["S1"]["max_total_leverage"].verdict != "NOT_COMPUTABLE"
    assert run.adjustment_dependence is None


def test_an_unapproved_formula_cannot_produce_a_result():
    version = formula_version(_formula(), [leverage_covenant("5.00")], status="draft")
    run = evaluate_run(version, inputs(_complete()))
    assert [r.code for r in run.reasons] == ["unapproved_formula"]
    for scenario in ("S0", "S1", "S2", "S3"):
        assert run.ebitda[scenario].value is None
        assert run.covenants[scenario]["max_total_leverage"].verdict == "NOT_COMPUTABLE"


def test_an_unmapped_component_blocks_approval_and_blocks_a_run():
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component(
                "unmapped",
                "one_time",
                reason="clause (xi) covers realised foreign exchange losses",
                review=None,
            ),
        ]
    )
    version = formula_version(formula, [leverage_covenant("5.00")], status="draft")
    codes = {blocker.code for blocker in approval_blockers(version)}
    assert "unmapped" in codes
    assert not can_approve(version)

    result = evaluate_ebitda(formula, inputs(_complete()), "S0")
    assert result.value is None
    assert [r.code for r in result.reasons] == ["unsupported_adjustment"]


def test_excluding_an_unsupported_component_unblocks_approval_and_is_disclosed():
    """A reviewer may exclude a construct the language cannot express. That
    has to unblock approval, and every scenario that would have included it
    has to say so, otherwise the exclusion is invisible."""
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component(
                "unsupported",
                "one_time",
                reason="the add-back is conditional on a ratio test",
                review="excluded_unsupported",
                note="excluded: the language cannot express a ratio-conditional add-back",
            ),
        ]
    )
    version = formula_version(formula, [leverage_covenant("5.00")])
    assert can_approve(version)

    run = evaluate_run(version, inputs(_complete()))
    assert run.ebitda["S0"].value == Decimal("65")
    assert [r.code for r in run.ebitda["S0"].disclosures] == ["unsupported_adjustment"]
    # S3 keeps only standard components, so the exclusion is not relevant there.
    assert run.ebitda["S3"].disclosures == []
    assert run.covenants["S0"]["max_total_leverage"].verdict != "NOT_COMPUTABLE"


def test_a_component_with_no_review_blocks_approval():
    formula = ebitda_formula([component("interest_expense", "standard", review=None)])
    version = formula_version(formula, [leverage_covenant("5.00")], status="draft")
    assert [b.code for b in approval_blockers(version)] == ["unreviewed_component"]


def test_two_components_resolving_to_the_same_item_block_approval():
    """Two clauses mapped to one vocabulary item would add the same fact
    twice, so approval has to stop it."""
    formula = ebitda_formula(
        [
            component("other_non_cash_charges", "non_cash", clause="(xiii)"),
            component("other_non_cash_charges", "non_cash", clause="(v)"),
        ]
    )
    version = formula_version(formula, [leverage_covenant("5.00")], status="draft")
    assert [b.code for b in approval_blockers(version)] == ["duplicate_item"]


def test_an_unresolved_reference_blocks_approval():
    from backend.evaluator.schema import DefinitionNode

    version = formula_version(_formula(), [leverage_covenant("5.00")], status="draft")
    version.definitions["Consolidated Net Income"] = DefinitionNode(
        term="Consolidated Net Income", depth=1, resolved=False
    )
    assert [b.code for b in approval_blockers(version)] == ["unresolved_reference"]


def test_rejecting_every_component_blocks_approval():
    formula = ebitda_formula(
        [component("interest_expense", "standard", review="rejected", note="not in this clause")]
    )
    version = formula_version(formula, [leverage_covenant("5.00")], status="draft")
    assert [b.code for b in approval_blockers(version)] == ["all_components_rejected"]
