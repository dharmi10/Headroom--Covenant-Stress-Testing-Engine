"""TTM construction and the reason codes it returns when it cannot build."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.edgar.facts import parse_company_facts
from backend.edgar.mapping import MappingRecord, propose, required_items
from backend.edgar.ttm import (
    build_period_inputs,
    build_ttm,
    quarter_ends,
    resolve_duration_item,
    resolve_instant_item,
)
from backend.edgar.facts import quarter_series
from tests.conftest import component, ebitda_formula, formula_version, leverage_covenant
from tests.test_facts import companyfacts, duration, instant

TEST_DATE = dt.date(2026, 3, 31)

FOUR_QUARTERS = [
    duration("2025-04-01", "2025-06-30", 10),
    duration("2025-07-01", "2025-09-30", 20),
    duration("2025-10-01", "2025-12-31", 30),
    duration("2026-01-01", "2026-03-31", 40),
]


def facts_of(rows, concept="NetIncomeLoss"):
    return parse_company_facts(companyfacts(rows, concept=concept))[concept]


def verified(item, concept, period_type="duration", **extra):
    return MappingRecord(
        formula_item=item,
        concept=concept,
        status="verified",
        period_type=period_type,
        rationale="checked against the filing",
        **extra,
    )


def test_ttm_sums_the_four_quarters_ending_on_the_test_date():
    window = build_ttm(facts_of(FOUR_QUARTERS), TEST_DATE)
    assert window is not None
    assert window.total == Decimal("100")
    assert window.labels[-1] == "2026-01-01..2026-03-31"


def test_the_window_must_be_contiguous():
    """A gap between two quarters means the year is not covered, so no TTM."""
    with_gap = [row for row in FOUR_QUARTERS if row["end"] != "2025-09-30"]
    with_gap.append(duration("2025-07-15", "2025-10-14", 20))
    assert build_ttm(facts_of(with_gap), TEST_DATE) is None


def test_a_missing_quarter_returns_missing_quarter():
    short = FOUR_QUARTERS[1:]
    resolved = resolve_duration_item(
        "net_income", verified("net_income", "NetIncomeLoss"), facts_of(short), TEST_DATE
    )
    assert resolved.value is None
    assert resolved.reason == "missing_quarter"


def test_incompatible_cumulative_periods_return_incompatible_facts():
    """Year-to-date periods that do not share a start date end on the test
    date but cannot be turned into quarters."""
    rows = [
        duration("2025-04-01", "2025-12-31", 300),
        duration("2025-01-01", "2026-03-31", 420, fp="FY", form="10-K"),
    ]
    resolved = resolve_duration_item(
        "net_income", verified("net_income", "NetIncomeLoss"), facts_of(rows), TEST_DATE
    )
    assert resolved.reason == "incompatible_facts"


def test_a_derived_q4_is_recorded_as_derived_with_its_transformation():
    """Q4 is never reported as a quarter, so the window needs it derived from
    the full year minus the nine-month year to date."""
    rows = [
        duration("2025-04-01", "2025-06-30", 10, accn="q2"),
        duration("2025-07-01", "2025-09-30", 20, accn="q3"),
        duration("2025-01-01", "2025-09-30", 35, accn="q3"),
        duration("2025-01-01", "2025-12-31", 65, accn="fy", fp="FY", form="10-K"),
        duration("2026-01-01", "2026-03-31", 40, accn="q1-26"),
    ]
    resolved = resolve_duration_item(
        "net_income", verified("net_income", "NetIncomeLoss"), facts_of(rows), TEST_DATE
    )
    # 10 + 20 + (65 - 35) + 40
    assert resolved.value == Decimal("100")
    assert resolved.origin == "derived"
    derived = [ref for ref in resolved.facts if ref.origin == "derived"]
    assert len(derived) == 1
    assert derived[0].start == dt.date(2025, 10, 1)
    assert "minus" in (derived[0].transformation or "")
    assert all(ref.accession is not None for ref in resolved.facts)


def test_a_missing_instant_returns_missing_instant():
    rows = [instant("2026-03-30", 500)]
    resolved = resolve_instant_item(
        "long_term_debt",
        verified("long_term_debt", "LongTermDebtNoncurrent", "instant"),
        facts_of(rows, "LongTermDebtNoncurrent"),
        TEST_DATE,
    )
    assert resolved.value is None
    assert resolved.reason == "missing_instant"
    assert "2026-03-31" in (resolved.note or "")


def test_an_unverified_mapping_returns_ambiguous_mapping():
    record = propose("net_income")
    assert record.status == "review_required"
    resolved = resolve_duration_item("net_income", record, facts_of(FOUR_QUARTERS), TEST_DATE)
    assert resolved.value is None
    assert resolved.reason == "ambiguous_mapping"


def test_an_unavailable_mapping_returns_missing_analyst_input():
    record = MappingRecord(
        formula_item="run_rate_cost_savings",
        status="unavailable",
        period_type="duration",
        rationale="no reported concept exists for projected savings",
    )
    resolved = resolve_duration_item("run_rate_cost_savings", record, [], TEST_DATE)
    assert resolved.reason == "missing_analyst_input"


def test_an_analyst_value_must_say_which_period_it_was_sourced_for():
    """Without the period, next quarter's run would silently reuse it."""
    with pytest.raises(ValidationError, match="test date it was sourced for"):
        MappingRecord(
            formula_item="run_rate_cost_savings",
            status="verified",
            period_type="duration",
            analyst_value="12500000",
            rationale="management presentation",
        )


def test_an_analyst_value_from_another_period_is_refused():
    record = MappingRecord(
        formula_item="run_rate_cost_savings",
        status="verified",
        period_type="duration",
        analyst_value="12500000",
        analyst_value_as_of=dt.date(2025, 12, 31),
        rationale="management presentation",
    )
    resolved = resolve_duration_item("run_rate_cost_savings", record, [], TEST_DATE)
    assert resolved.value is None
    assert resolved.reason == "missing_analyst_input"
    assert "cannot be reused for 2026-03-31" in (resolved.note or "")


def test_a_verified_analyst_value_is_used_and_kept_as_provenance():
    record = MappingRecord(
        formula_item="run_rate_cost_savings",
        status="verified",
        period_type="duration",
        analyst_value="12500000",
        analyst_value_as_of=TEST_DATE,
        rationale="management presentation dated 2026-02-01, slide 14",
    )
    resolved = resolve_duration_item("run_rate_cost_savings", record, [], TEST_DATE)
    assert resolved.value == Decimal("12500000")
    assert resolved.origin == "analyst"
    assert resolved.facts[0].concept == "analyst_input"
    assert "slide 14" in (resolved.facts[0].transformation or "")


def test_quarter_ends_rejects_a_window_that_is_not_a_year():
    rows = [
        duration("2025-10-01", "2025-12-31", 30),
        duration("2026-01-01", "2026-03-31", 40),
    ]
    series = quarter_series(facts_of(rows))
    assert quarter_ends(series, TEST_DATE) is None


def test_required_items_covers_the_formula_and_the_covenants():
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("restructuring_charges", "one_time"),
            component(
                "unsupported",
                "one_time",
                reason="ratio-conditional",
                review="excluded_unsupported",
                note="excluded",
            ),
        ]
    )
    covenant = leverage_covenant(
        items=["long_term_debt", "current_portion_long_term_debt"],
        net_of_cash={"enabled": True, "cap": "75000000"},
    )
    version = formula_version(formula, [covenant])
    assert required_items(version) == [
        "net_income",
        "interest_expense",
        "restructuring_charges",
        "long_term_debt",
        "current_portion_long_term_debt",
        "cash_and_equivalents",
    ]


def test_build_period_inputs_reports_an_item_with_no_record():
    inputs = build_period_inputs(
        deal_id="d",
        test_date=TEST_DATE,
        records={},
        facts_by_concept={},
        items=["net_income"],
    )
    assert inputs.items["net_income"].reason == "ambiguous_mapping"
    assert inputs.value_of("net_income") is None
