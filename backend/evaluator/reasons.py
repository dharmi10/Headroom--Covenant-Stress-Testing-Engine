"""Reason codes for inputs that cannot be used.

Headroom fails closed. A missing value is never replaced by zero, because a
zero would quietly make a covenant look safer than the evidence supports. Each
unusable input carries one of these codes, and the codes travel up to the
scenario and the covenant verdict so the analyst can see exactly which fact is
missing and which results it affects.
"""

from __future__ import annotations

from typing import Literal

ReasonCode = Literal[
    "unapproved_formula",
    "ambiguous_mapping",
    "missing_quarter",
    "missing_instant",
    "incompatible_facts",
    "missing_analyst_input",
    "unsupported_adjustment",
    "inconsistent_basis",
    "implausible_value",
]

REASON_TEXT: dict[str, str] = {
    "unapproved_formula": "No approved formula version exists for the deal",
    "ambiguous_mapping": "A required item's mapping is still review_required",
    "missing_quarter": "One of the four TTM quarters is neither reported nor derivable",
    "missing_instant": "No debt or cash fact is dated at the test date",
    "incompatible_facts": "Facts exist but cannot be combined",
    "missing_analyst_input": "An item marked unavailable needs an analyst value and has none",
    "unsupported_adjustment": "The scenario includes a component the reviewer excluded as unsupported",
    "inconsistent_basis": "The four quarters cannot be built without mixing restated and originally reported figures",
    "implausible_value": "A derived quarter produced a value the item cannot take",
}

ALL_REASONS: tuple[str, ...] = tuple(REASON_TEXT)


class Reason:
    """A reason code with the item and detail it applies to.

    Kept as a plain class rather than a Pydantic model so the evaluator can
    create thousands of them cheaply inside property tests.
    """

    __slots__ = ("code", "item", "detail")

    def __init__(self, code: str, item: str | None = None, detail: str | None = None) -> None:
        if code not in REASON_TEXT:
            raise ValueError("unknown reason code: " + code)
        self.code = code
        self.item = item
        self.detail = detail

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "item": self.item,
            "detail": self.detail or REASON_TEXT[self.code],
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Reason(" + self.code + ", item=" + repr(self.item) + ")"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Reason):
            return NotImplemented
        return (self.code, self.item, self.detail) == (other.code, other.item, other.detail)

    def __hash__(self) -> int:
        return hash((self.code, self.item, self.detail))


def dedupe(reasons: list[Reason]) -> list[Reason]:
    """Stable de-duplication, keeping first occurrence order."""
    seen: set[tuple[str, str | None, str | None]] = set()
    out: list[Reason] = []
    for reason in reasons:
        key = (reason.code, reason.item, reason.detail)
        if key not in seen:
            seen.add(key)
            out.append(reason)
    return out
