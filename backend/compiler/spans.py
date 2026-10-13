"""Span verification.

Every span in a drafted formula is checked against the agreement text before
the draft is shown to anyone: the text at ``[start:end]`` has to equal the
quote after whitespace normalisation, or the draft is rejected.

This proves the cited text exists. It does **not** prove the clause was
interpreted correctly - a real span attached to the wrong item passes this
check and is caught only by component-level human review, which is why the
compiler's semantic accuracy is measured separately against hand-written
formulas rather than assumed from span fidelity.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agreement.normalise import normalise_for_comparison
from backend.evaluator.schema import Covenant, EbitdaFormula, FormulaVersion, Span


class SpanVerificationError(ValueError):
    """A drafted span does not match the agreement text."""

    def __init__(self, failures: list["SpanFailure"]) -> None:
        self.failures = failures
        summary = "; ".join(failure.message for failure in failures[:5])
        if len(failures) > 5:
            summary += " (and " + str(len(failures) - 5) + " more)"
        super().__init__("span verification failed: " + summary)


@dataclass(frozen=True)
class SpanFailure:
    """One span that could not be verified."""

    target: str
    quote: str
    start: int
    end: int
    found: str
    reason: str

    @property
    def message(self) -> str:
        return self.target + ": " + self.reason

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "found": self.found,
            "reason": self.reason,
        }


def verify_span(span: Span, source: str, *, target: str) -> SpanFailure | None:
    """Check one span against ``source``. ``None`` means it verified."""
    if span.end > len(source):
        return SpanFailure(
            target=target,
            quote=span.quote,
            start=span.start,
            end=span.end,
            found="",
            reason="span ends past the end of the agreement text",
        )
    found = source[span.start : span.end]
    if normalise_for_comparison(found) == normalise_for_comparison(span.quote):
        return None
    relocated = relocate(span, source)
    reason = "the text at the cited offsets is not the quoted text"
    if relocated is None:
        reason = "the quoted text does not appear in the agreement at all"
    else:
        reason += " (the quote does appear at offset " + str(relocated) + ")"
    return SpanFailure(
        target=target,
        quote=span.quote,
        start=span.start,
        end=span.end,
        found=found[:200],
        reason=reason,
    )


def relocate(span: Span, source: str) -> int | None:
    """Where the quote really starts, if it appears in the text at all.

    Used to tell a model that drifted its offsets from one that invented the
    quote. A relocated span is still a failure: Headroom does not silently move
    a citation, because the offsets are what a reviewer reads the clause at.
    """
    direct = source.find(span.quote)
    if direct >= 0:
        return direct
    wanted = normalise_for_comparison(span.quote)
    if not wanted:
        return None
    head = wanted.split(" ")[0]
    probe = 0
    while True:
        probe = source.find(head, probe)
        if probe < 0:
            return None
        window = source[probe : probe + len(span.quote) + 200]
        if normalise_for_comparison(window).startswith(wanted):
            return probe
        probe += 1


def verify_formula(formula: EbitdaFormula, source: str) -> list[SpanFailure]:
    """Every span in an EBITDA formula."""
    failures: list[SpanFailure] = []
    failure = verify_span(formula.base.span, source, target="base:" + formula.base.item)
    if failure:
        failures.append(failure)
    for component in formula.components:
        failure = verify_span(component.span, source, target=component.key)
        if failure:
            failures.append(failure)
    for name, pool in sorted(formula.cap_pools.items()):
        if pool.span is not None:
            failure = verify_span(pool.span, source, target="cap_pool:" + name)
            if failure:
                failures.append(failure)
    return failures


def verify_covenant(covenant: Covenant, source: str) -> list[SpanFailure]:
    failures: list[SpanFailure] = []
    failure = verify_span(covenant.span, source, target="covenant:" + covenant.id)
    if failure:
        failures.append(failure)
    side = covenant.items_side
    if side.span is not None:
        failure = verify_span(side.span, source, target="covenant:" + covenant.id + ":items")
        if failure:
            failures.append(failure)
    if side.net_of_cash is not None and side.net_of_cash.span is not None:
        failure = verify_span(
            side.net_of_cash.span, source, target="covenant:" + covenant.id + ":net_of_cash"
        )
        if failure:
            failures.append(failure)
    return failures


def verify_version(version: FormulaVersion, source: str) -> list[SpanFailure]:
    """Every span in a formula version, including its definitions graph."""
    failures = verify_formula(version.ebitda, source)
    for covenant in version.covenants:
        failures.extend(verify_covenant(covenant, source))
    for term, node in sorted(version.definitions.items()):
        if node.span is not None:
            failure = verify_span(node.span, source, target="definition:" + term)
            if failure:
                failures.append(failure)
    return failures


def require_verified(version: FormulaVersion, source: str) -> None:
    """Raise unless every span in ``version`` matches ``source``."""
    failures = verify_version(version, source)
    if failures:
        raise SpanVerificationError(failures)


def locate(source: str, quote: str, *, start: int = 0) -> Span:
    """Build a verified span for ``quote``, for hand-written formulas.

    Golden formulas are written by hand against the real agreement, so they
    need the same offsets the compiler produces rather than invented ones.
    """
    index = source.find(quote, start)
    if index < 0:
        raise ValueError("quote not found in the agreement text: " + quote[:80])
    return Span(start=index, end=index + len(quote), quote=quote)
