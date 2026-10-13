"""XBRL fact handling: forms, units, restatements, derived quarters."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from backend.edgar.facts import (
    derive_quarters,
    instant_at,
    latest_by_period,
    parse_company_facts,
    quarter_series,
)


def companyfacts(rows, concept="NetIncomeLoss", unit="USD"):
    return {
        "cik": 1,
        "entityName": "Test Co",
        "facts": {"us-gaap": {concept: {"units": {unit: rows}}}},
    }


def duration(start, end, val, **extra):
    row = {"start": start, "end": end, "val": val, "form": "10-Q", "fy": 2026, "fp": "Q1"}
    row.update(extra)
    return row


def instant(end, val, **extra):
    row = {"end": end, "val": val, "form": "10-Q", "fy": 2026, "fp": "Q1"}
    row.update(extra)
    return row


def test_only_periodic_reports_and_amendments_are_accepted():
    payload = companyfacts(
        [
            duration("2026-01-01", "2026-03-31", 10, form="10-Q"),
            duration("2026-01-01", "2026-03-31", 99, form="8-K"),
            duration("2025-01-01", "2025-03-31", 20, form="10-K/A"),
            duration("2024-01-01", "2024-03-31", 30, form="S-1"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    assert {fact.form for fact in facts} == {"10-Q", "10-K/A"}


def test_only_the_requested_unit_is_parsed():
    payload = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [duration("2026-01-01", "2026-03-31", 10)],
                        "EUR": [duration("2026-01-01", "2026-03-31", 9)],
                    }
                }
            }
        }
    }
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    assert [fact.unit for fact in facts] == ["USD"]
    assert facts[0].value == Decimal("10")


def test_a_restatement_wins_over_the_original():
    payload = companyfacts(
        [
            duration("2026-01-01", "2026-03-31", 100, filed="2026-05-01", accn="a-1"),
            duration("2026-01-01", "2026-03-31", 90, filed="2026-08-01", accn="a-2"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    best = latest_by_period(facts)
    chosen = best[("duration", dt.date(2026, 1, 1), dt.date(2026, 3, 31))]
    assert chosen.value == Decimal("90")
    assert chosen.accession == "a-2"  # the audit trail keeps which filing won


def test_an_amendment_filed_the_same_day_supersedes_the_original():
    payload = companyfacts(
        [
            duration("2026-01-01", "2026-03-31", 100, filed="2026-05-01", form="10-Q", accn="x"),
            duration("2026-01-01", "2026-03-31", 95, filed="2026-05-01", form="10-Q/A", accn="x"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    chosen = latest_by_period(facts)[("duration", dt.date(2026, 1, 1), dt.date(2026, 3, 31))]
    assert chosen.value == Decimal("95")


def test_q4_is_derived_from_the_full_year_minus_nine_months():
    payload = companyfacts(
        [
            duration("2025-01-01", "2025-09-30", 300, form="10-Q"),
            duration("2025-01-01", "2025-12-31", 420, form="10-K", fp="FY"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    derived = derive_quarters(facts)
    assert len(derived) == 1
    q4 = derived[0]
    assert q4.value == Decimal("120")
    assert q4.start == dt.date(2025, 10, 1)
    assert q4.end == dt.date(2025, 12, 31)
    assert q4.origin == "derived"
    assert "minus" in (q4.transformation or "")


def test_a_year_and_a_nine_month_period_with_different_start_dates_are_incompatible():
    """Two cumulative periods that do not start on the same day are not two
    views of the same running total, so no quarter can be derived from them."""
    payload = companyfacts(
        [
            duration("2025-02-01", "2025-09-30", 300, form="10-Q"),
            duration("2025-01-01", "2025-12-31", 420, form="10-K", fp="FY"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    assert derive_quarters(facts) == []


def test_the_filing_fiscal_year_is_not_used_as_a_compatibility_key():
    """Companyfacts labels a fact with the fiscal year of the filing it came
    from, not of the period it covers, so two halves of one year-to-date
    series routinely carry different fy values. Keying on fy would lose the
    quarter at the split."""
    payload = companyfacts(
        [
            duration("2025-01-01", "2025-06-30", 200, fy=2026, fp="Q2"),
            duration("2025-01-01", "2025-09-30", 300, fy=2025, fp="Q3"),
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    derived = derive_quarters(facts)
    assert [fact.value for fact in derived] == [Decimal("100")]
    assert derived[0].start == dt.date(2025, 7, 1)


def test_a_reported_quarter_beats_a_derived_one():
    payload = companyfacts(
        [
            duration("2025-01-01", "2025-09-30", 300),
            duration("2025-01-01", "2025-12-31", 420, fp="FY", form="10-K"),
            duration("2025-10-01", "2025-12-31", 125),  # the filer stated Q4
        ]
    )
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    series = quarter_series(facts)
    assert series[dt.date(2025, 12, 31)].value == Decimal("125")
    assert series[dt.date(2025, 12, 31)].origin == "reported"


def test_an_instant_fact_must_be_dated_exactly_at_the_test_date():
    payload = companyfacts(
        [instant("2026-03-31", 500), instant("2026-04-02", 510)],
        concept="LongTermDebtNoncurrent",
    )
    facts = parse_company_facts(payload)["LongTermDebtNoncurrent"]
    assert instant_at(facts, dt.date(2026, 3, 31)).value == Decimal("500")
    # Nothing is interpolated two days either side.
    assert instant_at(facts, dt.date(2026, 3, 30)) is None


def test_a_six_month_period_is_not_treated_as_a_quarter():
    payload = companyfacts([duration("2026-01-01", "2026-06-30", 180)])
    facts = parse_company_facts(payload)["NetIncomeLoss"]
    assert quarter_series(facts) == {}
