"""The mapping gate: statuses, rationales, and what a candidate is worth."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.edgar.mapping import (
    MappingRecord,
    candidates_for,
    is_analyst_only,
    load_candidates,
    mapping_coverage,
    propose,
)


def test_every_vocabulary_item_has_a_candidate_entry():
    from backend.evaluator.vocabulary import (
        BASE_ITEMS,
        DEBT_ITEMS,
        DEDUCTIONS,
        DISCRETIONARY_ADJUSTMENTS,
        STANDARD_ADJUSTMENTS,
    )

    table = load_candidates()
    expected = set(
        BASE_ITEMS + STANDARD_ADJUSTMENTS + DISCRETIONARY_ADJUSTMENTS + DEDUCTIONS + DEBT_ITEMS
    )
    assert expected <= set(table)
    for item in expected:
        assert table[item].period_type in ("duration", "instant")


def test_a_proposal_is_always_review_required():
    record = propose("interest_expense")
    assert record.status == "review_required"
    assert record.concept == candidates_for("interest_expense")[0]
    assert not record.usable


def test_a_proposal_prefers_a_candidate_the_company_actually_reports():
    record = propose("interest_expense", available={"InterestExpenseDebt"})
    assert record.concept == "InterestExpenseDebt"


def test_a_proposal_with_no_available_candidate_has_no_concept():
    record = propose("interest_expense", available={"SomethingElse"})
    assert record.concept is None
    assert record.status == "review_required"


def test_projected_savings_have_no_candidate_at_all():
    assert candidates_for("run_rate_cost_savings") == []
    assert is_analyst_only("run_rate_cost_savings")
    assert propose("run_rate_cost_savings").concept is None


def test_verifying_a_mapping_requires_a_rationale():
    with pytest.raises(ValidationError, match="written rationale"):
        MappingRecord(
            formula_item="interest_expense",
            concept="InterestExpense",
            status="verified",
            period_type="duration",
        )


def test_verifying_a_mapping_requires_a_concept_or_an_analyst_value():
    with pytest.raises(ValidationError, match="concept or an analyst value"):
        MappingRecord(
            formula_item="run_rate_cost_savings",
            status="verified",
            period_type="duration",
            rationale="management presentation",
        )


def test_marking_a_mapping_unavailable_requires_a_rationale():
    with pytest.raises(ValidationError, match="requires a rationale"):
        MappingRecord(
            formula_item="run_rate_cost_savings",
            status="unavailable",
            period_type="duration",
        )


def test_verify_bumps_the_mapping_version():
    record = propose("interest_expense")
    approved = record.verify(rationale="matches the clause", by="analyst")
    assert approved.status == "verified"
    assert approved.mapping_version == record.mapping_version + 1
    assert approved.decided_by == "analyst"
    assert approved.usable
    # The original record is untouched: a decision creates a new version.
    assert record.status == "review_required"


def test_coverage_is_reported_as_verified_over_required():
    records = {
        "net_income": propose("net_income").verify(rationale="ok"),
        "interest_expense": propose("interest_expense"),
    }
    assert mapping_coverage(records, ["net_income", "interest_expense", "long_term_debt"]) == (
        1,
        3,
    )


# -- two items on one concept ------------------------------------------------
#
# ``mapping.yaml`` offers ``OtherNoncashIncomeExpense`` to both
# ``other_non_cash_charges`` and ``other_non_cash_gains``, which is honest -
# it really is the only candidate for either - but verifying both would put
# the same reported figure into covenant EBITDA twice, and with opposite signs
# it would go in in both directions at once. The formula gate cannot see this:
# its duplicate check compares items, and these are two different items.


def _verified(item: str, concept: str | None) -> MappingRecord:
    return MappingRecord(
        formula_item=item,  # type: ignore[arg-type]
        concept=concept,
        status="verified",
        period_type="duration",
        rationale="checked against the filings",
    )


def test_two_items_on_the_same_concept_block_approval():
    from backend.edgar.mapping import duplicate_concept_blockers

    records = {
        "other_non_cash_charges": _verified("other_non_cash_charges", "OtherNoncashIncomeExpense"),
        "other_non_cash_gains": _verified("other_non_cash_gains", "OtherNoncashIncomeExpense"),
    }
    blockers = duplicate_concept_blockers(records, list(records))
    assert [blocker.code for blocker in blockers] == ["duplicate_concept"]
    assert blockers[0].target == "OtherNoncashIncomeExpense"
    assert "other_non_cash_charges" in blockers[0].detail
    assert "other_non_cash_gains" in blockers[0].detail


def test_distinct_concepts_do_not_block():
    from backend.edgar.mapping import duplicate_concept_blockers

    records = {
        "other_non_cash_charges": _verified("other_non_cash_charges", "OtherNoncashIncomeExpense"),
        "other_non_cash_gains": _verified("other_non_cash_gains", "GainLossOnSaleOfBusiness"),
    }
    assert duplicate_concept_blockers(records, list(records)) == []


def test_two_analyst_valued_items_do_not_collide():
    """An analyst value has no concept, so two of them are not a double count:
    they are two separately sourced figures."""
    from backend.edgar.mapping import duplicate_concept_blockers

    records = {
        "transaction_costs": MappingRecord(
            formula_item="transaction_costs",
            concept=None,
            status="verified",
            period_type="duration",
            rationale="hand summed",
            analyst_value="0",
            analyst_value_as_of="2025-06-29",
        ),
        "other_non_cash_gains": MappingRecord(
            formula_item="other_non_cash_gains",
            concept=None,
            status="verified",
            period_type="duration",
            rationale="hand summed",
            analyst_value="0",
            analyst_value_as_of="2025-06-29",
        ),
    }
    assert duplicate_concept_blockers(records, list(records)) == []


def test_an_item_the_formula_does_not_require_is_not_counted():
    """Only the items a run would actually resolve can double count. A record
    left over from an earlier formula version is not a conflict."""
    from backend.edgar.mapping import duplicate_concept_blockers

    records = {
        "other_non_cash_charges": _verified("other_non_cash_charges", "OtherNoncashIncomeExpense"),
        "other_non_cash_gains": _verified("other_non_cash_gains", "OtherNoncashIncomeExpense"),
    }
    assert duplicate_concept_blockers(records, ["other_non_cash_charges"]) == []


def test_the_duplicate_concept_blocker_reaches_the_approval_gate():
    """The check is only worth having if it actually stops an approval."""
    from backend.edgar.mapping import required_items
    from backend.pipeline import all_blockers
    from tests.conftest import (
        component,
        coverage_covenant,
        ebitda_formula,
        formula_version,
        leverage_covenant,
    )

    version = formula_version(
        ebitda_formula(
            [
                component("other_non_cash_charges", "accepted_non_cash"),
                component("other_non_cash_gains", "accepted_non_cash", sign="-"),
            ]
        ),
        [leverage_covenant(), coverage_covenant()],
    )
    assert all_blockers(version) == []  # the formula gate alone sees nothing

    records = {
        item: _verified(item, "OtherNoncashIncomeExpense")
        if item in ("other_non_cash_charges", "other_non_cash_gains")
        else _verified(item, "Concept" + item)
        for item in required_items(version)
    }
    codes = [blocker.code for blocker in all_blockers(version, records)]
    assert codes == ["duplicate_concept"]
