"""The scenario engine.

Every scenario runs the whole formula from scratch: components, deductions,
exclusions and caps. It is tempting to compute the contractual result once and
subtract, but that is wrong whenever a cap is shared. Say pool A has a fixed
cap of 20 with restructuring of 15 and projected savings of 15. In S0 the pool
totals 30 and only 20 counts; in S1 the savings are gone and restructuring's
full 15 now fits. Subtracting 15 from S0 would give 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

from backend.evaluator.caps import PoolResult, evaluate_pools
from backend.evaluator.inputs import PeriodInputs
from backend.evaluator.money import ZERO, dec_str, exact
from backend.evaluator.reasons import Reason, dedupe
from backend.evaluator.schema import Component, EbitdaFormula
from backend.evaluator.vocabulary import (
    PROMOTABLE_CATEGORY,
    RECURRING_CATEGORY,
    SCENARIO_CATEGORIES,
    SCENARIO_LABELS,
)


@dataclass(frozen=True)
class ComponentLine:
    """One component as it entered (or did not enter) a scenario."""

    key: str
    item: str
    sign: str
    category: str
    cap_pool: str | None
    clause: str | None
    requested: Decimal | None
    contribution: Decimal | None
    state: str
    detail: str | None = None
    #: The category the component was judged under. Equal to ``category``
    #: except where the filings showed a "one-time" charge recurring, in which
    #: case the contract says one thing and the history says another, and the
    #: result has to show both.
    effective_category: str | None = None
    #: Why the category was promoted, quoting the years and the amounts.
    recurrence_evidence: str | None = None

    @property
    def judged_as(self) -> str:
        return self.effective_category or self.category

    def as_dict(self) -> dict[str, object]:
        return {
            "component": self.key,
            "item": self.item,
            "sign": self.sign,
            "category": self.category,
            "effective_category": self.judged_as,
            "recurrence_evidence": self.recurrence_evidence,
            "cap_pool": self.cap_pool,
            "clause": self.clause,
            "requested": None if self.requested is None else dec_str(self.requested),
            "contribution": None if self.contribution is None else dec_str(self.contribution),
            "state": self.state,
            "detail": self.detail,
        }


@dataclass
class EbitdaResult:
    """Covenant EBITDA for one scenario, with its full working."""

    scenario: str
    label: str
    value: Decimal | None
    e_base: Decimal | None
    base_value: Decimal | None
    pools: dict[str, PoolResult] = field(default_factory=dict)
    lines: list[ComponentLine] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    disclosures: list[Reason] = field(default_factory=list)

    @property
    def computable(self) -> bool:
        return self.value is not None

    def included(self) -> list[ComponentLine]:
        return [line for line in self.lines if line.state == "included"]

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "label": self.label,
            "ebitda": None if self.value is None else dec_str(self.value),
            "base": None if self.base_value is None else dec_str(self.base_value),
            "e_outside_pools": None if self.e_base is None else dec_str(self.e_base),
            "pools": [self.pools[name].as_dict() for name in sorted(self.pools)],
            "components": [line.as_dict() for line in self.lines],
            "reasons": [reason.as_dict() for reason in self.reasons],
            "disclosures": [reason.as_dict() for reason in self.disclosures],
        }


def includes_category(scenario: str, category: str) -> bool:
    try:
        allowed = SCENARIO_CATEGORIES[scenario]
    except KeyError:
        raise ValueError("unknown scenario: " + scenario) from None
    return True if allowed is None else category in allowed


def effective_category(
    component: Component,
    recurring: Mapping[str, str] | None,
) -> tuple[str, str | None]:
    """The category a component is judged under, and the evidence for it.

    A clause's category is a property of the contract and never changes. The
    one exception is a charge the agreement calls one-time that the borrower's
    own filings show recurring: the contract still permits the add-back, but a
    lender would not call it non-recurring, so it is judged as
    ``aggressive_recurring`` and the years behind that are carried alongside.
    """
    if component.category != PROMOTABLE_CATEGORY or not recurring:
        return component.category, None
    evidence = recurring.get(component.item)
    if evidence is None:
        return component.category, None
    return RECURRING_CATEGORY, evidence


def evaluate_ebitda(
    formula: EbitdaFormula,
    inputs: PeriodInputs,
    scenario: str,
    *,
    recurring: Mapping[str, str] | None = None,
) -> EbitdaResult:
    """Recalculate covenant EBITDA under ``scenario`` from scratch.

    ``recurring`` maps an item to the evidence that its "one-time" charge
    recurs, as produced by :mod:`backend.edgar.recurrence`. Components in the
    promotable category are judged as ``aggressive_recurring`` when they appear
    in it.
    """
    label = SCENARIO_LABELS.get(scenario, scenario)
    result = EbitdaResult(
        scenario=scenario, label=label, value=None, e_base=None, base_value=None
    )

    base_input = inputs.get(formula.base.item)
    if not base_input.usable:
        result.reasons.append(base_input.to_reason())
    base_value = base_input.value if base_input.usable else None
    result.base_value = base_value
    result.lines.append(
        ComponentLine(
            key="base:" + formula.base.item,
            item=formula.base.item,
            sign="+",
            category="standard",
            cap_pool=None,
            clause=formula.base.clause,
            requested=base_value,
            contribution=base_value,
            state="included" if base_value is not None else "not_computable",
            detail=None if base_value is not None else base_input.to_reason().code,
        )
    )

    outside: list[Decimal] = []
    pooled: dict[str, list[tuple[Component, Decimal]]] = {}

    for component in formula.components:
        line, amount = _resolve(component, inputs, scenario, result, recurring)
        result.lines.append(line)
        if amount is None:
            continue
        if component.cap_pool:
            pooled.setdefault(component.cap_pool, []).append((component, amount))
        else:
            outside.append(amount)

    if result.reasons:
        result.reasons = dedupe(result.reasons)
        return result

    assert base_value is not None
    with exact():
        e_base = base_value + sum(outside, ZERO)
    result.e_base = e_base

    active_pools = {name: pool for name, pool in formula.cap_pools.items() if name in pooled}
    allowed_total, pool_results = evaluate_pools(active_pools, pooled, e_base)
    result.pools = pool_results

    with exact():
        result.value = e_base + allowed_total

    _apply_pool_attribution(result)
    return result


def _resolve(
    component: Component,
    inputs: PeriodInputs,
    scenario: str,
    result: EbitdaResult,
    recurring: Mapping[str, str] | None = None,
) -> tuple[ComponentLine, Decimal | None]:
    """Resolve one component for one scenario.

    Returns the trace line and the signed contribution, or ``None`` when the
    component does not enter this scenario or has no usable value.
    """
    judged, evidence = effective_category(component, recurring)
    shared = dict(
        key=component.key,
        item=component.item,
        sign=component.sign,
        category=component.category,
        cap_pool=component.cap_pool,
        clause=component.clause,
        effective_category=judged,
        recurrence_evidence=evidence,
    )

    if component.excluded:
        assert component.review is not None
        decision = component.review.decision
        state = "excluded_by_reviewer"
        if decision == "excluded_unsupported":
            # The reviewer excluded a construct the language cannot express.
            # That unblocks approval, so it must not make every later run
            # NOT_COMPUTABLE; it is disclosed on each scenario that would
            # otherwise have included the component.
            state = "excluded_unsupported"
            if includes_category(scenario, judged):
                result.disclosures.append(
                    Reason(
                        "unsupported_adjustment",
                        item=component.item,
                        detail=component.review.note,
                    )
                )
        return (
            ComponentLine(
                **shared,
                requested=None,
                contribution=None,
                state=state,
                detail=component.review.note,
            ),
            None,
        )

    if component.item in ("unmapped", "unsupported"):
        # Only reachable on a draft: approval is blocked while either exists.
        result.reasons.append(
            Reason("unsupported_adjustment", item=component.item, detail=component.reason)
        )
        return (
            ComponentLine(
                **shared,
                requested=None,
                contribution=None,
                state="not_computable",
                detail=component.reason,
            ),
            None,
        )

    if not includes_category(scenario, judged):
        detail = "category " + judged + " is out of scope for " + scenario
        if evidence:
            detail += " (" + evidence + ")"
        return (
            ComponentLine(
                **shared,
                requested=None,
                contribution=None,
                state="excluded_by_scenario",
                detail=detail,
            ),
            None,
        )

    resolved = inputs.get(component.item)
    if not resolved.usable:
        reason = resolved.to_reason()
        result.reasons.append(reason)
        return (
            ComponentLine(
                **shared,
                requested=None,
                contribution=None,
                state="not_computable",
                detail=reason.code,
            ),
            None,
        )

    assert resolved.value is not None
    amount = resolved.value if component.sign == "+" else -resolved.value
    return (
        ComponentLine(
            **shared,
            requested=amount,
            contribution=amount,
            state="included",
        ),
        amount,
    )


def _apply_pool_attribution(result: EbitdaResult) -> None:
    """Rewrite pooled lines so their contribution is the capped share."""
    allowed_by_key = {
        part.key: part.allowed
        for pool in result.pools.values()
        for part in pool.attribution
    }
    for index, line in enumerate(result.lines):
        if line.cap_pool and line.state == "included" and line.key in allowed_by_key:
            allowed = allowed_by_key[line.key]
            detail = line.detail
            if line.requested is not None and allowed != line.requested:
                detail = "capped by pool " + line.cap_pool
            result.lines[index] = ComponentLine(
                key=line.key,
                item=line.item,
                sign=line.sign,
                category=line.category,
                cap_pool=line.cap_pool,
                clause=line.clause,
                requested=line.requested,
                contribution=allowed,
                state=line.state,
                detail=detail,
                effective_category=line.effective_category,
                recurrence_evidence=line.recurrence_evidence,
            )
