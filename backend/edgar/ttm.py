"""TTM construction.

Covenants are tested on the last four quarters combined, so every duration
item has to become a sum of exactly four contiguous quarters ending on the test
date, and every balance item has to be a fact dated exactly at the test date.
Anything that cannot be built that way returns a reason code. Nothing is
interpolated, pro-rated or defaulted to zero.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from backend.edgar.facts import Fact, instant_at, quarter_series
from backend.edgar.mapping import MappingRecord, is_analyst_only
from backend.evaluator.inputs import FactRef, ItemInput, PeriodInputs
from backend.evaluator.money import ZERO, exact, to_decimal
from backend.evaluator.reasons import ReasonCode


@dataclass(frozen=True)
class TtmWindow:
    """The four quarters that make up a TTM period."""

    quarters: tuple[Fact, ...]
    total: Decimal

    @property
    def labels(self) -> list[str]:
        return [str(fact.start) + ".." + str(fact.end) for fact in self.quarters]


def _to_ref(fact: Fact) -> FactRef:
    return FactRef(
        concept=fact.concept,
        value=fact.value,
        unit=fact.unit,
        period_type=fact.period_type,
        start=fact.start,
        end=fact.end,
        instant=fact.instant,
        form=fact.form,
        accession=fact.accession,
        filed=fact.filed,
        fy=fact.fy,
        fp=fact.fp,
        origin=fact.origin,  # type: ignore[arg-type]
        transformation=fact.transformation,
    )


def quarter_ends(series: dict[dt.date, Fact], test_date: dt.date) -> list[dt.date] | None:
    """The four contiguous quarter ends finishing on ``test_date``.

    Contiguity is checked against the quarters' actual start and end dates: the
    chain must run back from the test date with no gap and no overlap, and span
    something that is really a year. A six-month period cannot slip in, because
    it would not chain.
    """
    if test_date not in series:
        return None
    chain: list[Fact] = [series[test_date]]
    for _ in range(3):
        head = chain[-1]
        if head.start is None:
            return None
        previous_end = head.start - dt.timedelta(days=1)
        earlier = series.get(previous_end)
        if earlier is None:
            return None
        chain.append(earlier)
    oldest = chain[-1]
    if oldest.start is None:
        return None
    span = (test_date - oldest.start).days + 1
    if not 350 <= span <= 380:
        return None
    return [fact.end for fact in reversed(chain) if fact.end is not None]


def build_ttm(facts: Sequence[Fact], test_date: dt.date) -> TtmWindow | None:
    """Sum the four quarters ending on ``test_date``, or return ``None``."""
    series = quarter_series(facts)
    ends = quarter_ends(series, test_date)
    if ends is None or len(ends) != 4:
        return None
    window = tuple(series[end] for end in ends)
    with exact():
        total = sum((fact.value for fact in window), ZERO)
    return TtmWindow(quarters=window, total=total)


def resolve_duration_item(
    item: str,
    record: MappingRecord,
    facts: Sequence[Fact],
    test_date: dt.date,
) -> ItemInput:
    """Build one TTM flow item, or explain why it cannot be built."""
    if not record.usable:
        return _unusable(item, record)
    if record.concept is None:
        return _analyst_value(item, record, test_date)

    window = build_ttm(facts, test_date)
    if window is None:
        code = _diagnose_duration(facts, test_date)
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason=code,
            concept=record.concept,
            mapping_version=record.mapping_version,
            note=_duration_note(code, record.concept, test_date),
        )
    return ItemInput(
        item=item,  # type: ignore[arg-type]
        value=window.total,
        origin="derived" if any(f.origin == "derived" for f in window.quarters) else "reported",
        concept=record.concept,
        mapping_version=record.mapping_version,
        facts=[_to_ref(fact) for fact in window.quarters],
        note="TTM of " + ", ".join(window.labels),
    )


def resolve_instant_item(
    item: str,
    record: MappingRecord,
    facts: Sequence[Fact],
    test_date: dt.date,
) -> ItemInput:
    """Take the balance dated exactly at the test date, or explain why not."""
    if not record.usable:
        return _unusable(item, record)
    if record.concept is None:
        return _analyst_value(item, record, test_date)

    fact = instant_at(facts, test_date)
    if fact is None:
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="missing_instant",
            concept=record.concept,
            mapping_version=record.mapping_version,
            note="no " + record.concept + " fact is dated " + test_date.isoformat(),
        )
    return ItemInput(
        item=item,  # type: ignore[arg-type]
        value=fact.value,
        origin="reported",
        concept=record.concept,
        mapping_version=record.mapping_version,
        facts=[_to_ref(fact)],
    )


def _unusable(item: str, record: MappingRecord) -> ItemInput:
    """A mapping that has not been verified cannot feed a result."""
    if record.status == "unavailable":
        if record.analyst_value is not None:
            return ItemInput(
                item=item,  # type: ignore[arg-type]
                reason="missing_analyst_input",
                concept=None,
                mapping_version=record.mapping_version,
                note="an unavailable mapping must be verified before its value is used",
            )
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="missing_analyst_input",
            mapping_version=record.mapping_version,
            note=record.rationale,
        )
    return ItemInput(
        item=item,  # type: ignore[arg-type]
        reason="ambiguous_mapping",
        concept=record.concept,
        mapping_version=record.mapping_version,
        note=record.rationale or "the mapping is still review_required",
    )


def _analyst_value(item: str, record: MappingRecord, test_date: dt.date) -> ItemInput:
    """A verified mapping with no concept: the analyst supplied the number.

    An analyst value is a figure for one TTM period, hand-summed from that
    period's filings. Reusing it for another quarter would be the same silent
    assumption as substituting zero, so a value sourced for a different test
    date is refused rather than carried forward.
    """
    if record.analyst_value is None:
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="missing_analyst_input",
            mapping_version=record.mapping_version,
            note=record.rationale,
        )
    if record.analyst_value_as_of != test_date:
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="missing_analyst_input",
            mapping_version=record.mapping_version,
            note=(
                "the analyst value was sourced for the period ending "
                + str(record.analyst_value_as_of)
                + " and cannot be reused for "
                + test_date.isoformat()
            ),
        )
    value = to_decimal(record.analyst_value, field=item)
    return ItemInput(
        item=item,  # type: ignore[arg-type]
        value=value,
        origin="analyst",
        mapping_version=record.mapping_version,
        note=record.rationale,
        facts=[
            FactRef(
                concept="analyst_input",
                value=value,
                period_type="duration",
                end=test_date,
                origin="analyst",
                transformation=record.rationale,
            )
        ],
    )


def _diagnose_duration(facts: Sequence[Fact], test_date: dt.date) -> ReasonCode:
    """Say why a TTM window could not be built.

    ``incompatible_facts`` means the facts exist but cannot be combined, for
    example a fiscal year and a nine-month period that do not share a start
    date. ``missing_quarter`` means a quarter is neither reported nor derivable.
    """
    series = quarter_series(facts)
    if test_date in series:
        # The quarter itself exists, so one of the three before it is missing.
        return "missing_quarter"
    ends_on_test_date = [
        fact
        for fact in facts
        if fact.period_type == "duration" and fact.end == test_date
    ]
    if ends_on_test_date:
        # A period ends exactly on the test date but no quarter could be formed
        # from it: the cumulative periods do not share a start date, so they
        # are not two views of the same running total.
        return "incompatible_facts"
    return "missing_quarter"


def _duration_note(code: str, concept: str, test_date: dt.date) -> str:
    if code == "incompatible_facts":
        return (
            concept
            + " is reported only in periods that cannot be combined into quarters"
            + " ending "
            + test_date.isoformat()
        )
    return (
        "the four quarters ending "
        + test_date.isoformat()
        + " are not all reported or derivable for "
        + concept
    )


def build_period_inputs(
    *,
    deal_id: str,
    test_date: dt.date,
    records: dict[str, MappingRecord],
    facts_by_concept: dict[str, list[Fact]],
    items: Sequence[str],
) -> PeriodInputs:
    """Resolve every required item for one test quarter."""
    resolved: dict[str, ItemInput] = {}
    quarters: list[str] = []
    for item in items:
        record = records.get(item)
        if record is None:
            resolved[item] = ItemInput(
                item=item,  # type: ignore[arg-type]
                reason="ambiguous_mapping",
                note="no mapping record exists for this item",
            )
            continue
        facts = facts_by_concept.get(record.concept or "", [])
        if record.period_type == "instant":
            resolved[item] = resolve_instant_item(item, record, facts, test_date)
        else:
            resolved[item] = resolve_duration_item(item, record, facts, test_date)
            if not quarters and len(resolved[item].facts) == 4:
                quarters = [
                    str(ref.start) + ".." + str(ref.end) for ref in resolved[item].facts
                ]
    return PeriodInputs(
        deal_id=deal_id,
        test_date=test_date,
        quarters=quarters,
        items=resolved,
    )


def available_test_dates(
    facts_by_concept: dict[str, list[Fact]],
    anchor_concept: str = "NetIncomeLoss",
) -> list[dt.date]:
    """Quarter ends for which a full TTM window exists for the anchor concept.

    Offered to the analyst as the quarters a run can actually be built for,
    rather than letting them pick a date that will fail closed.
    """
    facts = facts_by_concept.get(anchor_concept, [])
    series = quarter_series(facts)
    usable = [end for end in sorted(series) if quarter_ends(series, end) is not None]
    return usable


def analyst_only(item: str) -> bool:
    return is_analyst_only(item)
