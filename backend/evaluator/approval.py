"""What blocks a formula version from being approved.

Approval is the gate that turns a draft into something a run may use, so the
checks here are deliberately unforgiving. They are all deterministic: nothing
about approval depends on the model that drafted the formula.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.evaluator.schema import Covenant, FormulaVersion


@dataclass(frozen=True)
class Blocker:
    """One unresolved thing standing between a draft and approval."""

    code: str
    target: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "target": self.target, "detail": self.detail}


BLOCKER_TEXT = {
    "unmapped": "a clause item outside the vocabulary",
    "unsupported": "a construct the formula language cannot express",
    "unresolved_reference": "a referenced definition could not be found",
    "unreviewed_component": "a component has no reviewer decision",
    "unreviewed_covenant": "a covenant has no reviewer decision",
    "duplicate_item": "two components resolve to the same item and would double count",
    "all_components_rejected": "every component was rejected, leaving nothing to compute",
}


def approval_blockers(version: FormulaVersion) -> list[Blocker]:
    """Everything that must be resolved before ``version`` can be approved."""
    blockers: list[Blocker] = []

    for term, node in sorted(version.definitions.items()):
        if not node.resolved:
            blockers.append(
                Blocker("unresolved_reference", term, BLOCKER_TEXT["unresolved_reference"])
            )

    if version.ebitda.base.item in ("unmapped", "unsupported"):
        blockers.append(
            Blocker(
                version.ebitda.base.item,
                "base:" + version.ebitda.base.item,
                version.ebitda.base.reason or BLOCKER_TEXT[version.ebitda.base.item],
            )
        )

    seen_items: dict[str, str] = {}
    live = 0
    for component in version.ebitda.components:
        if component.review is None:
            blockers.append(
                Blocker("unreviewed_component", component.key, BLOCKER_TEXT["unreviewed_component"])
            )
        elif component.excluded:
            continue
        live += 1
        if component.item in ("unmapped", "unsupported"):
            # A reviewer may only clear these by excluding them with a note,
            # which the branch above already skipped.
            blockers.append(
                Blocker(
                    component.item,
                    component.key,
                    component.reason or BLOCKER_TEXT[component.item],
                )
            )
            continue
        if component.item in seen_items:
            blockers.append(
                Blocker(
                    "duplicate_item",
                    component.key,
                    BLOCKER_TEXT["duplicate_item"] + " (also " + seen_items[component.item] + ")",
                )
            )
        else:
            seen_items[component.item] = component.key

    if live == 0 and not blockers:
        blockers.append(
            Blocker("all_components_rejected", version.ebitda.formula_id,
                    BLOCKER_TEXT["all_components_rejected"])
        )

    for covenant in version.covenants:
        blockers.extend(_covenant_blockers(covenant))

    return blockers


def _covenant_blockers(covenant: Covenant) -> list[Blocker]:
    found: list[Blocker] = []
    if covenant.review is None:
        found.append(
            Blocker("unreviewed_covenant", covenant.id, BLOCKER_TEXT["unreviewed_covenant"])
        )
    for item in covenant.items_side.items:
        if item in ("unmapped", "unsupported"):
            found.append(
                Blocker(item, covenant.id, covenant.reason or BLOCKER_TEXT[item])
            )
    return found


def can_approve(version: FormulaVersion) -> bool:
    return not approval_blockers(version)
