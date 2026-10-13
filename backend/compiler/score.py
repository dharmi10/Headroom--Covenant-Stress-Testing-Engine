"""Measure the compiler against a hand-written formula.

Span verification proves a citation exists; it says nothing about whether the
clause was read correctly. That is what this module measures: for each clause
of the golden formula, did the draft get the item, the sign, the category and
the cap rule right? The number is reported with its dataset size and its
failures listed, never asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.evaluator.schema import CapPool, Component, Covenant, FormulaVersion


@dataclass
class FieldComparison:
    """One clause, field by field."""

    clause: str
    matched: dict[str, bool] = field(default_factory=dict)
    golden: dict[str, Any] = field(default_factory=dict)
    drafted: dict[str, Any] = field(default_factory=dict)

    @property
    def correct(self) -> bool:
        return all(self.matched.values())

    def wrong_fields(self) -> list[str]:
        return [name for name, ok in self.matched.items() if not ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "clause": self.clause,
            "correct": self.correct,
            "wrong_fields": self.wrong_fields(),
            "golden": self.golden,
            "drafted": self.drafted,
        }


@dataclass
class Scorecard:
    """The compiler's measured accuracy on one agreement."""

    deal_id: str
    components: list[FieldComparison] = field(default_factory=list)
    missing_clauses: list[str] = field(default_factory=list)
    extra_clauses: list[str] = field(default_factory=list)
    covenants: list[FieldComparison] = field(default_factory=list)

    @property
    def component_total(self) -> int:
        return len(self.components) + len(self.missing_clauses)

    @property
    def component_correct(self) -> int:
        return sum(1 for row in self.components if row.correct)

    @property
    def field_total(self) -> int:
        return sum(len(row.matched) for row in self.components)

    @property
    def field_correct(self) -> int:
        return sum(sum(1 for ok in row.matched.values() if ok) for row in self.components)

    def accuracy(self) -> float | None:
        if self.component_total == 0:
            return None
        return self.component_correct / self.component_total

    def field_accuracy(self) -> float | None:
        if self.field_total == 0:
            return None
        return self.field_correct / self.field_total

    def as_dict(self) -> dict[str, Any]:
        return {
            "deal_id": self.deal_id,
            "components_total": self.component_total,
            "components_correct": self.component_correct,
            "component_accuracy": self.accuracy(),
            "fields_total": self.field_total,
            "fields_correct": self.field_correct,
            "field_accuracy": self.field_accuracy(),
            "missing_clauses": self.missing_clauses,
            "extra_clauses": self.extra_clauses,
            "failures": [row.as_dict() for row in self.components if not row.correct],
            "covenants": [row.as_dict() for row in self.covenants],
        }

    def report(self) -> str:
        lines = ["compiler accuracy for " + self.deal_id]
        total, correct = self.component_total, self.component_correct
        lines.append(
            "  components: " + str(correct) + "/" + str(total) + _pct(self.accuracy())
        )
        lines.append(
            "  fields:     "
            + str(self.field_correct)
            + "/"
            + str(self.field_total)
            + _pct(self.field_accuracy())
        )
        if self.missing_clauses:
            lines.append("  clauses the draft did not account for: " + ", ".join(self.missing_clauses))
        if self.extra_clauses:
            lines.append("  clauses the draft invented: " + ", ".join(self.extra_clauses))
        for row in self.components:
            if row.correct:
                continue
            lines.append("  " + row.clause + " wrong: " + ", ".join(row.wrong_fields()))
            for name in row.wrong_fields():
                lines.append(
                    "      golden "
                    + repr(row.golden.get(name))
                    + " vs drafted "
                    + repr(row.drafted.get(name))
                )
        for row in self.covenants:
            if not row.correct:
                lines.append("  covenant " + row.clause + " wrong: " + ", ".join(row.wrong_fields()))
        return "\n".join(lines)


def _pct(value: float | None) -> str:
    if value is None:
        return ""
    return " (" + format(value * 100, ".1f") + "%)"


def _cap_rule(component: Component, formula) -> dict[str, Any] | None:  # noqa: ANN001
    if not component.cap_pool:
        return None
    pool: CapPool | None = formula.cap_pools.get(component.cap_pool)
    if pool is None:
        return None
    return {
        "kind": pool.kind,
        "fixed_amount": None if pool.fixed_amount is None else str(pool.fixed_amount),
        "pct": None if pool.pct is None else str(pool.pct),
        "basis": pool.basis,
    }


def score_components(golden: FormulaVersion, drafted: FormulaVersion) -> Scorecard:
    """Compare the drafted formula with the hand-written one, clause by clause.

    Clauses are matched on their label, which is what a reviewer uses too. A
    draft that renames a clause is counted as having missed it, because a
    reviewer could not line it up against the contract either.
    """
    card = Scorecard(deal_id=golden.deal_id)
    drafted_by_clause = {
        _clause_key(component): component for component in drafted.ebitda.components
    }
    golden_by_clause = {
        _clause_key(component): component for component in golden.ebitda.components
    }

    for clause, want in golden_by_clause.items():
        got = drafted_by_clause.get(clause)
        if got is None:
            card.missing_clauses.append(clause)
            continue
        want_cap = _cap_rule(want, golden.ebitda)
        got_cap = _cap_rule(got, drafted.ebitda)
        comparison = FieldComparison(
            clause=clause,
            matched={
                "item": want.item == got.item,
                "sign": want.sign == got.sign,
                "category": want.category == got.category,
                "cap_rule": want_cap == got_cap,
            },
            golden={
                "item": want.item,
                "sign": want.sign,
                "category": want.category,
                "cap_rule": want_cap,
            },
            drafted={
                "item": got.item,
                "sign": got.sign,
                "category": got.category,
                "cap_rule": got_cap,
            },
        )
        card.components.append(comparison)

    card.extra_clauses = sorted(set(drafted_by_clause) - set(golden_by_clause))
    card.covenants = _score_covenants(golden.covenants, drafted.covenants)
    return card


def _clause_key(component: Component) -> str:
    return (component.clause or "").strip() or component.item


def _score_covenants(golden: list[Covenant], drafted: list[Covenant]) -> list[FieldComparison]:
    rows: list[FieldComparison] = []
    drafted_by_type = {covenant.type: covenant for covenant in drafted}
    for want in golden:
        got = drafted_by_type.get(want.type)
        if got is None:
            rows.append(
                FieldComparison(
                    clause=want.id,
                    matched={"present": False},
                    golden={"present": True},
                    drafted={"present": False},
                )
            )
            continue
        want_netting = want.items_side.net_of_cash
        got_netting = got.items_side.net_of_cash
        rows.append(
            FieldComparison(
                clause=want.id,
                matched={
                    "type": want.type == got.type,
                    "items": sorted(want.items_side.items) == sorted(got.items_side.items),
                    "thresholds": _thresholds(want) == _thresholds(got),
                    "net_of_cash": _netting(want_netting) == _netting(got_netting),
                },
                golden={
                    "type": want.type,
                    "items": sorted(want.items_side.items),
                    "thresholds": _thresholds(want),
                    "net_of_cash": _netting(want_netting),
                },
                drafted={
                    "type": got.type,
                    "items": sorted(got.items_side.items),
                    "thresholds": _thresholds(got),
                    "net_of_cash": _netting(got_netting),
                },
            )
        )
    return rows


def _thresholds(covenant: Covenant) -> list[tuple[str, str]]:
    return [(step.from_.isoformat(), str(step.threshold)) for step in covenant.schedule]


def _netting(netting) -> dict[str, Any] | None:  # noqa: ANN001
    if netting is None or not netting.enabled:
        return None
    cap: Decimal | None = netting.cap
    return {"enabled": True, "cap": None if cap is None else str(cap)}
