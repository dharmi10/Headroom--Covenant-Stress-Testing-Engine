"""Aggregate several compiler scorecards into one measurement.

One compile is an anecdote. The question a reviewer actually asks is "how often
does it get a clause right, and does it give the same answer twice", so this
module takes N scorecards over M agreements and reports both: accuracy per
field, and run-to-run stability per clause.

Nothing here asserts a threshold. A compiler metric the test suite enforces is
a metric nobody will ever let fall, which is not the same as a metric that is
true.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.compiler.score import Scorecard

#: The per-component fields a draft is scored on. Thresholds live on the
#: covenant, not the component, so they are aggregated separately.
COMPONENT_FIELDS = ("item", "sign", "category", "cap_rule")
COVENANT_FIELDS = ("type", "items", "thresholds", "net_of_cash")


@dataclass
class FieldTally:
    """How often one field was right, across every run of every deal."""

    name: str
    correct: int = 0
    total: int = 0

    @property
    def accuracy(self) -> float | None:
        return None if self.total == 0 else self.correct / self.total

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.name,
            "correct": self.correct,
            "total": self.total,
            "accuracy": self.accuracy,
        }


@dataclass
class ClauseStability:
    """What a single clause was drafted as, run after run.

    A clause that is wrong the same way every time is a prompt or a vocabulary
    problem. A clause that is right four times out of five is a sampling
    problem, and the two need different fixes, so they are reported apart.
    """

    deal_id: str
    clause: str
    runs: int = 0
    correct_runs: int = 0
    #: One entry per distinct answer the model gave, with how often it gave it.
    answers: dict[str, int] = field(default_factory=dict)

    @property
    def stable(self) -> bool:
        return len(self.answers) <= 1

    @property
    def always_correct(self) -> bool:
        return self.runs > 0 and self.correct_runs == self.runs

    def as_dict(self) -> dict[str, Any]:
        return {
            "deal_id": self.deal_id,
            "clause": self.clause,
            "runs": self.runs,
            "correct_runs": self.correct_runs,
            "stable": self.stable,
            "answers": dict(sorted(self.answers.items())),
        }


@dataclass
class Measurement:
    """Every scorecard, reduced to the numbers a reader can check."""

    model: str
    prompt_version: str
    measured_at: str
    deals: list[str] = field(default_factory=list)
    runs_per_deal: dict[str, int] = field(default_factory=dict)
    component_fields: dict[str, FieldTally] = field(default_factory=dict)
    covenant_fields: dict[str, FieldTally] = field(default_factory=dict)
    components_whole: FieldTally = field(
        default_factory=lambda: FieldTally("component_fully_correct")
    )
    covenants_whole: FieldTally = field(
        default_factory=lambda: FieldTally("covenant_fully_correct")
    )
    missing_clauses: dict[str, int] = field(default_factory=dict)
    extra_clauses: dict[str, int] = field(default_factory=dict)
    clauses: dict[tuple[str, str], ClauseStability] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[int] = field(default_factory=list)
    retries: list[dict[str, Any]] = field(default_factory=list)

    # -- shape -------------------------------------------------------------

    @property
    def n_agreements(self) -> int:
        return len(self.deals)

    @property
    def n_component_observations(self) -> int:
        return self.components_whole.total

    @property
    def n_clauses(self) -> int:
        """Distinct clauses in the golden formulas, not observations."""
        return len({key for key in self.clauses})

    @property
    def unstable_clauses(self) -> list[ClauseStability]:
        return [row for row in self.clauses.values() if not row.stable]

    @property
    def mean_attempts(self) -> float | None:
        return None if not self.attempts else statistics.fmean(self.attempts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "measured_at": self.measured_at,
            "n_agreements": self.n_agreements,
            "deals": self.deals,
            "runs_per_deal": self.runs_per_deal,
            "n_distinct_clauses": self.n_clauses,
            "n_component_observations": self.n_component_observations,
            "component_fields": [
                self.component_fields[name].as_dict()
                for name in COMPONENT_FIELDS
                if name in self.component_fields
            ],
            "covenant_fields": [
                self.covenant_fields[name].as_dict()
                for name in COVENANT_FIELDS
                if name in self.covenant_fields
            ],
            "component_fully_correct": self.components_whole.as_dict(),
            "covenant_fully_correct": self.covenants_whole.as_dict(),
            "missing_clauses": dict(sorted(self.missing_clauses.items())),
            "extra_clauses": dict(sorted(self.extra_clauses.items())),
            "unstable_clauses": [row.as_dict() for row in self.unstable_clauses],
            "clause_stability": [
                row.as_dict() for row in sorted(self.clauses.values(), key=_clause_sort)
            ],
            "failures": self.failures,
            "mean_attempts_per_call": self.mean_attempts,
            "retries": self.retries,
        }


def _clause_sort(row: ClauseStability) -> tuple:
    return (row.deal_id, row.correct_runs, row.clause)


def _tally(table: dict[str, FieldTally], name: str, ok: bool) -> None:
    entry = table.setdefault(name, FieldTally(name))
    entry.total += 1
    entry.correct += 1 if ok else 0


def _answer_key(drafted: dict[str, Any]) -> str:
    """A stable string for one drafted answer, for counting repeats."""
    parts = []
    for name in COMPONENT_FIELDS:
        value = drafted.get(name)
        parts.append(name + "=" + ("-" if value is None else str(value)))
    return " ".join(parts)


def aggregate(
    cards: Iterable[tuple[str, int, Scorecard]],
    *,
    model: str,
    prompt_version: str,
    calls: Iterable[dict[str, Any]] = (),
    measured_at: str | None = None,
) -> Measurement:
    """Reduce ``(deal_id, run_index, scorecard)`` triples to one measurement."""
    measurement = Measurement(
        model=model,
        prompt_version=prompt_version,
        measured_at=measured_at
        or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    )

    for deal_id, run_index, card in cards:
        if deal_id not in measurement.deals:
            measurement.deals.append(deal_id)
        measurement.runs_per_deal[deal_id] = max(
            measurement.runs_per_deal.get(deal_id, 0), run_index + 1
        )

        for row in card.components:
            measurement.components_whole.total += 1
            measurement.components_whole.correct += 1 if row.correct else 0
            for name in COMPONENT_FIELDS:
                if name in row.matched:
                    _tally(measurement.component_fields, name, row.matched[name])

            key = (deal_id, row.clause)
            stability = measurement.clauses.setdefault(
                key, ClauseStability(deal_id=deal_id, clause=row.clause)
            )
            stability.runs += 1
            stability.correct_runs += 1 if row.correct else 0
            answer = _answer_key(row.drafted)
            stability.answers[answer] = stability.answers.get(answer, 0) + 1

            if not row.correct:
                measurement.failures.append(
                    {
                        "deal_id": deal_id,
                        "run": run_index + 1,
                        "clause": row.clause,
                        "wrong_fields": row.wrong_fields(),
                        "golden": row.golden,
                        "drafted": row.drafted,
                    }
                )

        for clause in card.missing_clauses:
            name = deal_id + " " + clause
            measurement.missing_clauses[name] = measurement.missing_clauses.get(name, 0) + 1
            # A clause the draft never accounted for is counted as a wrong
            # component, not left out of the denominator.
            measurement.components_whole.total += 1
            key = (deal_id, clause)
            stability = measurement.clauses.setdefault(
                key, ClauseStability(deal_id=deal_id, clause=clause)
            )
            stability.runs += 1
            stability.answers["(clause not accounted for)"] = (
                stability.answers.get("(clause not accounted for)", 0) + 1
            )

        for clause in card.extra_clauses:
            name = deal_id + " " + clause
            measurement.extra_clauses[name] = measurement.extra_clauses.get(name, 0) + 1

        for row in card.covenants:
            measurement.covenants_whole.total += 1
            measurement.covenants_whole.correct += 1 if row.correct else 0
            for name in COVENANT_FIELDS:
                if name in row.matched:
                    _tally(measurement.covenant_fields, name, row.matched[name])
            if not row.correct:
                measurement.failures.append(
                    {
                        "deal_id": deal_id,
                        "run": run_index + 1,
                        "clause": "covenant:" + row.clause,
                        "wrong_fields": row.wrong_fields(),
                        "golden": row.golden,
                        "drafted": row.drafted,
                    }
                )

    for call in calls:
        attempts = call.get("attempts")
        if isinstance(attempts, int):
            measurement.attempts.append(attempts)
        for index, errors in enumerate(call.get("errors", []) or [], start=1):
            if errors:
                measurement.retries.append(
                    {"target": call.get("target"), "attempt": index, "errors": errors}
                )

    return measurement


def _pct(value: float | None) -> str:
    return "n/a" if value is None else format(value * 100, ".1f") + "%"


def markdown_report(measurement: Measurement, *, note: str = "") -> str:
    """The measurement as ``docs/evaluation/compiler.md``."""
    lines: list[str] = []
    lines.append("# Compiler accuracy")
    lines.append("")
    lines.append(
        "The LLM does exactly one job in Headroom: turn clause text into a typed"
    )
    lines.append(
        "formula. Span verification proves the citation exists; it says nothing about"
    )
    lines.append(
        "whether the clause was *read* correctly. This file is the answer to that"
    )
    lines.append("second question, measured rather than asserted.")
    lines.append("")
    lines.append("| | |")
    lines.append("| --- | --- |")
    lines.append("| Model | `" + measurement.model + "` |")
    lines.append("| Prompt version | `" + measurement.prompt_version + "` |")
    lines.append("| Measured | " + measurement.measured_at + " |")
    lines.append("| Agreements | " + str(measurement.n_agreements) + " |")
    lines.append(
        "| Runs | "
        + ", ".join(
            deal + ": " + str(measurement.runs_per_deal[deal]) for deal in measurement.deals
        )
        + " |"
    )
    lines.append("| Distinct clauses | " + str(measurement.n_clauses) + " |")
    lines.append(
        "| Component observations | " + str(measurement.n_component_observations) + " |"
    )
    lines.append("")
    lines.append("> **This is a tiny sample.** " + str(measurement.n_agreements) + " agreement(s)")
    lines.append(
        "> and "
        + str(measurement.n_clauses)
        + " distinct clauses is an anecdote with error bars wide enough to drive a"
    )
    lines.append(
        "> truck through. It is enough to catch a compiler that is badly wrong and"
    )
    lines.append(
        "> nowhere near enough to publish an accuracy figure. Every number below"
    )
    lines.append("> should be read as \"what happened on these clauses\", not as a rate.")
    if note:
        lines.append("")
        lines.append(note)
    lines.append("")

    lines.append("## Per-field accuracy")
    lines.append("")
    lines.append("| Field | Correct | Observations | Accuracy |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name in COMPONENT_FIELDS:
        tally = measurement.component_fields.get(name)
        if tally is None:
            continue
        lines.append(
            "| `"
            + name
            + "` | "
            + str(tally.correct)
            + " | "
            + str(tally.total)
            + " | "
            + _pct(tally.accuracy)
            + " |"
        )
    whole = measurement.components_whole
    lines.append(
        "| **every field on the component** | "
        + str(whole.correct)
        + " | "
        + str(whole.total)
        + " | "
        + _pct(whole.accuracy)
        + " |"
    )
    lines.append("")
    lines.append("Covenants are scored on their own fields, thresholds included:")
    lines.append("")
    lines.append("| Field | Correct | Observations | Accuracy |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name in COVENANT_FIELDS:
        tally = measurement.covenant_fields.get(name)
        if tally is None:
            continue
        lines.append(
            "| `"
            + name
            + "` | "
            + str(tally.correct)
            + " | "
            + str(tally.total)
            + " | "
            + _pct(tally.accuracy)
            + " |"
        )
    cov = measurement.covenants_whole
    lines.append(
        "| **every field on the covenant** | "
        + str(cov.correct)
        + " | "
        + str(cov.total)
        + " | "
        + _pct(cov.accuracy)
        + " |"
    )
    lines.append("")

    lines.append("## Run-to-run stability")
    lines.append("")
    lines.append(
        "Current Claude models reject the sampling parameters, so temperature 0 is not"
    )
    lines.append(
        "available (see `docs/decisions.md`). Stability is therefore measured rather"
    )
    lines.append("than assumed: the same agreement is compiled several times and the")
    lines.append("answers compared clause by clause.")
    lines.append("")
    unstable = measurement.unstable_clauses
    if not measurement.clauses:
        lines.append("No runs recorded.")
    elif not unstable:
        lines.append(
            "Every clause was drafted identically in every run ("
            + str(measurement.n_clauses)
            + " clauses)."
        )
    else:
        lines.append(
            str(len(unstable))
            + " of "
            + str(measurement.n_clauses)
            + " clauses were not drafted identically in every run:"
        )
        lines.append("")
        lines.append("| Deal | Clause | Correct runs | Distinct answers |")
        lines.append("| --- | --- | ---: | --- |")
        for row in sorted(unstable, key=_clause_sort):
            answers = "; ".join(
                key + " x" + str(count) for key, count in sorted(row.answers.items())
            )
            lines.append(
                "| "
                + row.deal_id
                + " | `"
                + row.clause
                + "` | "
                + str(row.correct_runs)
                + "/"
                + str(row.runs)
                + " | "
                + answers
                + " |"
            )
    lines.append("")

    lines.append("## Every wrong component")
    lines.append("")
    if not measurement.failures:
        lines.append("None. Every clause matched the hand-written formula on every field.")
    else:
        lines.append("| Deal | Run | Clause | Wrong fields | Golden | Drafted |")
        lines.append("| --- | ---: | --- | --- | --- | --- |")
        for row in measurement.failures:
            wrong = ", ".join("`" + name + "`" for name in row["wrong_fields"])
            golden = "; ".join(
                name + "=" + str(row["golden"].get(name)) for name in row["wrong_fields"]
            )
            drafted = "; ".join(
                name + "=" + str(row["drafted"].get(name)) for name in row["wrong_fields"]
            )
            lines.append(
                "| "
                + row["deal_id"]
                + " | "
                + str(row["run"])
                + " | `"
                + row["clause"]
                + "` | "
                + wrong
                + " | "
                + golden
                + " | "
                + drafted
                + " |"
            )
    lines.append("")

    if measurement.missing_clauses or measurement.extra_clauses:
        lines.append("## Clauses missed and invented")
        lines.append("")
        lines.append("| Clause | Times | Kind |")
        lines.append("| --- | ---: | --- |")
        for name, count in sorted(measurement.missing_clauses.items()):
            lines.append("| `" + name + "` | " + str(count) + " | not accounted for |")
        for name, count in sorted(measurement.extra_clauses.items()):
            lines.append("| `" + name + "` | " + str(count) + " | invented |")
        lines.append("")

    lines.append("## Retries")
    lines.append("")
    mean = measurement.mean_attempts
    lines.append(
        "Mean attempts per call: "
        + ("n/a" if mean is None else format(mean, ".2f"))
        + " (the compiler allows one retry, carrying the exact validation errors)."
    )
    if measurement.retries:
        lines.append("")
        lines.append("| Target | Attempt | Rejected because |")
        lines.append("| --- | ---: | --- |")
        for row in measurement.retries:
            lines.append(
                "| "
                + str(row["target"])
                + " | "
                + str(row["attempt"])
                + " | "
                + "; ".join(row["errors"])[:300]
                + " |"
            )
    lines.append("")
    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("make measure              # one run per golden deal")
    lines.append("make measure RUNS=5       # five runs per golden deal, with stability")
    lines.append("```")
    lines.append("")
    lines.append(
        "Needs Anthropic credentials. Every compile is saved to"
    )
    lines.append(
        "`data/transcripts/<deal>.run<N>.json` so a scorecard can be re-derived"
    )
    lines.append("without calling the model again (`--replay`).")
    lines.append("")
    return "\n".join(lines)
