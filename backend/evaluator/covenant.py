"""Covenant metrics and verdicts.

For a maximum leverage covenant with threshold ``T``, debt ``D`` and covenant
EBITDA ``E``::

    leverage = D / E
    cushion  = 1 - D / (T * E)
    additional debt capacity = T * E - D

For a minimum interest coverage covenant with interest ``I``::

    coverage = E / I
    cushion  = 1 - (T * I) / E

Verdicts are decided by exact cross-multiplication, never by comparing rounded
ratios: ``D <= T * E`` instead of ``D / E <= T``. The displayed ratio and
cushion are rounded for reading only, so a borrower exactly at 3.00x is never
reported as a breach because of a division remainder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from backend.evaluator.inputs import PeriodInputs
from backend.evaluator.money import (
    ONE,
    ZERO,
    dec_str,
    div,
    exact,
    quantize_percent,
    quantize_ratio,
)
from backend.evaluator.reasons import Reason, dedupe
from backend.evaluator.schema import Covenant, ItemsSide
from backend.evaluator.scenarios import EbitdaResult

Verdict = Literal["PASS", "TIGHT", "BREACH", "NOT_COMPUTABLE"]

#: Default tight band: a cushion below 15% is reported as TIGHT.
DEFAULT_TIGHT_BAND = Decimal("0.15")


@dataclass
class SideResult:
    """One side of a covenant ratio, built from items."""

    value: Decimal | None
    gross: Decimal | None = None
    netted: Decimal | None = None
    cash_available: Decimal | None = None
    cash_cap: Decimal | None = None
    parts: list[tuple[str, Decimal]] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "value": None if self.value is None else dec_str(self.value),
            "gross": None if self.gross is None else dec_str(self.gross),
            "cash_netted": None if self.netted is None else dec_str(self.netted),
            "cash_available": None
            if self.cash_available is None
            else dec_str(self.cash_available),
            "cash_cap": None if self.cash_cap is None else dec_str(self.cash_cap),
            "parts": [{"item": item, "value": dec_str(value)} for item, value in self.parts],
            "reasons": [reason.as_dict() for reason in self.reasons],
        }


@dataclass
class CovenantResult:
    """A covenant tested in one scenario."""

    covenant_id: str
    covenant_name: str | None
    covenant_type: str
    scenario: str
    threshold: Decimal | None
    ebitda: Decimal | None
    side: SideResult
    ratio: Decimal | None
    cushion: Decimal | None
    headroom_amount: Decimal | None
    debt_capacity: Decimal | None
    verdict: Verdict
    reasons: list[Reason] = field(default_factory=list)
    disclosures: list[Reason] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "covenant_id": self.covenant_id,
            "covenant_name": self.covenant_name,
            "covenant_type": self.covenant_type,
            "scenario": self.scenario,
            "threshold": None if self.threshold is None else dec_str(self.threshold),
            "ebitda": None if self.ebitda is None else dec_str(self.ebitda),
            "ratio": None if self.ratio is None else dec_str(self.ratio),
            "ratio_display": _show(quantize_ratio(self.ratio)),
            "cushion": None if self.cushion is None else dec_str(self.cushion),
            "cushion_display": _show(quantize_percent(self.cushion)),
            "headroom_ebitda": None
            if self.headroom_amount is None
            else dec_str(self.headroom_amount),
            "debt_capacity": None if self.debt_capacity is None else dec_str(self.debt_capacity),
            "verdict": self.verdict,
            "side": self.side.as_dict(),
            "reasons": [reason.as_dict() for reason in self.reasons],
            "disclosures": [reason.as_dict() for reason in self.disclosures],
        }


def _show(value: Decimal | None) -> str | None:
    return None if value is None else dec_str(value)


def build_side(side: ItemsSide, inputs: PeriodInputs) -> SideResult:
    """Sum a side's items, then net cash against it up to the cap."""
    parts: list[tuple[str, Decimal]] = []
    reasons: list[Reason] = []
    for item in side.items:
        resolved = inputs.get(item)
        if not resolved.usable:
            reasons.append(resolved.to_reason())
            continue
        assert resolved.value is not None
        parts.append((item, resolved.value))
    if reasons:
        return SideResult(value=None, parts=parts, reasons=dedupe(reasons))

    with exact():
        gross = sum((value for _, value in parts), ZERO)

    netting = side.net_of_cash
    if netting is None or not netting.enabled:
        return SideResult(value=gross, gross=gross, parts=parts)

    cash_input = inputs.get(netting.item)
    if not cash_input.usable:
        return SideResult(value=None, gross=gross, parts=parts, reasons=[cash_input.to_reason()])
    assert cash_input.value is not None
    available = cash_input.value
    with exact():
        usable = available if netting.cap is None else min(available, netting.cap)
        usable = max(usable, ZERO)
        value = gross - usable
    return SideResult(
        value=value,
        gross=gross,
        netted=usable,
        cash_available=available,
        cash_cap=netting.cap,
        parts=parts,
    )


def evaluate_covenant(
    covenant: Covenant,
    ebitda: EbitdaResult,
    inputs: PeriodInputs,
    *,
    tight_band: Decimal = DEFAULT_TIGHT_BAND,
) -> CovenantResult:
    """Test one covenant against one scenario's EBITDA."""
    threshold = covenant.threshold_at(inputs.test_date)
    side = build_side(covenant.items_side, inputs)
    reasons: list[Reason] = []
    reasons.extend(ebitda.reasons)
    reasons.extend(side.reasons)
    if threshold is None:
        reasons.append(
            Reason(
                "incompatible_facts",
                item=covenant.id,
                detail="the threshold schedule starts after the test date",
            )
        )

    blank = CovenantResult(
        covenant_id=covenant.id,
        covenant_name=covenant.name,
        covenant_type=covenant.type,
        scenario=ebitda.scenario,
        threshold=threshold,
        ebitda=ebitda.value,
        side=side,
        ratio=None,
        cushion=None,
        headroom_amount=None,
        debt_capacity=None,
        verdict="NOT_COMPUTABLE",
        reasons=dedupe(reasons),
        disclosures=list(ebitda.disclosures),
    )
    if reasons or ebitda.value is None or side.value is None or threshold is None:
        return blank

    e = ebitda.value
    if covenant.type == "max_ratio":
        return _max_ratio(blank, threshold, e, side.value, tight_band)
    return _min_ratio(blank, threshold, e, side.value, tight_band)


def _max_ratio(
    result: CovenantResult,
    threshold: Decimal,
    e: Decimal,
    debt: Decimal,
    tight_band: Decimal,
) -> CovenantResult:
    """Leverage: debt over EBITDA, capped above by the threshold."""
    if e <= 0:
        # A leverage test against zero or negative EBITDA has no finite ratio,
        # and the covenant cannot be satisfied.
        result.verdict = "BREACH"
        return result
    with exact():
        result.ratio = debt / e
        result.cushion = ONE - debt / (threshold * e)
        result.debt_capacity = threshold * e - debt
        # EBITDA could fall to debt / threshold before the test fails.
        result.headroom_amount = e - debt / threshold
        breach = debt > threshold * e
        tight = debt > (ONE - tight_band) * threshold * e
    result.verdict = "BREACH" if breach else ("TIGHT" if tight else "PASS")
    return result


def _min_ratio(
    result: CovenantResult,
    threshold: Decimal,
    e: Decimal,
    interest: Decimal,
    tight_band: Decimal,
) -> CovenantResult:
    """Coverage: EBITDA over interest, floored below by the threshold."""
    if interest < 0:
        result.reasons = [
            Reason(
                "incompatible_facts",
                item="interest_expense",
                detail="negative interest expense cannot be used in a coverage test",
            )
        ]
        return result
    if e <= 0:
        result.verdict = "BREACH"
        return result
    if interest == 0:
        # No interest to cover: the test is satisfied with no exposure.
        result.ratio = None
        result.cushion = ONE
        result.headroom_amount = e
        result.verdict = "PASS"
        return result
    with exact():
        result.ratio = e / interest
        result.cushion = ONE - threshold * interest / e
        result.headroom_amount = e - threshold * interest
        breach = threshold * interest > e
        tight = threshold * interest > (ONE - tight_band) * e
    result.verdict = "BREACH" if breach else ("TIGHT" if tight else "PASS")
    return result


def worst_verdict(verdicts: list[str]) -> str:
    """The verdict a deal is reported at: the worst of its covenants."""
    order = ["PASS", "TIGHT", "NOT_COMPUTABLE", "BREACH"]
    worst = "PASS"
    for verdict in verdicts:
        if order.index(verdict) > order.index(worst):
            worst = verdict
    return worst


def cushion_ratio(result: CovenantResult) -> Decimal | None:
    """The cushion as a plain ratio, for charts."""
    return result.cushion


def ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return div(numerator, denominator)
