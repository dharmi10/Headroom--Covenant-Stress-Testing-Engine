"""The formula language: a closed, typed JSON format.

The language is deliberately small. Anything it cannot express is recorded as
``unsupported`` with its span and a reason rather than approximated, because an
approximated covenant is worse than an absent one. Every model forbids unknown
fields, so a field the LLM invents is a validation error, not a silent extra.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

from backend.evaluator.money import dec_str, to_decimal
from backend.evaluator.vocabulary import Category, ItemName, Sign

STRICT = ConfigDict(extra="forbid", strict=True)


def _as_decimal(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int, Decimal)):
        return to_decimal(value)
    return value


def _as_date(value: Any) -> Any:
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    return value


def _as_datetime(value: Any) -> Any:
    if isinstance(value, str):
        return dt.datetime.fromisoformat(value)
    return value


#: A money amount or rate. Accepts strings and integers, never floats.
Amount = Annotated[
    Decimal,
    BeforeValidator(_as_decimal),
    PlainSerializer(dec_str, return_type=str, when_used="always"),
]

#: An ISO date, accepted as a string and stored as a ``date``.
IsoDate = Annotated[dt.date, BeforeValidator(_as_date)]

#: An ISO timestamp, accepted as a string and stored as a ``datetime``.
IsoDateTime = Annotated[dt.datetime, BeforeValidator(_as_datetime)]


class Span(BaseModel):
    """A character range in the normalised agreement text, with its quote.

    The quote is what makes a span checkable: a drafted span is rejected unless
    the agreement text at ``[start:end]`` equals ``quote``. That proves the text
    exists. Whether it was read correctly is what human review is for.
    """

    model_config = STRICT

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> "Span":
        if self.end <= self.start:
            raise ValueError("span.end must be greater than span.start")
        return self


ReviewDecision = Literal["accepted", "edited", "rejected", "excluded_unsupported"]


class Review(BaseModel):
    """A reviewer decision on one component, frozen into the version."""

    model_config = STRICT

    decision: ReviewDecision
    note: str | None = None
    reviewer: str | None = None
    reviewed_at: IsoDateTime | None = None

    @model_validator(mode="after")
    def _note_required(self) -> "Review":
        needs_note = ("edited", "rejected", "excluded_unsupported")
        if self.decision in needs_note and not (self.note and self.note.strip()):
            raise ValueError("a " + self.decision + " review requires a note")
        return self


CapKind = Literal["fixed", "percentage", "greater_of"]
CapBasis = Literal["before_pool", "after_pool"]


class CapPool(BaseModel):
    """A cap shared by one or more components.

    ``basis`` records what a percentage is measured against: ``before_pool``
    for "calculated before such add-backs", ``after_pool`` for "after giving
    effect to such add-backs".
    """

    model_config = STRICT

    kind: CapKind
    fixed_amount: Amount | None = None
    pct: Amount | None = None
    basis: CapBasis | None = None
    span: Span | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "CapPool":
        needs_fixed = self.kind in ("fixed", "greater_of")
        needs_pct = self.kind in ("percentage", "greater_of")
        if needs_fixed and self.fixed_amount is None:
            raise ValueError("cap kind " + self.kind + " requires fixed_amount")
        if needs_pct and self.pct is None:
            raise ValueError("cap kind " + self.kind + " requires pct")
        if not needs_fixed and self.fixed_amount is not None:
            raise ValueError("cap kind " + self.kind + " must not set fixed_amount")
        if not needs_pct and self.pct is not None:
            raise ValueError("cap kind " + self.kind + " must not set pct")
        if needs_pct:
            if self.basis is None:
                raise ValueError("cap kind " + self.kind + " requires basis")
            if not 0 < self.pct < 1:
                raise ValueError("pct must be between 0 and 1 exclusive")
        elif self.basis is not None:
            raise ValueError("basis only applies to a percentage cap")
        if self.fixed_amount is not None and self.fixed_amount < 0:
            raise ValueError("fixed_amount must not be negative")
        return self

    @property
    def uses_after_pool(self) -> bool:
        return self.basis == "after_pool"


class Component(BaseModel):
    """One signed line of the EBITDA definition."""

    model_config = STRICT

    item: ItemName
    sign: Sign
    category: Category
    cap_pool: str | None = None
    span: Span
    clause: str | None = None
    reason: str | None = None
    review: Review | None = None

    @model_validator(mode="after")
    def _sentinels_need_a_reason(self) -> "Component":
        if self.item in ("unmapped", "unsupported"):
            if not (self.reason and self.reason.strip()):
                raise ValueError("an " + self.item + " component requires a reason")
        return self

    @property
    def excluded(self) -> bool:
        """True when the reviewer took this component out of the calculation."""
        if self.review is None:
            return False
        return self.review.decision in ("rejected", "excluded_unsupported")

    @property
    def key(self) -> str:
        """Stable identity for traces: item plus clause, or item plus offset."""
        suffix = self.clause if self.clause else str(self.span.start)
        return self.item + "@" + suffix


class BaseTerm(BaseModel):
    """The starting point of the definition, e.g. Consolidated Net Income."""

    model_config = STRICT

    item: ItemName
    span: Span
    clause: str | None = None
    reason: str | None = None


class DraftedWith(BaseModel):
    """Provenance of the LLM draft. A hand-written formula leaves this unset."""

    model_config = STRICT

    model: str
    prompt_version: str
    attempts: int = Field(ge=1)
    temperature: Amount | None = None


FormulaStatus = Literal["draft", "approved", "superseded"]


class EbitdaFormula(BaseModel):
    """The covenant EBITDA definition as an executable formula."""

    model_config = STRICT

    formula_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: FormulaStatus = "draft"
    source_hash: str = Field(min_length=1)
    drafted_with: DraftedWith | None = None
    metric: Literal["consolidated_ebitda"] = "consolidated_ebitda"
    base: BaseTerm
    components: list[Component] = Field(min_length=1)
    cap_pools: dict[str, CapPool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _pools_match(self) -> "EbitdaFormula":
        referenced = {c.cap_pool for c in self.components if c.cap_pool}
        defined = set(self.cap_pools)
        missing = sorted(referenced - defined)
        if missing:
            raise ValueError("components reference undefined cap pools: " + repr(missing))
        unused = sorted(defined - referenced)
        if unused:
            raise ValueError("cap pools are defined but never used: " + repr(unused))
        after = sorted(n for n, pool in self.cap_pools.items() if pool.uses_after_pool)
        if len(after) > 1:
            raise ValueError(
                "two cap pools measured after the pool depend on each other; "
                "the language does not support this: " + repr(after)
            )
        return self

    def pool_items(self, pool: str) -> list[Component]:
        return [c for c in self.components if c.cap_pool == pool]


class NetOfCash(BaseModel):
    """A netting allowance, optionally capped: "less unrestricted cash…"."""

    model_config = STRICT

    enabled: bool
    cap: Amount | None = None
    item: ItemName = "cash_and_equivalents"
    span: Span | None = None

    @model_validator(mode="after")
    def _cap_non_negative(self) -> "NetOfCash":
        if self.cap is not None and self.cap < 0:
            raise ValueError("net_of_cash.cap must not be negative")
        return self


class ItemsSide(BaseModel):
    """One side of a covenant ratio built from balance or flow items."""

    model_config = STRICT

    items: list[ItemName] = Field(min_length=1)
    net_of_cash: NetOfCash | None = None
    span: Span | None = None


class MetricSide(BaseModel):
    """One side of a covenant ratio that is the covenant EBITDA itself."""

    model_config = STRICT

    metric: Literal["consolidated_ebitda"]


def _as_side(value: Any) -> Any:
    if value == "consolidated_ebitda":
        return {"metric": "consolidated_ebitda"}
    return value


Side = Annotated[MetricSide | ItemsSide, BeforeValidator(_as_side)]


class ScheduleStep(BaseModel):
    """A threshold effective from a date until the next step."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    from_: IsoDate = Field(alias="from")
    threshold: Amount

    @model_validator(mode="after")
    def _positive(self) -> "ScheduleStep":
        if self.threshold <= 0:
            raise ValueError("threshold must be positive")
        return self


class TestSpec(BaseModel):
    model_config = STRICT

    frequency: Literal["quarterly"] = "quarterly"
    period: Literal["ttm"] = "ttm"


CovenantType = Literal["max_ratio", "min_ratio"]


class Covenant(BaseModel):
    """A financial maintenance covenant."""

    model_config = STRICT

    id: str = Field(min_length=1)
    name: str | None = None
    type: CovenantType
    numerator: Side
    denominator: Side
    schedule: list[ScheduleStep] = Field(min_length=1)
    test: TestSpec = Field(default_factory=TestSpec)
    span: Span
    reason: str | None = None
    review: Review | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Covenant":
        self.schedule.sort(key=lambda step: step.from_)
        dates = [step.from_ for step in self.schedule]
        if len(set(dates)) != len(dates):
            raise ValueError("schedule has two steps with the same effective date")
        if self.type == "max_ratio":
            if not isinstance(self.denominator, MetricSide):
                raise ValueError("a max_ratio covenant must divide by consolidated_ebitda")
            if not isinstance(self.numerator, ItemsSide):
                raise ValueError("a max_ratio covenant needs an items numerator")
        else:
            if not isinstance(self.numerator, MetricSide):
                raise ValueError("a min_ratio covenant must have consolidated_ebitda on top")
            if not isinstance(self.denominator, ItemsSide):
                raise ValueError("a min_ratio covenant needs an items denominator")
        return self

    def threshold_at(self, as_of: dt.date) -> Decimal | None:
        """The threshold in force on ``as_of``.

        Steps are inclusive of their effective date; ``None`` means the
        schedule only starts after the test date.
        """
        current: Decimal | None = None
        for step in self.schedule:
            if step.from_ <= as_of:
                current = step.threshold
        return current

    @property
    def items_side(self) -> ItemsSide:
        """The side built from items, whichever side that is."""
        side = self.denominator if self.type == "min_ratio" else self.numerator
        assert isinstance(side, ItemsSide)  # guaranteed by _shape
        return side


class DefinitionNode(BaseModel):
    """One term in the definitions graph, resolved deterministically."""

    model_config = STRICT

    term: str = Field(min_length=1)
    depth: int = Field(ge=0)
    span: Span | None = None
    text: str | None = None
    resolved: bool = True
    references: list[str] = Field(default_factory=list)


class FormulaVersion(BaseModel):
    """Everything a run needs from the agreement: the EBITDA formula, the
    covenants, and the definitions graph they were drafted against."""

    model_config = STRICT

    deal_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: FormulaStatus = "draft"
    source_hash: str = Field(min_length=1)
    ebitda: EbitdaFormula
    covenants: list[Covenant] = Field(min_length=1)
    definitions: dict[str, DefinitionNode] = Field(default_factory=dict)
    created_at: IsoDateTime | None = None
    approved_by: str | None = None
    approved_at: IsoDateTime | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "FormulaVersion":
        ids = [c.id for c in self.covenants]
        if len(set(ids)) != len(ids):
            raise ValueError("covenant ids must be unique")
        if self.ebitda.version != self.version:
            raise ValueError("ebitda.version must match the formula version")
        if self.ebitda.source_hash != self.source_hash:
            raise ValueError("ebitda.source_hash must match the version source_hash")
        if self.status == "approved":
            if self.approved_by is None or self.approved_at is None:
                raise ValueError("an approved version records who approved it and when")
        return self
