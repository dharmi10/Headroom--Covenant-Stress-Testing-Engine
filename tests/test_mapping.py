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
