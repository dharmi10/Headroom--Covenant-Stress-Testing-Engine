"""XBRL facts with provenance.

One ``companyfacts`` call returns everything a company has ever reported. This
module turns the relevant part of it into facts that remember where they came
from: concept, unit, period, form, accession number, filing date and whether
the value was reported or derived. Nothing here decides what a fact means for a
covenant; that is the mapping gate's job.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable, Iterator, Literal

from backend.evaluator.money import to_decimal

#: Which vintage of the filer's own figures a window is built from.
#:
#: ``as_restated`` takes the most recent presentation of every period;
#: ``as_originally_reported`` takes each period as it was first published. The
#: two are never mixed inside one window, which is what :func:`facts_on_basis`
#: enforces.
Basis = Literal["as_restated", "as_originally_reported"]

#: Tried in this order: the current figures first, the original ones only if
#: the current ones cannot produce a complete window.
BASES: tuple[Basis, ...] = ("as_restated", "as_originally_reported")

BASIS_LABELS: dict[str, str] = {
    "as_restated": "as restated",
    "as_originally_reported": "as originally reported",
}

#: Only periodic reports and their amendments. A fact first seen in an 8-K or
#: an S-1 is not part of the quarterly reporting series.
ACCEPTED_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT"})

#: A duration this long is treated as one fiscal quarter. Quarters are never
#: identified by length alone: the fiscal year, fiscal period and the actual
#: start and end dates all have to agree as well.
QUARTER_MIN_DAYS = 80
QUARTER_MAX_DAYS = 100
YEAR_MIN_DAYS = 350
YEAR_MAX_DAYS = 380


@dataclass(frozen=True)
class Fact:
    """One reported or derived financial fact."""

    concept: str
    value: Decimal
    unit: str
    period_type: str  # "duration" or "instant"
    start: dt.date | None
    end: dt.date | None
    instant: dt.date | None
    form: str | None
    accession: str | None
    filed: dt.date | None
    fy: int | None
    fp: str | None
    origin: str = "reported"
    transformation: str | None = None
    derived_from: tuple[str, ...] = ()
    #: Which reporting basis this fact was selected on, once a basis has been
    #: chosen. ``None`` on a fact nobody has filtered yet.
    basis: str | None = None

    @property
    def days(self) -> int | None:
        if self.period_type != "duration" or self.start is None or self.end is None:
            return None
        return (self.end - self.start).days + 1

    @property
    def is_quarter(self) -> bool:
        days = self.days
        return days is not None and QUARTER_MIN_DAYS <= days <= QUARTER_MAX_DAYS

    @property
    def is_year(self) -> bool:
        days = self.days
        return days is not None and YEAR_MIN_DAYS <= days <= YEAR_MAX_DAYS

    @property
    def period_key(self) -> tuple:
        if self.period_type == "instant":
            return ("instant", self.instant)
        return ("duration", self.start, self.end)

    def label(self) -> str:
        if self.period_type == "instant":
            return self.concept + " @ " + str(self.instant)
        return self.concept + " " + str(self.start) + ".." + str(self.end)


def _as_date(value: object) -> dt.date | None:
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def parse_company_facts(
    payload: dict,
    *,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
) -> dict[str, list[Fact]]:
    """Every accepted fact in ``payload``, grouped by concept."""
    facts: dict[str, list[Fact]] = {}
    concepts = payload.get("facts", {}).get(taxonomy, {})
    for concept, body in concepts.items():
        rows = body.get("units", {}).get(unit)
        if not rows:
            continue
        parsed = list(_parse_rows(concept, rows, unit))
        if parsed:
            facts[concept] = parsed
    return facts


def _parse_rows(concept: str, rows: Iterable[dict], unit: str) -> Iterator[Fact]:
    for row in rows:
        form = row.get("form")
        if form not in ACCEPTED_FORMS:
            continue
        if "val" not in row:
            continue
        end = _as_date(row.get("end"))
        start = _as_date(row.get("start"))
        if end is None:
            continue
        period_type = "duration" if start is not None else "instant"
        try:
            value = to_decimal(row["val"], field=concept)
        except (TypeError, ValueError):
            continue
        yield Fact(
            concept=concept,
            value=value,
            unit=unit,
            period_type=period_type,
            start=start,
            end=end if period_type == "duration" else None,
            instant=end if period_type == "instant" else None,
            form=form,
            accession=row.get("accn"),
            filed=_as_date(row.get("filed")),
            fy=row.get("fy") if isinstance(row.get("fy"), int) else None,
            fp=row.get("fp") if isinstance(row.get("fp"), str) else None,
        )


# -- reporting basis ---------------------------------------------------------
#
# A filer that restates does not republish every period it affected. Teleflex
# restated fiscal 2024 in its 2026 10-K but never reissued the nine months to
# September 2024, so the two cumulative figures a fourth quarter is derived
# from end up on different bases, and the subtraction produces a number nobody
# ever reported - for Teleflex, a quarter with negative depreciation.
#
# The fix is to treat a cumulative series as having two vintages either side of
# the restatement, and to build a window out of one vintage only:
#
# * a **series** is one concept, one unit and one start date, which is exactly
#   the group a quarter may be derived within;
# * the series' **restatement boundary** is the earliest filing that reported
#   one of its periods with a value differing from that period's first
#   published value;
# * facts filed before the earliest boundary are the *original* cohort, facts
#   filed at or after the latest boundary are the *restated* cohort, and a
#   series nobody restated has one cohort that serves both bases.
#
# Filtering to a cohort before anything is derived means the two cumulative
# facts behind a derived quarter are always either from the same filing or from
# the same side of the restatement. Neither basis is "the truth": the choice is
# recorded on the run so a reader knows which set of figures they are looking
# at.


def series_key(fact: Fact) -> tuple:
    """The group a fact can be compared and subtracted within.

    Durations are keyed by start date, so one year-to-date series is one key.
    Instants are keyed by their own date: restating one balance sheet date says
    nothing about another.
    """
    if fact.period_type == "instant":
        return (fact.concept, fact.unit, "instant", fact.instant)
    return (fact.concept, fact.unit, "duration", fact.start)


def restated_periods(facts: Iterable[Fact]) -> list[tuple[Fact, Fact]]:
    """Every period reported twice with different values, as (first, later).

    The pairs are what the audit trail quotes when it has to explain that a
    window could not be built on one basis.
    """
    by_period: dict[tuple, list[Fact]] = {}
    for fact in facts:
        by_period.setdefault(fact.period_key, []).append(fact)
    found: list[tuple[Fact, Fact]] = []
    for key in sorted(by_period, key=lambda k: tuple(str(part) for part in k)):
        group = sorted(by_period[key], key=_filing_order)
        first = group[0]
        for later in group[1:]:
            if later.value != first.value:
                found.append((first, later))
    return found


def _boundaries(facts: Iterable[Fact]) -> list[dt.date]:
    """The filing dates at which a value in this series changed."""
    dates: list[dt.date] = []
    for _first, later in restated_periods(facts):
        if later.filed is not None:
            dates.append(later.filed)
    return sorted(set(dates))


def facts_on_basis(facts: Iterable[Fact], basis: Basis) -> list[Fact]:
    """Keep only the facts that belong to ``basis``, series by series.

    A series nobody restated is kept whole, because its single presentation is
    both the original and the current one. A series that was restated is cut at
    its boundary, and only one side survives. The surviving facts are tagged
    with the basis so the provenance in the audit trail says which vintage a
    figure came from.
    """
    by_series: dict[tuple, list[Fact]] = {}
    for fact in facts:
        by_series.setdefault(series_key(fact), []).append(fact)

    kept: list[Fact] = []
    for key in sorted(by_series, key=lambda k: tuple(str(part) for part in k)):
        group = by_series[key]
        bounds = _boundaries(group)
        if not bounds:
            kept.extend(replace(fact, basis=basis) for fact in group)
            continue
        # Several restatements leave several boundaries. Taking the latest for
        # the restated side and the earliest for the original side keeps each
        # cohort inside one presentation rather than straddling two.
        if basis == "as_restated":
            cut = bounds[-1]
            kept.extend(
                replace(fact, basis=basis)
                for fact in group
                if fact.filed is not None and fact.filed >= cut
            )
        else:
            cut = bounds[0]
            kept.extend(
                replace(fact, basis=basis)
                for fact in group
                if fact.filed is not None and fact.filed < cut
            )
    return kept


def basis_conflict(facts: Iterable[Fact]) -> str | None:
    """A sentence naming the restatements that split this concept's series.

    ``None`` when nothing was ever restated, in which case a window that could
    not be built has some other problem and must not be blamed on the basis.
    """
    pairs = restated_periods(facts)
    if not pairs:
        return None
    parts: list[str] = []
    for first, later in pairs[:4]:
        parts.append(
            first.label()
            + " was first reported as "
            + str(first.value)
            + " in "
            + (first.accession or "an earlier filing")
            + " and restated to "
            + str(later.value)
            + " in "
            + (later.accession or "a later filing")
            + (" filed " + str(later.filed) if later.filed else "")
        )
    if len(pairs) > 4:
        parts.append("and " + str(len(pairs) - 4) + " further restated period(s)")
    return "; ".join(parts)


def latest_by_period(facts: Iterable[Fact]) -> dict[tuple, Fact]:
    """Collapse restatements and amendments to one fact per period.

    When a period is reported more than once, the most recently filed value
    wins and the filing it came from is kept, so a restatement is visible in
    the audit trail rather than silently averaged away.
    """
    best: dict[tuple, Fact] = {}
    for fact in facts:
        key = fact.period_key
        current = best.get(key)
        if current is None or _filing_order(fact) > _filing_order(current):
            best[key] = fact
    return best


def _filing_order(fact: Fact) -> tuple:
    return (
        fact.filed or dt.date.min,
        fact.accession or "",
        # An amendment filed the same day as the original supersedes it.
        1 if (fact.form or "").endswith("/A") else 0,
    )


def instant_at(
    facts: Iterable[Fact], on: dt.date, *, basis: Basis | None = None
) -> Fact | None:
    """The balance reported exactly at ``on``, latest filing wins.

    Nothing is interpolated: a debt balance dated three days off the test date
    is a different number, and guessing it would be the kind of silent
    approximation Headroom exists to avoid. With ``basis`` set, a balance sheet
    date the filer restated is taken on the same basis as the flows, so the
    numerator and the denominator of a covenant ratio agree.
    """
    pool = facts_on_basis(facts, basis) if basis is not None else list(facts)
    best: Fact | None = None
    for fact in pool:
        if fact.period_type != "instant" or fact.instant != on:
            continue
        if best is None or _filing_order(fact) > _filing_order(best):
            best = fact
    return best


def derive_quarters(facts: Iterable[Fact], *, basis: Basis | None = None) -> list[Fact]:
    """Quarters implied by the difference of two year-to-date periods.

    A filer that reports a concept only year to date never states the quarter
    directly. Subtracting the shorter cumulative period from the longer one
    recovers it, but only when both facts are two views of the same running
    total: same concept, same unit, same fiscal year, same start date, **and
    the same reporting basis**. ``Q4 = FY - 9M YTD`` is this rule's best known
    case.

    **Why the basis belongs in the compatibility rule.** A fourth quarter can
    never be derived inside a single filing, because the full year is in the
    10-K and the nine months are in the third quarter's 10-Q. The derivation
    therefore always spans two filings, and if a restatement happened between
    them the two figures are measured on different bases. Passing ``basis``
    filters the facts to one cohort first (see :func:`facts_on_basis`), so the
    subtraction is either within one filing or within one presentation.
    Calling this without a basis keeps the older, looser behaviour and is kept
    only for inspecting what a filer reported.

    **Why the fiscal year is the start date, not the ``fy`` field.** ``fy`` in
    companyfacts is the fiscal year of the *filing* a fact appeared in, not of
    the period it covers: a filer's Q1 year-to-date fact routinely carries the
    next year's ``fy`` because it was restated in a later report. Keying on
    ``fy`` therefore splits one year-to-date series in half and silently loses
    the quarter at the split. The shared start date identifies the fiscal year
    exactly, since a year-to-date series starts on the first day of it.
    """
    if basis is not None:
        facts = facts_on_basis(facts, basis)
    reported = list(latest_by_period(facts).values())
    durations = [fact for fact in reported if fact.period_type == "duration"]
    by_start: dict[tuple, list[Fact]] = {}
    for fact in durations:
        by_start.setdefault((fact.concept, fact.unit, fact.start), []).append(fact)

    existing = {fact.period_key for fact in reported}
    derived: list[Fact] = []
    # Sorted so two groups that imply the same quarter resolve the same way
    # on every run.
    for key_tuple in sorted(by_start, key=lambda k: tuple(str(part) for part in k)):
        group = by_start[key_tuple]
        group.sort(key=lambda fact: fact.end or dt.date.min)
        for index in range(1, len(group)):
            longer = group[index]
            shorter = group[index - 1]
            if longer.end is None or shorter.end is None:
                continue
            start = shorter.end + dt.timedelta(days=1)
            if start > longer.end:
                continue
            gap = (longer.end - start).days + 1
            if not QUARTER_MIN_DAYS <= gap <= QUARTER_MAX_DAYS:
                continue
            key = ("duration", start, longer.end)
            if key in existing:
                continue
            existing.add(key)
            derived.append(
                replace(
                    longer,
                    value=longer.value - shorter.value,
                    start=start,
                    origin="derived",
                    transformation=(
                        _span_label(longer)
                        + " minus "
                        + _span_label(shorter)
                        + " (shared fiscal year and start date"
                        + (
                            ", one filing"
                            if longer.accession and longer.accession == shorter.accession
                            else ", same reporting basis"
                        )
                        + (
                            ": " + BASIS_LABELS[basis]
                            if basis is not None
                            else ""
                        )
                        + ")"
                    ),
                    derived_from=tuple(
                        sorted(
                            {longer.accession or "", shorter.accession or ""} - {""}
                        )
                    ),
                )
            )
    return derived


def _span_label(fact: Fact) -> str:
    days = fact.days or 0
    months = max(1, round(days / 30.4))
    return str(months) + "M to " + str(fact.end)


def quarter_series(
    facts: Iterable[Fact], *, basis: Basis | None = None
) -> dict[dt.date, Fact]:
    """Every quarter available for a concept, reported or derived, by end date.

    A reported quarter always beats a derived one for the same period: a figure
    the filer stated is better evidence than a subtraction. With ``basis`` set,
    only that basis' figures are eligible, so a quarter the filer restated is
    taken on one presentation rather than whichever version was filed last.
    """
    pool = list(facts_on_basis(facts, basis)) if basis is not None else list(facts)
    reported = latest_by_period(pool)
    series: dict[dt.date, Fact] = {}
    for fact in reported.values():
        if fact.period_type == "duration" and fact.is_quarter and fact.end is not None:
            series[fact.end] = fact
    for fact in derive_quarters(pool):
        if fact.end is not None and fact.end not in series:
            series[fact.end] = fact
    return series
