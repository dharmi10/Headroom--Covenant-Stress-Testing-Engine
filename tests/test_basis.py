"""One reporting basis per window.

A filer that restates rarely republishes every period the restatement
affected. Taking the most recently filed figure for each period independently
then mixes two presentations inside one trailing twelve month window, and a
quarter derived across that seam is a subtraction of two numbers that were
never measured the same way.

The case these tests are built from is real. Teleflex restated fiscal 2024 in
its 2026 10-K and never reissued the nine months to September 2024, so the
fourth quarter of 2024 came out as restated-year minus original-nine-months:
a quarter with **negative depreciation and amortisation**, which then summed
into a TTM total that looked entirely ordinary.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from backend.edgar.facts import (
    basis_conflict,
    derive_quarters,
    facts_on_basis,
    parse_company_facts,
    quarter_series,
    restated_periods,
)
from pathlib import Path

from pydantic import ValidationError

from backend.edgar.mapping import MappingRecord
from backend.pipeline import load_mappings
from backend.edgar.ttm import (
    build_period_inputs,
    build_ttm,
    choose_basis,
    implausible_quarter,
    resolve_duration_item,
)

D = Decimal


def row(start, end, val, *, filed, accn, form="10-Q"):
    return {
        "start": start,
        "end": end,
        "val": val,
        "form": form,
        "filed": filed,
        "accn": accn,
        "fy": 2025,
        "fp": "Q3",
    }


def facts_of(rows, concept="DepreciationAndAmortization"):
    payload = {"facts": {"us-gaap": {concept: {"units": {"USD": rows}}}}}
    return parse_company_facts(payload)[concept]


#: The Teleflex depreciation series, with the figures the filings actually
#: carry. The fiscal year was restated from 274,601 to 161,534; the nine
#: months to 2024-09-29 was never reissued.
TELEFLEX_DA = [
    # Q3 2024, reported once and never restated.
    row("2024-07-01", "2024-09-29", 68636000, filed="2025-11-06", accn="0000096943-25-000138"),
    # The 2024 year-to-date series: nine months, then the year twice.
    row("2024-01-01", "2024-09-29", 202809000, filed="2025-11-06", accn="0000096943-25-000138"),
    row(
        "2024-01-01", "2024-12-31", 274601000,
        filed="2025-02-28", accn="0000096943-25-000031", form="10-K",
    ),
    row(
        "2024-01-01", "2024-12-31", 161534000,
        filed="2026-02-27", accn="0000096943-26-000019", form="10-K",
    ),
    # Q1 2025, restated.
    row("2025-01-01", "2025-03-30", 67331000, filed="2025-05-01", accn="0000096943-25-000077"),
    row("2025-01-01", "2025-03-30", 38620000, filed="2026-05-07", accn="0000096943-26-000050"),
    # Q2 2025, restated.
    row("2025-03-31", "2025-06-29", 65712000, filed="2025-07-31", accn="0000096943-25-000115"),
    row("2025-03-31", "2025-06-29", 36888000, filed="2026-08-06", accn="0000096943-26-000095"),
]

TEST_DATE = dt.date(2025, 6, 29)

#: What the mixed-basis window produced, and must never produce again.
MIXED_BASIS_TOTAL = D("102869000")
#: The same window built entirely from the figures as first published.
ORIGINAL_BASIS_TOTAL = D("273471000")


def verified(concept: str, period_type: str = "duration") -> MappingRecord:
    return MappingRecord(
        formula_item="depreciation_amortization",  # type: ignore[arg-type]
        concept=concept,
        status="verified",
        period_type=period_type,  # type: ignore[arg-type]
        rationale="test",
    )


# -- the regression ----------------------------------------------------------


def test_the_teleflex_window_never_produces_the_mixed_basis_total():
    """The regression. Either a consistent-basis answer or a refusal.

    This is the whole point of the change: the number 102,869,000 was wrong,
    and it was wrong in a way nothing downstream could detect, because a TTM
    total has no sign that one of its quarters was impossible.
    """
    facts = facts_of(TELEFLEX_DA)
    resolved = resolve_duration_item(
        "depreciation_amortization",
        verified("DepreciationAndAmortization"),
        facts,
        TEST_DATE,
        basis="as_originally_reported",
    )
    assert resolved.value != MIXED_BASIS_TOTAL
    if resolved.usable:
        assert resolved.value == ORIGINAL_BASIS_TOTAL
    else:
        assert resolved.reason in ("inconsistent_basis", "missing_quarter", "implausible_value")


def test_the_restated_basis_cannot_build_the_teleflex_window():
    """The restating 10-K did not reissue the nine months, so the fourth
    quarter of 2024 has nothing to be derived from on that basis. Refusing is
    the correct answer, and it is what makes the run fall back."""
    facts = facts_of(TELEFLEX_DA)
    assert build_ttm(facts, TEST_DATE, basis="as_restated") is None


def test_the_original_basis_builds_a_window_with_no_negative_quarter():
    facts = facts_of(TELEFLEX_DA)
    window = build_ttm(facts, TEST_DATE, basis="as_originally_reported")
    assert window is not None
    assert window.total == ORIGINAL_BASIS_TOTAL
    assert all(fact.value > 0 for fact in window.quarters)
    assert implausible_quarter("depreciation_amortization", window) is None


def test_the_derived_fourth_quarter_is_the_original_year_minus_the_original_nine_months():
    facts = facts_of(TELEFLEX_DA)
    window = build_ttm(facts, TEST_DATE, basis="as_originally_reported")
    assert window is not None
    derived = [fact for fact in window.quarters if fact.origin == "derived"]
    assert len(derived) == 1
    assert derived[0].value == D("274601000") - D("202809000")
    assert derived[0].basis == "as_originally_reported"


def test_without_a_basis_the_old_mixed_window_is_still_what_the_facts_allow():
    """Guards the guard: the mixed total is reachable only when nobody asks
    for a basis, which is why every caller in the pipeline passes one."""
    facts = facts_of(TELEFLEX_DA)
    window = build_ttm(facts, TEST_DATE)
    assert window is not None
    assert window.total == MIXED_BASIS_TOTAL
    assert any(fact.value < 0 for fact in window.quarters)


# -- cohorts -----------------------------------------------------------------


def test_a_restated_period_is_found_with_both_of_its_filings():
    facts = facts_of(TELEFLEX_DA)
    pairs = restated_periods(facts)
    changed = {(first.value, later.value) for first, later in pairs}
    assert (D("274601000"), D("161534000")) in changed
    assert (D("67331000"), D("38620000")) in changed


def test_a_series_nobody_restated_belongs_to_both_bases():
    """The nine months to September 2024 has one value in one filing. It is
    the original figure and the current one at the same time, so neither basis
    may discard it on its own account."""
    only = [r for r in TELEFLEX_DA if r["start"] == "2024-07-01"]
    facts = facts_of(only)
    for basis in ("as_restated", "as_originally_reported"):
        kept = facts_on_basis(facts, basis)
        assert [fact.value for fact in kept] == [D("68636000")]


def test_the_restated_cohort_drops_the_figures_the_restatement_replaced():
    facts = facts_of(TELEFLEX_DA)
    kept = facts_on_basis(facts, "as_restated")
    values = {fact.value for fact in kept}
    assert D("161534000") in values
    assert D("274601000") not in values
    # The nine months was never reissued, so it is not available on this basis
    # and the derivation that needs it cannot happen.
    assert D("202809000") not in values


def test_the_original_cohort_drops_the_restatements():
    facts = facts_of(TELEFLEX_DA)
    kept = facts_on_basis(facts, "as_originally_reported")
    values = {fact.value for fact in kept}
    assert D("274601000") in values
    assert D("202809000") in values
    assert D("161534000") not in values
    assert D("38620000") not in values


def test_a_derivation_never_spans_the_restatement_boundary():
    facts = facts_of(TELEFLEX_DA)
    for basis in ("as_restated", "as_originally_reported"):
        for derived in derive_quarters(facts, basis=basis):
            assert derived.value >= 0, (basis, derived.transformation)


def test_the_basis_conflict_names_the_periods_and_the_filings():
    """``inconsistent_basis`` has to be actionable: the analyst needs to know
    which period moved and which filing moved it."""
    facts = facts_of(TELEFLEX_DA)
    conflict = basis_conflict(facts)
    assert conflict is not None
    assert "274601000" in conflict
    assert "161534000" in conflict
    assert "0000096943-26-000019" in conflict
    assert "2024-12-31" in conflict


def test_nothing_restated_means_no_basis_conflict_to_report():
    """So a window that failed for an ordinary reason is never blamed on the
    basis."""
    facts = facts_of([r for r in TELEFLEX_DA if r["start"] == "2024-07-01"])
    assert basis_conflict(facts) is None


# -- the plausibility guard --------------------------------------------------


@pytest.mark.parametrize("item", ["depreciation_amortization", "interest_expense"])
def test_a_negative_derived_quarter_is_refused_for_items_that_cannot_be_negative(item):
    facts = facts_of(TELEFLEX_DA)
    window = build_ttm(facts, TEST_DATE)  # deliberately unfiltered: the mixed window
    assert window is not None
    broken = implausible_quarter(item, window)
    assert broken is not None
    assert broken.value < 0

    record = MappingRecord(
        formula_item=item,  # type: ignore[arg-type]
        concept="DepreciationAndAmortization",
        status="verified",
        period_type="duration",
        rationale="test",
    )
    resolved = resolve_duration_item(item, record, facts, TEST_DATE)
    assert resolved.reason == "implausible_value"
    assert resolved.value is None
    assert "cannot be" in (resolved.note or "")


def test_a_negative_derived_quarter_is_allowed_where_the_item_can_be_negative():
    """A tax benefit and a net loss are real negatives. The guard must not
    reach them, or it would refuse ordinary quarters."""
    facts = facts_of(TELEFLEX_DA)
    window = build_ttm(facts, TEST_DATE)
    assert window is not None
    assert implausible_quarter("income_tax_expense", window) is None
    assert implausible_quarter("net_income", window) is None


def test_a_reported_negative_quarter_is_the_filers_statement_and_is_kept():
    """Only derived quarters are checked. A figure the filer published stands,
    whatever Headroom thinks of it."""
    rows = [
        row("2025-09-29", "2025-12-31", -5, filed="2026-02-27", accn="a", form="10-K"),
        row("2025-06-30", "2025-09-28", 10, filed="2025-11-06", accn="b"),
        row("2025-03-31", "2025-06-29", 10, filed="2025-07-31", accn="c"),
        row("2024-12-31", "2025-03-30", 10, filed="2025-05-01", accn="d"),
    ]
    facts = facts_of(rows)
    window = build_ttm(facts, dt.date(2025, 12, 31), basis="as_originally_reported")
    assert window is not None
    assert implausible_quarter("depreciation_amortization", window) is None
    assert window.total == D("25")


# -- choosing the basis for a whole run --------------------------------------


def item_input(usable: bool):
    from backend.evaluator.inputs import ItemInput

    if usable:
        return ItemInput(item="net_income", value="1", origin="reported")
    return ItemInput(item="net_income", reason="missing_quarter")


def test_the_restated_basis_wins_when_it_loses_nothing():
    basis, lost = choose_basis(
        {
            "as_restated": {"a": item_input(True), "b": item_input(True)},
            "as_originally_reported": {"a": item_input(True), "b": item_input(True)},
        }
    )
    assert basis == "as_restated"
    assert lost == set()


def test_the_original_basis_wins_when_the_restated_one_cannot_build_everything():
    basis, lost = choose_basis(
        {
            "as_restated": {"a": item_input(True), "b": item_input(False)},
            "as_originally_reported": {"a": item_input(True), "b": item_input(True)},
        }
    )
    assert basis == "as_originally_reported"
    assert lost == set()


def test_an_item_only_the_other_basis_could_build_is_reported_not_mixed_in():
    """Neither basis covers everything. The run still commits to one, and the
    item that would have needed the other is refused rather than borrowed."""
    basis, lost = choose_basis(
        {
            "as_restated": {"a": item_input(True), "b": item_input(True), "c": item_input(False)},
            "as_originally_reported": {
                "a": item_input(True),
                "b": item_input(False),
                "c": item_input(True),
            },
        }
    )
    assert basis == "as_restated"
    assert lost == {"c"}


def test_a_lost_item_is_reported_as_inconsistent_basis_naming_the_filings():
    """End to end through ``build_period_inputs``: the item that cannot be
    built on the run's basis says so, with the restatement that caused it."""
    records = {
        "depreciation_amortization": verified("DepreciationAndAmortization"),
        "net_income": MappingRecord(
            formula_item="net_income",
            concept="NetIncomeLoss",
            status="verified",
            period_type="duration",
            rationale="test",
        ),
    }
    # Net income resolves on both bases; depreciation only on the original one.
    net_income_rows = [
        row("2024-07-01", "2024-09-29", 1, filed="2025-11-06", accn="x"),
        row("2024-09-30", "2024-12-31", 1, filed="2025-11-06", accn="x"),
        row("2025-01-01", "2025-03-30", 1, filed="2025-11-06", accn="x"),
        row("2025-03-31", "2025-06-29", 1, filed="2025-11-06", accn="x"),
    ]
    inputs = build_period_inputs(
        deal_id="t",
        test_date=TEST_DATE,
        records=records,
        facts_by_concept={
            "DepreciationAndAmortization": facts_of(TELEFLEX_DA),
            "NetIncomeLoss": facts_of(net_income_rows, concept="NetIncomeLoss"),
        },
        items=["net_income", "depreciation_amortization"],
    )
    assert inputs.basis == "as_originally_reported"
    assert inputs.items["depreciation_amortization"].value == ORIGINAL_BASIS_TOTAL
    assert inputs.basis_note


def test_the_basis_is_recorded_on_the_inputs_and_on_every_fact():
    records = {"depreciation_amortization": verified("DepreciationAndAmortization")}
    inputs = build_period_inputs(
        deal_id="t",
        test_date=TEST_DATE,
        records=records,
        facts_by_concept={"DepreciationAndAmortization": facts_of(TELEFLEX_DA)},
        items=["depreciation_amortization"],
    )
    assert inputs.basis == "as_originally_reported"
    resolved = inputs.items["depreciation_amortization"]
    assert resolved.usable
    assert {ref.basis for ref in resolved.facts} == {"as_originally_reported"}


# -- analyst values carry a basis too ---------------------------------------
#
# The one-basis rule polices the facts the pipeline selects. An analyst value
# is a figure a human hand-summed from a period's filings, and it is just as
# basis-bound: twelve months of impairment is a different number either side of
# a restatement. These tests cover the guard that refuses one sourced on the
# basis the run did not choose.


def analyst(
    value: str,
    *,
    as_of: dt.date = TEST_DATE,
    basis: str | None = None,
    item: str = "impairment_charges",
) -> MappingRecord:
    return MappingRecord(
        formula_item=item,  # type: ignore[arg-type]
        status="verified",
        period_type="duration",
        rationale="hand-summed from the filings covering the window",
        analyst_value=value,
        analyst_value_as_of=as_of,
        analyst_value_basis=basis,  # type: ignore[arg-type]
    )


def test_an_analyst_value_sourced_on_the_other_basis_is_refused():
    resolved = resolve_duration_item(
        "impairment_charges",
        analyst("253841000", basis="as_restated"),
        [],
        TEST_DATE,
        basis="as_originally_reported",
    )
    assert not resolved.usable
    assert resolved.reason == "inconsistent_basis"
    assert "as restated" in (resolved.note or "")
    assert "as originally reported" in (resolved.note or "")


def test_an_analyst_value_sourced_on_the_run_basis_is_used():
    resolved = resolve_duration_item(
        "impairment_charges",
        analyst("253841000", basis="as_originally_reported"),
        [],
        TEST_DATE,
        basis="as_originally_reported",
    )
    assert resolved.usable
    assert resolved.value == D("253841000")
    assert resolved.origin == "analyst"
    assert [ref.basis for ref in resolved.facts] == ["as_originally_reported"]


def test_an_analyst_value_with_no_basis_recorded_is_still_usable():
    """Refusing an untagged value outright would be a migration, not a guard.
    The provenance says the basis is unstated so it can be re-sourced."""
    resolved = resolve_duration_item(
        "impairment_charges",
        analyst("253841000", basis=None),
        [],
        TEST_DATE,
        basis="as_restated",
    )
    assert resolved.usable
    assert [ref.basis for ref in resolved.facts] == [None]


def test_a_basis_without_an_analyst_value_is_refused_by_the_schema():
    with pytest.raises(ValidationError):
        MappingRecord(
            formula_item="impairment_charges",  # type: ignore[arg-type]
            concept="GoodwillImpairmentLoss",
            status="verified",
            period_type="duration",
            rationale="test",
            analyst_value_basis="as_restated",
        )


def test_the_period_check_still_runs_before_the_basis_check():
    """A value for the wrong quarter is refused as missing_analyst_input even
    when its basis matches, because the period is the stronger objection."""
    resolved = resolve_duration_item(
        "impairment_charges",
        analyst("253841000", as_of=dt.date(2025, 12, 31), basis="as_originally_reported"),
        [],
        TEST_DATE,
        basis="as_originally_reported",
    )
    assert resolved.reason == "missing_analyst_input"


def test_the_golden_impairment_value_is_tagged_with_the_basis_it_was_sourced_on():
    """The golden deal's one analyst-valued add-back. Every fact behind it
    belongs to both cohorts - none of those series was ever restated - so it is
    tagged as originally reported, which is the basis the run settles on."""
    records = load_mappings(Path("data/golden/teleflex-2025q2/mappings.json"))
    record = records["impairment_charges"]
    assert record.analyst_value == "253841000"
    assert record.analyst_value_basis == "as_originally_reported"
    assert record.analyst_value_as_of == TEST_DATE
