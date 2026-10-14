"""Does a "one-time" charge recur?

A credit agreement lets the borrower add back "extraordinary, unusual or
non-recurring" charges. Whether a charge is actually non-recurring is a
question about the borrower's history, not about the contract, and it is
answerable from the filings: a restructuring charge the borrower has reported
in most of the last four fiscal years is a cost of doing business that happens
to be labelled one-time.

The test here is deliberately mechanical, because the alternative is an
opinion. A charge recurs when its mapped concept carries a **non-zero annual
fact in at least ``min_years`` of the last ``window_years`` fiscal years**
ending on or before the test date. Both numbers are configurable, the window
examined is reported, and every year's amount and accession number travels with
the finding so a reviewer can disagree with the conclusion rather than with a
black box.

Nothing here decides what to do about it. The evaluator promotes a ``one_time``
component to ``aggressive_recurring`` when the finding says it recurs, and the
scenario ladder does the rest.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from backend.edgar.facts import Basis, Fact, facts_on_basis, latest_by_period
from backend.evaluator.money import dec_str

#: A charge reported in at least this many of the examined years recurs.
DEFAULT_MIN_YEARS = 3

#: How many fiscal years back to look.
DEFAULT_WINDOW_YEARS = 4


@dataclass(frozen=True)
class YearObservation:
    """One fiscal year of one concept, as the filings report it."""

    start: dt.date
    end: dt.date
    value: Decimal
    accession: str | None
    form: str | None
    filed: dt.date | None

    @property
    def reported(self) -> bool:
        """A charge of zero is not a charge.

        Filers tag a sparse concept only in the periods where the amount is
        non-zero, so an absent year and a zero year mean the same thing: the
        charge did not happen. Counting zeros would make any concept the filer
        tags consistently look like it recurs.
        """
        return self.value != 0

    def as_dict(self) -> dict[str, object]:
        return {
            "fiscal_year_end": self.end.isoformat(),
            "start": self.start.isoformat(),
            "value": dec_str(self.value),
            "reported": self.reported,
            "accession": self.accession,
            "form": self.form,
            "filed": None if self.filed is None else self.filed.isoformat(),
        }


@dataclass(frozen=True)
class RecurrenceFinding:
    """Whether one item's charge recurs, with the evidence for it."""

    item: str
    concept: str | None
    min_years: int
    window_years: int
    observations: tuple[YearObservation, ...] = ()
    note: str = ""

    @property
    def years_examined(self) -> int:
        return len(self.observations)

    @property
    def years_reported(self) -> int:
        return sum(1 for row in self.observations if row.reported)

    @property
    def recurs(self) -> bool:
        return self.years_reported >= self.min_years

    @property
    def evidence(self) -> str:
        """The finding in one sentence, for the UI and the audit trail."""
        if self.concept is None:
            return (
                self.item
                + " has no reported concept, so recurrence cannot be tested from"
                + " the filings"
            )
        if not self.observations:
            return (
                self.concept
                + " has no annual facts in the "
                + str(self.window_years)
                + " fiscal years before the test date"
            )
        years = ", ".join(
            str(row.end.year) + ": " + dec_str(row.value) for row in self.observations
        )
        verdict = "recurs" if self.recurs else "does not recur"
        return (
            self.concept
            + " is reported in "
            + str(self.years_reported)
            + " of the last "
            + str(self.years_examined)
            + " fiscal years ("
            + years
            + "), so on a threshold of "
            + str(self.min_years)
            + " of "
            + str(self.window_years)
            + " it "
            + verdict
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "item": self.item,
            "concept": self.concept,
            "recurs": self.recurs,
            "min_years": self.min_years,
            "window_years": self.window_years,
            "years_examined": self.years_examined,
            "years_reported": self.years_reported,
            "evidence": self.evidence,
            "years": [row.as_dict() for row in self.observations],
            "note": self.note,
        }


def annual_facts(
    facts: Iterable[Fact], *, basis: Basis | None = None
) -> list[Fact]:
    """Every fiscal-year fact for a concept, newest last, one per period."""
    pool = list(facts_on_basis(facts, basis)) if basis is not None else list(facts)
    years = [
        fact
        for fact in latest_by_period(pool).values()
        if fact.period_type == "duration" and fact.is_year and fact.end is not None
    ]
    years.sort(key=lambda fact: fact.end or dt.date.min)
    return years


def examine(
    item: str,
    concept: str | None,
    facts: Sequence[Fact],
    test_date: dt.date,
    *,
    min_years: int = DEFAULT_MIN_YEARS,
    window_years: int = DEFAULT_WINDOW_YEARS,
    basis: Basis | None = None,
) -> RecurrenceFinding:
    """Test whether ``item``'s charge recurs, and show the working.

    Only fiscal years **ending on or before the test date** count: a run is a
    statement about what was knowable at that date, and a later year's filing
    would make the same run produce different results as time passed.
    """
    if concept is None:
        return RecurrenceFinding(
            item=item,
            concept=None,
            min_years=min_years,
            window_years=window_years,
            note="no reported concept to test",
        )

    eligible = [
        fact
        for fact in annual_facts(facts, basis=basis)
        if fact.end is not None and fact.end <= test_date
    ]
    window = eligible[-window_years:]
    observations = tuple(
        YearObservation(
            start=fact.start or fact.end,  # type: ignore[arg-type]
            end=fact.end,  # type: ignore[arg-type]
            value=fact.value,
            accession=fact.accession,
            form=fact.form,
            filed=fact.filed,
        )
        for fact in window
    )
    return RecurrenceFinding(
        item=item,
        concept=concept,
        min_years=min_years,
        window_years=window_years,
        observations=observations,
    )


def examine_items(
    *,
    items: Mapping[str, str | None],
    facts_by_concept: Mapping[str, list[Fact]],
    test_date: dt.date,
    min_years: int = DEFAULT_MIN_YEARS,
    window_years: int = DEFAULT_WINDOW_YEARS,
    basis: Basis | None = None,
) -> dict[str, RecurrenceFinding]:
    """Test every item in ``items`` (item -> concept, or ``None``)."""
    findings: dict[str, RecurrenceFinding] = {}
    for item, concept in sorted(items.items()):
        findings[item] = examine(
            item,
            concept,
            facts_by_concept.get(concept or "", []),
            test_date,
            min_years=min_years,
            window_years=window_years,
            basis=basis,
        )
    return findings


def recurring_items(findings: Mapping[str, RecurrenceFinding]) -> set[str]:
    """The items whose charges recur, for the scenario engine."""
    return {item for item, finding in findings.items() if finding.recurs}
