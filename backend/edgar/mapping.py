"""Mapping records: the second approval gate.

``mapping.yaml`` lists candidate concepts per formula item, but a candidate is
only a suggestion. An available concept is not necessarily the contractual
item, so every deal gets its own record per item and only a ``verified`` record
with a written rationale can feed a computable result.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.evaluator.schema import STRICT, IsoDate, IsoDateTime
from backend.evaluator.vocabulary import ANALYST_ONLY_ITEMS, ItemName, period_type_for

MAPPING_FILE = Path(__file__).resolve().parent.parent / "mapping.yaml"

MappingStatus = Literal["review_required", "verified", "unavailable"]


class CandidateSet(BaseModel):
    """What ``mapping.yaml`` says about one item."""

    model_config = ConfigDict(extra="forbid")

    period_type: Literal["duration", "instant"]
    candidates: list[str] = Field(default_factory=list)
    note: str | None = None


class MappingRecord(BaseModel):
    """One deal's decision about one formula item."""

    model_config = STRICT

    formula_item: ItemName
    concept: str | None = None
    status: MappingStatus = "review_required"
    period_type: Literal["duration", "instant"]
    rationale: str | None = None
    mapping_version: int = Field(default=1, ge=1)
    analyst_value: str | None = None
    analyst_value_as_of: IsoDate | None = None
    decided_by: str | None = None
    decided_at: IsoDateTime | None = None

    @model_validator(mode="after")
    def _gate(self) -> "MappingRecord":
        if self.analyst_value is not None and self.analyst_value_as_of is None:
            # An analyst value is a figure for one TTM period, hand-summed from
            # that period's filings. Without the period it is bound to, the
            # next quarter's run would silently reuse last quarter's number.
            raise ValueError("an analyst value must record the test date it was sourced for")
        if self.concept is not None and self.analyst_value is not None:
            # A concept and an analyst value are alternatives, not a value with
            # a label: holding both would leave which one computes implicit.
            raise ValueError("a mapping has either a concept or an analyst value, not both")
        if self.status == "verified":
            if not (self.rationale and self.rationale.strip()):
                raise ValueError("a verified mapping requires a written rationale")
            if self.concept is None and self.analyst_value is None:
                raise ValueError(
                    "a verified mapping needs either a concept or an analyst value"
                )
        if self.status == "unavailable" and not (self.rationale and self.rationale.strip()):
            raise ValueError("an unavailable mapping requires a rationale")
        return self

    @property
    def usable(self) -> bool:
        return self.status == "verified"

    def verify(self, *, rationale: str, by: str | None = None) -> "MappingRecord":
        """Approve this mapping, bumping its version."""
        return self.model_copy(
            update={
                "status": "verified",
                "rationale": rationale,
                "mapping_version": self.mapping_version + 1,
                "decided_by": by,
                "decided_at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            }
        )

    def mark_unavailable(self, *, rationale: str, by: str | None = None) -> "MappingRecord":
        return self.model_copy(
            update={
                "status": "unavailable",
                "rationale": rationale,
                "mapping_version": self.mapping_version + 1,
                "decided_by": by,
                "decided_at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            }
        )


@lru_cache(maxsize=1)
def load_candidates(path: str | None = None) -> dict[str, CandidateSet]:
    """Parse ``mapping.yaml`` into candidate sets, once per process."""
    target = Path(path) if path else MAPPING_FILE
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    items = payload.get("items", {})
    parsed: dict[str, CandidateSet] = {}
    for item, body in items.items():
        parsed[item] = CandidateSet.model_validate(body)
    return parsed


def candidates_for(item: str) -> list[str]:
    table = load_candidates()
    found = table.get(item)
    return list(found.candidates) if found else []


def propose(item: str, *, available: set[str] | None = None) -> MappingRecord:
    """Propose a mapping for ``item``, always as ``review_required``.

    When the company's reported concepts are known, the first candidate that
    actually has facts is proposed; otherwise the first candidate is. Items
    with no concept at all (projected cost savings) are proposed with no
    concept, which is what makes the analyst supply a sourced value.
    """
    options = candidates_for(item)
    chosen: str | None = None
    if options:
        if available is None:
            chosen = options[0]
        else:
            for candidate in options:
                if candidate in available:
                    chosen = candidate
                    break
    return MappingRecord(
        formula_item=item,  # type: ignore[arg-type]
        concept=chosen,
        status="review_required",
        period_type=period_type_for(item),
    )


def required_items(version) -> list[str]:  # noqa: ANN001 - FormulaVersion, avoids a cycle
    """Every item a run of ``version`` would need a mapping for.

    Excluded components are left out: the reviewer took them out of the
    calculation, so demanding a mapping for them would block a run for no
    reason.
    """
    items: list[str] = [version.ebitda.base.item]
    for component in version.ebitda.components:
        if component.excluded or component.item in ("unmapped", "unsupported"):
            continue
        items.append(component.item)
    for covenant in version.covenants:
        side = covenant.items_side
        items.extend(side.items)
        if side.net_of_cash is not None and side.net_of_cash.enabled:
            items.append(side.net_of_cash.item)
    ordered: list[str] = []
    for item in items:
        if item not in ordered and item not in ("unmapped", "unsupported"):
            ordered.append(item)
    return ordered


def mapping_coverage(records: dict[str, MappingRecord], items: list[str]) -> tuple[int, int]:
    """Verified mappings over required mappings, as a reported metric."""
    verified = sum(1 for item in items if item in records and records[item].usable)
    return verified, len(items)


def is_analyst_only(item: str) -> bool:
    return item in ANALYST_ONLY_ITEMS or not candidates_for(item)
