"""Find the parts of an agreement the compiler needs, without an LLM.

Locating sections is a parsing problem, not a reasoning problem: the structure
is announced by the document itself in headings and in the ``"Term" means``
pattern. Doing it with regular expressions keeps it free, instant, and
traceable to a character offset, and it means the LLM is only ever sent the few
thousand characters that matter.

When a layout defeats these patterns the fallback is a human pasting the
clause, never a second model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``"Consolidated EBITDA" means`` and its variants. The normaliser has already
#: turned typographic quotes into straight ones.
#:
#: Two things here are not obvious, and both came from real agreements that the
#: first version of this pattern read as having no definitions at all:
#:
#: * **The verb may be a colon.** One house style writes ``"Consolidated
#:   EBITDA": with respect to any Person for any period, ...`` rather than
#:   ``means``. A colon is only accepted when a lower-case word follows it, so
#:   ``"Borrower": LANTHEUS MEDICAL IMAGING, INC.`` and a quoted phrase that
#:   merely ends a sentence do not masquerade as definitions.
#: * **The term may contain a newline.** Filers wrap the headword across a line
#:   break mid-term, so ``"Consolidated\nEBITDA"`` is one term written over two
#:   lines. :func:`_clean_term` collapses the whitespace, so the term is
#:   indexed under its single-line name.
#:
#: See docs/evaluation/generalisation.md for what each change was found on.
DEFINITION_RE = re.compile(
    r'"(?P<term>[A-Z][^"]{1,120}?)"\s*'
    r'(?:(?P<verb>means|shall mean|has the meaning)|:\s+(?=[a-z]))',
)

#: Article and section headings, used to bound a search.
ARTICLE_RE = re.compile(r"^\s*ARTICLE\s+([IVXLC]+|\d+)\b.*$", re.I | re.M)
SECTION_RE = re.compile(r"^\s*(?:SECTION\s+)?(\d+\.\d+)\s*\.?\s*(?P<title>[^\n]{0,120})$", re.M)

#: Headings that introduce the financial maintenance covenants.
FINANCIAL_COVENANT_HEADINGS = (
    "Financial Covenants",
    "Financial Covenant",
    "Certain Financial Covenants",
    "Financial Condition Covenants",
    "Financial Performance Covenants",
)

#: Phrases a maintenance covenant is stated with.
COVENANT_SENTENCE_RE = re.compile(
    r"(?:will not permit|shall not permit|shall not allow|will not allow|Permit)\s+"
    r"(?:the\s+)?(?P<ratio>[A-Z][A-Za-z ]{0,60}Ratio)",
)


@dataclass(frozen=True)
class Located:
    """A region of the agreement, with its offsets."""

    label: str
    start: int
    end: int
    text: str

    @property
    def length(self) -> int:
        return self.end - self.start


class LocationError(LookupError):
    """A section could not be located; the analyst pastes the clause instead."""


def definition_index(text: str) -> dict[str, tuple[int, int]]:
    """Every defined term in the agreement, mapped to the span of its body.

    A definition runs from its own quoted term to the start of the next one,
    which is how these documents are laid out and what makes the boundary
    computable rather than guessed.
    """
    matches = list(DEFINITION_RE.finditer(text))
    index: dict[str, tuple[int, int]] = {}
    for position, match in enumerate(matches):
        term = _clean_term(match.group("term"))
        if not term:
            continue
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        # A term defined twice (once in the index of defined terms, once in the
        # article itself) keeps its longest body, which is the real definition.
        existing = index.get(term)
        if existing is None or (end - start) > (existing[1] - existing[0]):
            index[term] = (start, end)
    return index


def _clean_term(raw: str) -> str:
    term = re.sub(r"\s+", " ", raw).strip()
    if len(term) < 3 or len(term) > 120:
        return ""
    if not re.match(r"^[A-Z0-9]", term):
        return ""
    return term


def find_definition(text: str, term: str) -> Located:
    """The definition of ``term``, or raise :class:`LocationError`."""
    index = definition_index(text)
    found = index.get(term)
    if found is None:
        for candidate, span in index.items():
            if candidate.lower() == term.lower():
                found = span
                break
    if found is None:
        raise LocationError("no definition found for " + repr(term))
    start, end = found
    return Located(label=term, start=start, end=end, text=text[start:end])


def locate_definitions_article(text: str) -> Located:
    """The article that holds the defined terms."""
    matches = list(DEFINITION_RE.finditer(text))
    if not matches:
        raise LocationError("the agreement has no 'Term means' definitions")
    # Skip the table of contents: the real article is where definitions are
    # densest, so anchor on the longest run of consecutive definitions.
    start = matches[0].start()
    best_start, best_count = start, 0
    window: list[int] = []
    for match in matches:
        window.append(match.start())
        while window and match.start() - window[0] > 400_000:
            window.pop(0)
        if len(window) > best_count:
            best_count = len(window)
            best_start = window[0]
    end = matches[-1].end()
    return Located(label="definitions", start=best_start, end=end, text=text[best_start:end])


def locate_financial_covenants(text: str, *, window: int = 12_000) -> Located:
    """The section stating the financial maintenance covenants.

    Agreements repeat the heading in the table of contents, so the heading is
    only accepted where a covenant sentence follows it.
    """
    best: Located | None = None
    for heading in FINANCIAL_COVENANT_HEADINGS:
        for match in re.finditer(re.escape(heading), text):
            start = match.start()
            chunk = text[start : start + window]
            if not COVENANT_SENTENCE_RE.search(chunk):
                continue
            end = _covenant_section_end(text, start, window)
            candidate = Located(
                label="financial_covenants", start=start, end=end, text=text[start:end]
            )
            if best is None or candidate.length > best.length:
                best = candidate
        if best is not None:
            return best
    raise LocationError("the financial covenant section could not be located")


def _covenant_section_end(text: str, start: int, window: int) -> int:
    """End the section at the next numbered section heading after the start."""
    body = text[start : start + window]
    headings = [
        match
        for match in SECTION_RE.finditer(body)
        if match.start() > 200 and not match.group("title").strip().startswith("Financial")
    ]
    if headings:
        return start + headings[0].start()
    return min(len(text), start + window)


def covenant_mentions(text: str) -> list[tuple[str, int]]:
    """Each ratio a maintenance covenant sentence names, with its offset."""
    found: list[tuple[str, int]] = []
    for match in COVENANT_SENTENCE_RE.finditer(text):
        ratio = re.sub(r"\s+", " ", match.group("ratio")).strip()
        found.append((ratio, match.start()))
    return found


def locate_ebitda_definition(text: str) -> Located:
    """The covenant EBITDA definition, whatever the agreement calls it."""
    for term in (
        "Consolidated EBITDA",
        "EBITDA",
        "Adjusted EBITDA",
        "Consolidated Adjusted EBITDA",
        "Adjusted Consolidated EBITDA",
    ):
        try:
            return find_definition(text, term)
        except LocationError:
            continue
    raise LocationError("no EBITDA definition found")
