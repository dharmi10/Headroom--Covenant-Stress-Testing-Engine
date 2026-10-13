"""Builders that keep the tests about arithmetic rather than about JSON."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Iterable

import pytest

from backend.evaluator.inputs import ItemInput, PeriodInputs
from backend.evaluator.schema import (
    BaseTerm,
    Component,
    Covenant,
    EbitdaFormula,
    FormulaVersion,
    Review,
    Span,
)

SOURCE_HASH = "sha256:test"
APPROVED_AT = dt.datetime(2026, 1, 15, 9, 0, 0)

_offset = {"next": 1000}


def span(quote: str = "clause text") -> Span:
    """A span with a unique offset, so component keys stay distinct."""
    start = _offset["next"]
    _offset["next"] = start + len(quote) + 1
    return Span(start=start, end=start + len(quote), quote=quote)


def component(
    item: str,
    category: str,
    *,
    sign: str = "+",
    cap_pool: str | None = None,
    clause: str | None = None,
    review: str | None = "accepted",
    note: str | None = None,
    reason: str | None = None,
) -> Component:
    reviewed = None
    if review is not None:
        reviewed = Review(decision=review, note=note or ("see clause" if review != "accepted" else None))
    return Component(
        item=item,
        sign=sign,
        category=category,
        cap_pool=cap_pool,
        clause=clause or item,
        reason=reason,
        span=span(item),
        review=reviewed,
    )


def ebitda_formula(
    components: Iterable[Component],
    cap_pools: dict[str, Any] | None = None,
    *,
    formula_id: str = "test-deal",
    version: int = 1,
    status: str = "approved",
) -> EbitdaFormula:
    return EbitdaFormula(
        formula_id=formula_id,
        version=version,
        status=status,
        source_hash=SOURCE_HASH,
        base=BaseTerm(item="net_income", span=span("Consolidated Net Income"), clause="base"),
        components=list(components),
        cap_pools=cap_pools or {},
    )


def leverage_covenant(
    threshold: str = "5.00",
    *,
    cid: str = "max_total_leverage",
    items: list[str] | None = None,
    net_of_cash: dict[str, Any] | None = None,
    schedule: list[dict[str, str]] | None = None,
) -> Covenant:
    return Covenant(
        id=cid,
        name="Maximum Total Leverage",
        type="max_ratio",
        numerator={
            "items": items or ["long_term_debt"],
            "net_of_cash": net_of_cash,
        },
        denominator="consolidated_ebitda",
        schedule=schedule or [{"from": "2020-01-01", "threshold": threshold}],
        span=span("shall not permit the leverage ratio"),
        review=Review(decision="accepted"),
    )


def coverage_covenant(threshold: str = "3.00", *, cid: str = "min_interest_coverage") -> Covenant:
    return Covenant(
        id=cid,
        name="Minimum Interest Coverage",
        type="min_ratio",
        numerator="consolidated_ebitda",
        denominator={"items": ["interest_expense"]},
        schedule=[{"from": "2020-01-01", "threshold": threshold}],
        span=span("shall not permit the interest coverage ratio"),
        review=Review(decision="accepted"),
    )


def formula_version(
    formula: EbitdaFormula,
    covenants: Iterable[Covenant],
    *,
    status: str = "approved",
    deal_id: str = "test-deal",
) -> FormulaVersion:
    return FormulaVersion(
        deal_id=deal_id,
        version=formula.version,
        status=status,
        source_hash=formula.source_hash,
        ebitda=formula,
        covenants=list(covenants),
        approved_by="analyst" if status == "approved" else None,
        approved_at=APPROVED_AT if status == "approved" else None,
    )


def inputs(
    values: dict[str, str | int | Decimal],
    *,
    test_date: str = "2026-03-31",
    reasons: dict[str, str] | None = None,
    deal_id: str = "test-deal",
) -> PeriodInputs:
    items: dict[str, ItemInput] = {}
    for item, value in values.items():
        items[item] = ItemInput(item=item, value=value, origin="reported", concept="test:" + item)
    for item, code in (reasons or {}).items():
        items[item] = ItemInput(item=item, reason=code)
    return PeriodInputs(
        deal_id=deal_id,
        test_date=dt.date.fromisoformat(test_date),
        items=items,
    )


@pytest.fixture
def primer_formula() -> EbitdaFormula:
    """The PRD finance primer: net income 40 + interest 25 + tax 10 + D&A 25."""
    return ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("income_tax_expense", "standard"),
            component("depreciation_amortization", "standard"),
        ]
    )


@pytest.fixture
def primer_inputs() -> PeriodInputs:
    return inputs(
        {
            "net_income": "40",
            "interest_expense": "25",
            "income_tax_expense": "10",
            "depreciation_amortization": "25",
            "long_term_debt": "450",
        }
    )
