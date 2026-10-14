"""Screen candidate credit agreements against the formula language.

Adding a golden deal is expensive - a hand-written formula, an independent
verification script, a hand calculation - so candidates are screened first,
mechanically, against the things that actually disqualify an agreement:

* the deterministic locator cannot find the EBITDA definition or the financial
  covenant section (a layout problem, recorded rather than special-cased);
* there is no maintenance covenant, only incurrence tests;
* there is no capped add-back basket, so the cap engine is never exercised;
* the definition leans on constructs the formula language cannot express.

Nothing here decides whether a deal is suitable. It prints what the locator
found and what the clause text contains, so the reading that follows is done
with the evidence in front of it.

Run with::

    python -m scripts.screen_candidates
    python -m scripts.screen_candidates --url https://www.sec.gov/Archives/...
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

from backend.agreement.fetch import fetch_agreement
from backend.agreement.locate import (
    LocationError,
    covenant_mentions,
    locate_ebitda_definition,
    locate_financial_covenants,
)
from backend.edgar.client import EdgarClient, EdgarError

#: Candidates found through EDGAR full-text search, by the Phase 2 criteria:
#: an Exhibit 10.x credit agreement with a maintenance leverage covenant and a
#: capped add-back basket.
CANDIDATES: list[tuple[str, str, str]] = [
    (
        "Forward Air",
        "0000912728",
        "https://www.sec.gov/Archives/edgar/data/912728/000162828025000462/"
        "ex101amendment3tocredita.htm",
    ),
    (
        "Lantheus Holdings",
        "0001521036",
        "https://www.sec.gov/Archives/edgar/data/1521036/000119312524284219/"
        "d922033dex101.htm",
    ),
    (
        "Mercury Systems",
        "0001049521",
        "https://www.sec.gov/Archives/edgar/data/1049521/000104952124000027/"
        "a2024q4exhibit101.htm",
    ),
    (
        "American Axle",
        "0000820081",
        "https://www.sec.gov/Archives/edgar/data/820081/000110465925016568/"
        "tm257070d2_ex10-1.htm",
    ),
    (
        "Superior Group of Companies",
        "0000095574",
        "https://www.sec.gov/Archives/edgar/data/95574/000143774925007026/ex_787509.htm",
    ),
    (
        "Lifetime Brands",
        "0000874396",
        "https://www.sec.gov/Archives/edgar/data/874396/000162828023039077/exhibit101.htm",
    ),
    (
        "CACI International",
        "0000016058",
        "https://www.sec.gov/Archives/edgar/data/16058/000162828025054481/secondar1.htm",
    ),
]

#: Phrases that signal a maintenance covenant rather than an incurrence test.
MAINTENANCE_RE = re.compile(
    r"(?:will not permit|shall not permit)[^.]{0,200}?"
    r"(?:as (?:at|of) the last day of any (?:fiscal quarter|period)|"
    r"for any period of four consecutive fiscal quarters|"
    r"as (?:at|of) the end of any fiscal quarter)",
    re.I | re.S,
)

#: A capped add-back basket: a cap stated as a percentage of EBITDA or as a
#: dollar amount, inside the definition.
CAP_PCT_RE = re.compile(
    r"shall not exceed[^.]{0,160}?(\d{1,2}(?:\.\d+)?)\s*%[^.]{0,80}?(?:Consolidated )?EBITDA",
    re.I | re.S,
)
CAP_FIXED_RE = re.compile(r"shall not exceed\s*\$\s?([\d,]{7,})", re.I)

#: Constructs the formula language does not express. Their presence is not
#: disqualifying on its own - the reviewer can exclude a clause with a note -
#: but a definition built mostly from them is not worth hand-writing.
UNSUPPORTED_PATTERNS = {
    "pro forma cost savings": re.compile(
        r"(?:cost sav|synerg)[a-z]*", re.I
    ),
    "run-rate basis": re.compile(r"run[- ]rate", re.I),
    "cross-period claw-back": re.compile(
        r"cash payment[s]? (?:made )?(?:with respect to|in respect of)[^.]{0,120}"
        r"non-cash charge",
        re.I | re.S,
    ),
    "acquisition holiday": re.compile(
        r"(?:holiday|step[- ]up)[^.]{0,120}(?:Material Acquisition|Qualified Acquisition)",
        re.I | re.S,
    ),
    "mark-to-market pension": re.compile(r"mark[- ]to[- ]market[^.]{0,60}pension", re.I),
}

#: Enumerated clause markers inside a definition: (i), (ii), (a), (b)...
CLAUSE_RE = re.compile(r"\(\s*(?:[ivxlc]{1,6}|[a-z])\s*\)")


@dataclass
class Screening:
    """What the locator and the clause text say about one candidate."""

    name: str
    url: str
    chars: int = 0
    source_hash: str = ""
    ebitda_term: str | None = None
    ebitda_chars: int = 0
    ebitda_clauses: int = 0
    covenant_section: bool = False
    covenant_ratios: list[str] = field(default_factory=list)
    maintenance: bool = False
    caps_pct: list[str] = field(default_factory=list)
    caps_fixed: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    locator_failures: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def qualifies(self) -> bool:
        return (
            self.error is None
            and self.ebitda_term is not None
            and self.covenant_section
            and self.maintenance
            and bool(self.caps_pct or self.caps_fixed)
        )

    def report(self) -> str:
        lines = ["=" * 88, self.name + "  " + self.url]
        if self.error:
            lines.append("  ERROR: " + self.error)
            return "\n".join(lines)
        lines.append(
            "  text: "
            + format(self.chars, ",")
            + " chars  "
            + self.source_hash[:19]
        )
        lines.append(
            "  EBITDA definition: "
            + (self.ebitda_term or "NOT FOUND")
            + ("  (" + format(self.ebitda_chars, ",") + " chars, "
               + str(self.ebitda_clauses) + " enumerated clauses)" if self.ebitda_term else "")
        )
        lines.append(
            "  covenant section:  "
            + ("found" if self.covenant_section else "NOT FOUND")
            + "  ratios: "
            + (", ".join(self.covenant_ratios) or "none")
        )
        lines.append("  maintenance test:  " + ("yes" if self.maintenance else "NO"))
        lines.append(
            "  capped baskets:    "
            + (", ".join(self.caps_pct + self.caps_fixed) or "none")
        )
        lines.append("  unsupported:       " + (", ".join(self.unsupported) or "none detected"))
        for failure in self.locator_failures:
            lines.append("  LOCATOR: " + failure)
        lines.append("  verdict: " + ("QUALIFIES" if self.qualifies else "does not qualify"))
        return "\n".join(lines)


def screen(name: str, url: str, *, client: EdgarClient | None = None) -> Screening:
    result = Screening(name=name, url=url)
    client = client or EdgarClient()
    try:
        agreement = fetch_agreement(url, client=client)
    except (EdgarError, OSError) as exc:
        result.error = str(exc)[:200]
        return result

    text = agreement.text
    result.chars = len(text)
    result.source_hash = agreement.source_hash

    try:
        definition = locate_ebitda_definition(text)
        result.ebitda_term = definition.label
        result.ebitda_chars = definition.length
        body = definition.text
        result.ebitda_clauses = len(set(CLAUSE_RE.findall(body)))
    except LocationError as exc:
        result.locator_failures.append("locate_ebitda_definition: " + str(exc))
        body = ""

    try:
        section = locate_financial_covenants(text)
        result.covenant_section = True
        result.covenant_ratios = sorted(
            {ratio for ratio, _ in covenant_mentions(section.text)}
        )
    except LocationError as exc:
        result.locator_failures.append("locate_financial_covenants: " + str(exc))

    result.maintenance = bool(MAINTENANCE_RE.search(text))

    search_in = body or text
    result.caps_pct = sorted(
        {match.group(1) + "% of EBITDA" for match in CAP_PCT_RE.finditer(search_in)}
    )
    result.caps_fixed = sorted(
        {"$" + match.group(1) for match in CAP_FIXED_RE.finditer(search_in)}
    )[:4]
    result.unsupported = sorted(
        name for name, pattern in UNSUPPORTED_PATTERNS.items() if pattern.search(search_in)
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", default=None)
    parser.add_argument("--name", action="append", default=None)
    args = parser.parse_args()

    if args.url:
        names = args.name or ["candidate " + str(i + 1) for i in range(len(args.url))]
        pairs = list(zip(names, args.url))
    else:
        pairs = [(name, url) for name, _cik, url in CANDIDATES]

    client = EdgarClient()
    qualifying: list[str] = []
    for name, url in pairs:
        result = screen(name, url, client=client)
        print(result.report())
        if result.qualifies:
            qualifying.append(name)
    print("=" * 88)
    print("qualifying on the mechanical criteria:", ", ".join(qualifying) or "none")
    print("(the clause text still has to be read before any of these is chosen)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
