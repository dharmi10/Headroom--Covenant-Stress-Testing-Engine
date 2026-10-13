"""What the evaluator is given: one value or one reason per formula item.

The evaluator never fetches anything. It is handed a resolved set of inputs,
each of which either has an exact value with its provenance, or a reason code
explaining why it has none. That boundary is what makes a run reproducible: the
same inputs and the same formula version always produce the same numbers.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.evaluator.reasons import Reason, ReasonCode
from backend.evaluator.schema import STRICT, Amount, IsoDate
from backend.evaluator.vocabulary import ItemName

Origin = Literal["reported", "derived", "analyst"]


class FactRef(BaseModel):
    """Provenance for one financial fact, enough to find it again by hand."""

    model_config = STRICT

    concept: str
    value: Amount
    unit: str = "USD"
    period_type: Literal["duration", "instant"]
    start: IsoDate | None = None
    end: IsoDate | None = None
    instant: IsoDate | None = None
    form: str | None = None
    accession: str | None = None
    filed: IsoDate | None = None
    fy: int | None = None
    fp: str | None = None
    origin: Origin = "reported"
    transformation: str | None = None

    @property
    def label(self) -> str:
        if self.period_type == "instant":
            return self.concept + " @ " + str(self.instant)
        return self.concept + " " + str(self.start) + ".." + str(self.end)


class ItemInput(BaseModel):
    """A resolved formula item: a value, or a reason there is none."""

    model_config = STRICT

    item: ItemName
    value: Amount | None = None
    reason: ReasonCode | None = None
    origin: Origin | None = None
    concept: str | None = None
    mapping_version: int | None = None
    facts: list[FactRef] = Field(default_factory=list)
    note: str | None = None

    @property
    def usable(self) -> bool:
        return self.value is not None and self.reason is None

    def to_reason(self) -> Reason:
        code = self.reason or "ambiguous_mapping"
        return Reason(code, item=self.item, detail=self.note)


class PeriodInputs(BaseModel):
    """Every input needed for one test quarter of one deal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    deal_id: str
    test_date: IsoDate
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    quarters: list[str] = Field(default_factory=list)
    items: dict[str, ItemInput] = Field(default_factory=dict)

    def get(self, item: str) -> ItemInput:
        """The input for ``item``, or a missing-fact placeholder.

        An item the pipeline never produced is treated as missing with the
        structurally correct reason, never as zero.
        """
        found = self.items.get(item)
        if found is not None:
            return found
        from backend.evaluator.vocabulary import INSTANT_ITEMS

        code: ReasonCode = "missing_instant" if item in INSTANT_ITEMS else "missing_quarter"
        return ItemInput(item=item, reason=code, note="no input was produced for this item")

    def value_of(self, item: str) -> Decimal | None:
        resolved = self.get(item)
        return resolved.value if resolved.usable else None


def analyst_input(
    item: str,
    value: str | int | Decimal,
    *,
    note: str,
    as_of: dt.date | None = None,
) -> ItemInput:
    """An item the analyst supplied by hand, with the source note required."""
    if not note.strip():
        raise ValueError("an analyst input requires a source note")
    return ItemInput(
        item=item,  # type: ignore[arg-type]
        value=value if isinstance(value, (str, int, Decimal)) else str(value),
        origin="analyst",
        note=note,
        facts=[
            FactRef(
                concept="analyst_input",
                value=value if isinstance(value, (str, int, Decimal)) else str(value),
                period_type="duration",
                end=as_of,
                origin="analyst",
                transformation=note,
            )
        ],
    )
