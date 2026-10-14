"""TTM construction.

Covenants are tested on the last four quarters combined, so every duration
item has to become a sum of exactly four contiguous quarters ending on the test
date, and every balance item has to be a fact dated exactly at the test date.
Anything that cannot be built that way returns a reason code. Nothing is
interpolated, pro-rated or defaulted to zero.

**One basis per window.** A filer that restates rarely republishes every period
it affected, so taking the most recently filed figure for each period
independently can mix two presentations inside one window - and a quarter
derived across that seam is a subtraction of two numbers measured differently.
Every item in a run is therefore built on a single reporting basis, chosen once
for the whole run by :func:`choose_basis`: the restated figures if a complete
window can be built from them, the figures as originally reported if not, and
``inconsistent_basis`` if an item would need the other basis than the one the
run settled on. The basis is recorded on the inputs and travels into the output
hash, so changing it changes the run's identity.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from backend.edgar.facts import (
    BASES,
    BASIS_LABELS,
    Basis,
    Fact,
    basis_conflict,
    instant_at,
    quarter_series,
)
from backend.edgar.mapping import MappingRecord, is_analyst_only
from backend.evaluator.inputs import FactRef, ItemInput, PeriodInputs
from backend.evaluator.money import ZERO, exact, to_decimal
from backend.evaluator.reasons import ReasonCode
from backend.evaluator.vocabulary import NON_NEGATIVE_FLOW_ITEMS


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
        basis=fact.basis,
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


def build_ttm(
    facts: Sequence[Fact], test_date: dt.date, *, basis: Basis | None = None
) -> TtmWindow | None:
    """Sum the four quarters ending on ``test_date``, or return ``None``."""
    series = quarter_series(facts, basis=basis)
    ends = quarter_ends(series, test_date)
    if ends is None or len(ends) != 4:
        return None
    window = tuple(series[end] for end in ends)
    with exact():
        total = sum((fact.value for fact in window), ZERO)
    return TtmWindow(quarters=window, total=total)


def implausible_quarter(item: str, window: TtmWindow) -> Fact | None:
    """A derived quarter whose value the item cannot take.

    Depreciation does not run backwards and a lender does not pay the borrower
    interest, so a negative here is not a small number - it is the signature of
    two cumulative figures that were never on the same basis. The window is
    refused rather than summed, because the total would look entirely ordinary.

    Only derived quarters are checked. A negative figure the filer actually
    reported is the filer's statement and Headroom does not overrule it.
    """
    if item not in NON_NEGATIVE_FLOW_ITEMS:
        return None
    for fact in window.quarters:
        if fact.origin == "derived" and fact.value < 0:
            return fact
    return None


def resolve_duration_item(
    item: str,
    record: MappingRecord,
    facts: Sequence[Fact],
    test_date: dt.date,
    *,
    basis: Basis | None = None,
) -> ItemInput:
    """Build one TTM flow item, or explain why it cannot be built."""
    if not record.usable:
        return _unusable(item, record)
    if record.concept is None:
        return _analyst_value(item, record, test_date)

    window = build_ttm(facts, test_date, basis=basis)
    if window is None:
        code = _diagnose_duration(facts, test_date, basis=basis)
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason=code,
            concept=record.concept,
            mapping_version=record.mapping_version,
            note=_duration_note(code, record.concept, test_date, facts=facts, basis=basis),
        )

    broken = implausible_quarter(item, window)
    if broken is not None:
        return ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="implausible_value",
            concept=record.concept,
            mapping_version=record.mapping_version,
            note=(
                record.concept
                + " for the derived quarter "
                + str(broken.start)
                + ".."
                + str(broken.end)
                + " is "
                + str(broken.value)
                + ", which this item cannot be. "
                + (broken.transformation or "")
            ).strip(),
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
    *,
    basis: Basis | None = None,
) -> ItemInput:
    """Take the balance dated exactly at the test date, or explain why not."""
    if not record.usable:
        return _unusable(item, record)
    if record.concept is None:
        return _analyst_value(item, record, test_date)

    fact = instant_at(facts, test_date, basis=basis)
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


def _diagnose_duration(
    facts: Sequence[Fact], test_date: dt.date, *, basis: Basis | None = None
) -> ReasonCode:
    """Say why a TTM window could not be built.

    ``incompatible_facts`` means the facts exist but cannot be combined, for
    example a fiscal year and a nine-month period that do not share a start
    date. ``missing_quarter`` means a quarter is neither reported nor derivable.
    """
    series = quarter_series(facts, basis=basis)
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


def _duration_note(
    code: str,
    concept: str,
    test_date: dt.date,
    *,
    facts: Sequence[Fact] = (),
    basis: Basis | None = None,
) -> str:
    if code == "incompatible_facts":
        note = (
            concept
            + " is reported only in periods that cannot be combined into quarters"
            + " ending "
            + test_date.isoformat()
        )
    else:
        note = (
            "the four quarters ending "
            + test_date.isoformat()
            + " are not all reported or derivable for "
            + concept
        )
    if basis is not None:
        note += " on the figures " + BASIS_LABELS[basis]
        conflict = basis_conflict(facts)
        if conflict:
            note += ". " + conflict
    return note


def resolve_all(
    *,
    test_date: dt.date,
    records: dict[str, MappingRecord],
    facts_by_concept: dict[str, list[Fact]],
    items: Sequence[str],
    basis: Basis | None,
) -> dict[str, ItemInput]:
    """Resolve every required item on one reporting basis."""
    resolved: dict[str, ItemInput] = {}
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
            resolved[item] = resolve_instant_item(item, record, facts, test_date, basis=basis)
        else:
            resolved[item] = resolve_duration_item(item, record, facts, test_date, basis=basis)
    return resolved


def choose_basis(attempts: dict[str, dict[str, ItemInput]]) -> tuple[Basis, set[str]]:
    """Pick the one basis the whole run is built on.

    ``attempts`` maps each basis to what it resolved. The restated figures win
    whenever they can produce everything the other basis could, because they
    are the filer's current statement of the period. The original figures win
    when the restated ones cannot, which is what happens when a restatement
    landed inside the window and the filer never reissued the comparative.

    When neither basis covers everything, the run still commits to one - the
    one that resolves more items, restated breaking the tie - and the items
    only the other basis could have produced are returned as the second value,
    to be reported as ``inconsistent_basis``. Mixing them is the one thing that
    is never done.
    """
    usable = {
        basis: {item for item, found in resolved.items() if found.usable}
        for basis, resolved in attempts.items()
    }
    union: set[str] = set()
    for found in usable.values():
        union |= found

    for basis in BASES:
        if basis in usable and usable[basis] == union:
            return basis, set()

    best = max(BASES, key=lambda basis: (len(usable.get(basis, set())), basis == "as_restated"))
    return best, union - usable.get(best, set())


def build_period_inputs(
    *,
    deal_id: str,
    test_date: dt.date,
    records: dict[str, MappingRecord],
    facts_by_concept: dict[str, list[Fact]],
    items: Sequence[str],
) -> PeriodInputs:
    """Resolve every required item for one test quarter, on one basis."""
    attempts = {
        basis: resolve_all(
            test_date=test_date,
            records=records,
            facts_by_concept=facts_by_concept,
            items=items,
            basis=basis,
        )
        for basis in BASES
    }
    basis, lost = choose_basis(attempts)
    resolved = dict(attempts[basis])

    for item in sorted(lost):
        record = records.get(item)
        facts = facts_by_concept.get((record.concept if record else None) or "", [])
        conflict = basis_conflict(facts)
        resolved[item] = ItemInput(
            item=item,  # type: ignore[arg-type]
            reason="inconsistent_basis",
            concept=record.concept if record else None,
            mapping_version=record.mapping_version if record else None,
            note=(
                "this item can only be built from the figures "
                + BASIS_LABELS[_other_basis(basis)]
                + ", and the rest of the run is built from the figures "
                + BASIS_LABELS[basis]
                + "; mixing the two inside one trailing twelve month window "
                + "would subtract figures measured on different bases"
                + (". " + conflict if conflict else "")
            ),
        )

    quarters: list[str] = []
    for item in items:
        found = resolved.get(item)
        if found is not None and found.usable and len(found.facts) == 4:
            quarters = [str(ref.start) + ".." + str(ref.end) for ref in found.facts]
            break

    return PeriodInputs(
        deal_id=deal_id,
        test_date=test_date,
        quarters=quarters,
        basis=basis,
        basis_note=_basis_note(basis, attempts),
        items=resolved,
    )


def _other_basis(basis: Basis) -> Basis:
    return "as_originally_reported" if basis == "as_restated" else "as_restated"


def _basis_note(basis: Basis, attempts: dict[str, dict[str, ItemInput]]) -> str:
    """Why the run is on this basis, in one sentence for the audit trail."""
    counts = {
        name: sum(1 for found in resolved.values() if found.usable)
        for name, resolved in attempts.items()
    }
    other = _other_basis(basis)
    note = "Built from the figures " + BASIS_LABELS[basis] + "."
    if counts.get(basis, 0) > counts.get(other, 0):
        note += (
            " The figures "
            + BASIS_LABELS[other]
            + " resolve only "
            + str(counts.get(other, 0))
            + " of "
            + str(len(attempts[basis]))
            + " items, because a restatement falls inside the window and the"
            + " filer did not reissue every period it affected."
        )
    elif counts.get(basis, 0) == counts.get(other, 0):
        note += " Both bases resolve the same items; the current figures are preferred."
    return note


def available_test_dates(
    facts_by_concept: dict[str, list[Fact]],
    anchor_concept: str = "NetIncomeLoss",
) -> list[dt.date]:
    """Quarter ends for which a full TTM window exists for the anchor concept.

    Offered to the analyst as the quarters a run can actually be built for,
    rather than letting them pick a date that will fail closed. A date is
    offered when either basis can build the anchor's window, since the run
    chooses between them itself.
    """
    facts = facts_by_concept.get(anchor_concept, [])
    found: set[dt.date] = set()
    for basis in BASES:
        series = quarter_series(facts, basis=basis)
        found |= {end for end in series if quarter_ends(series, end) is not None}
    return sorted(found)


def analyst_only(item: str) -> bool:
    return is_analyst_only(item)
