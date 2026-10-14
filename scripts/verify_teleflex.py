"""Independent recalculation of the Teleflex golden case.

This script is deliberately a second implementation. It imports nothing from
``backend`` - no evaluator, no TTM builder, no mapping code, no schema - and
uses only the standard library. It re-reads the raw companyfacts JSON, picks
the facts itself, derives the fiscal fourth quarter explicitly as FY minus the
nine-month year to date, and prints every intermediate number so each one can
be checked against the filing it came from.

A quarter may only be derived from two year-to-date facts on the same
reporting basis. Two figures for overlapping periods are not two views of the
same running total if the company restated in between, and subtracting them
produces a number that was never reported by anybody. The basis is worked out
here from the filings themselves, independently of the application: a
year-to-date series is cut at the first filing that reported one of its periods
with a different value, and a window is built from one side of that cut only.

The whole calculation then runs on a single basis, chosen the same way the
application chooses it - the restated figures if they can produce a complete
window, the figures as originally reported if they cannot - so that the two
implementations are comparable on the figures they actually used.

Run with::

    python scripts/verify_teleflex.py

``--basis as_restated`` or ``--basis as_originally_reported`` forces one basis
instead, which is how the rejected mixed-basis window can be inspected.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import urllib.request
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 50

CIK = "0000096943"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK" + CIK + ".json"
CACHE_DIR = Path("data/cache")
USER_AGENT = "Headroom verification (dharmi.chauhan10@gmail.com)"

TEST_DATE = dt.date(2025, 6, 29)
LEVERAGE_CAP = Decimal("4.50")
COVERAGE_FLOOR = Decimal("3.50")
TIGHT_BAND = Decimal("0.15")
RESTRUCTURING_CAP_PCT = Decimal("0.05")

#: The concept each formula item is mapped to, per the golden mappings file.
#: Written out here so the mapping under test is visible, not imported.
DURATION_CONCEPTS = {
    "net_income": "NetIncomeLoss",
    "income_tax_expense": "IncomeTaxExpenseBenefit",
    "interest_expense": "InterestExpenseNonoperating",
    "depreciation_amortization": "DepreciationAndAmortization",
    "stock_based_compensation": "ShareBasedCompensation",
    "restructuring_charges": "RestructuringCharges",
}

INSTANT_CONCEPTS = {
    "long_term_debt": "LongTermDebtNoncurrent",
    "current_portion_long_term_debt": "LongTermDebtCurrent",
    "cash_and_equivalents": "CashAndCashEquivalentsAtCarryingValue",
}

#: The clause (b)(v) add-back is a hand-summed analyst value in the golden set.
#: Its rationale names these concepts, so the sum is reproduced here rather
#: than taken on trust.
IMPAIRMENT_CONCEPTS = [
    "GoodwillImpairmentLoss",
    "ImpairmentOfIntangibleAssetsExcludingGoodwill",
]

ACCEPTED_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}

def required_items() -> list[str]:
    """The four items S3 is built from."""
    return [
        "net_income",
        "income_tax_expense",
        "interest_expense",
        "depreciation_amortization",
    ]


RULE = "=" * 92
THIN = "-" * 92

findings: list[str] = []

#: Set from ``--basis`` to force one basis; ``None`` means work it out.
CHOSEN_BASIS: str | None = None


def note(line: str) -> None:
    findings.append(line)


# ---------------------------------------------------------------- fetching --


def companyfacts() -> dict:
    digest = hashlib.sha256(COMPANYFACTS_URL.encode("utf-8")).hexdigest()[:40]
    cached = CACHE_DIR / digest[:2] / (digest + ".body")
    if cached.exists():
        print("companyfacts from the disk cache:", cached)
        raw = cached.read_bytes()
    else:
        print("fetching companyfacts from", COMPANYFACTS_URL)
        request = urllib.request.Request(
            COMPANYFACTS_URL, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    print("   ", len(raw), "bytes, sha256", hashlib.sha256(raw).hexdigest()[:16])
    return json.loads(raw)


def rows_for(facts: dict, concept: str) -> list[dict]:
    body = facts.get("facts", {}).get("us-gaap", {}).get(concept)
    if body is None:
        return []
    return [
        row
        for row in body.get("units", {}).get("USD", [])
        if row.get("form") in ACCEPTED_FORMS and "val" in row
    ]


def date_of(value) -> dt.date | None:
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def candidates(rows: list[dict], start: dt.date | None, end: dt.date) -> list[dict]:
    """Every filing that reported this exact period, oldest first."""
    hits = [
        row
        for row in rows
        if date_of(row.get("end")) == end and date_of(row.get("start")) == start
    ]
    return sorted(hits, key=lambda row: (row.get("filed") or "", row.get("accn") or ""))


def value_of(row: dict) -> Decimal:
    return Decimal(str(row["val"]))


# ---------------------------------------------------------- reporting basis --

BASES = ("as_restated", "as_originally_reported")
BASIS_LABELS = {
    "as_restated": "as restated",
    "as_originally_reported": "as originally reported",
}


def boundaries_of(series: list[dict]) -> list[str]:
    """Filing dates at which a value inside one year-to-date series changed.

    A series is the set of rows sharing a start date, which is exactly the set
    a quarter may be derived within. The first filing to report one of its
    periods with a value different from that period's first published value is
    where the series splits into two bases.
    """
    by_period: dict[tuple, list[dict]] = {}
    for row in series:
        by_period.setdefault((row.get("start"), row.get("end")), []).append(row)
    cuts: set[str] = set()
    for group in by_period.values():
        ordered = sorted(group, key=lambda r: (r.get("filed") or "", r.get("accn") or ""))
        first = value_of(ordered[0])
        for later in ordered[1:]:
            if value_of(later) != first and later.get("filed"):
                cuts.add(str(later["filed"]))
    return sorted(cuts)


def rows_on_basis(rows: list[dict], basis: str) -> list[dict]:
    """Keep only the rows belonging to ``basis``, series by series.

    A series nobody restated survives whole: its one presentation is both the
    original and the current figure. A restated series is cut, and only one
    side is kept, so nothing downstream can subtract across the cut.
    """
    by_start: dict[object, list[dict]] = {}
    for row in rows:
        by_start.setdefault(row.get("start"), []).append(row)
    kept: list[dict] = []
    for series in by_start.values():
        cuts = boundaries_of(series)
        if not cuts:
            kept.extend(series)
            continue
        if basis == "as_restated":
            kept.extend(r for r in series if str(r.get("filed") or "") >= cuts[-1])
        else:
            kept.extend(r for r in series if str(r.get("filed") or "") < cuts[0])
    return kept


# ------------------------------------------------------- the four quarters --


def find_quarter_windows(facts: dict) -> list[tuple[dt.date, dt.date]]:
    rows = rows_for(facts, DURATION_CONCEPTS["net_income"])
    quarters: dict[dt.date, tuple[dt.date, dt.date]] = {}
    for row in rows:
        start, end = date_of(row.get("start")), date_of(row.get("end"))
        if start is None or end is None:
            continue
        if 80 <= (end - start).days + 1 <= 100:
            quarters[end] = (start, end)

    window: list[tuple[dt.date, dt.date]] = []
    cursor = TEST_DATE
    for _ in range(4):
        if cursor not in quarters:
            raise SystemExit("no reported quarter ends " + cursor.isoformat())
        start, end = quarters[cursor]
        window.append((start, end))
        cursor = start - dt.timedelta(days=1)
    window.reverse()

    print()
    print("Four quarters ending", TEST_DATE.isoformat())
    for start, end in window:
        print(
            "   ",
            start.isoformat(),
            "to",
            end.isoformat(),
            "(" + str((end - start).days + 1) + " days)",
        )
    span = (window[-1][1] - window[0][0]).days + 1
    print("    span:", span, "days")
    if not 350 <= span <= 380:
        raise SystemExit("the four quarters do not span a year")
    return window


# --------------------------------------------------------------- resolving --


class Resolved:
    """One quarter, resolved, with enough provenance to argue about."""

    def __init__(
        self,
        start: dt.date,
        end: dt.date,
        value: Decimal,
        origin: str,
        form: str,
        accession: str,
        basis: str,
        detail: str = "",
    ) -> None:
        self.start, self.end = start, end
        self.value = value
        self.origin = origin
        self.form = form
        self.accession = accession
        self.basis = basis  # the filing date the figure's basis comes from
        self.detail = detail


def resolve_quarter(
    rows: list[dict], start: dt.date, end: dt.date, *, basis: str
) -> Resolved | None:
    """One quarter, reported if stated, else derived from two cumulative facts.

    ``rows`` is filtered to ``basis`` first, so every figure in play sits on
    one side of any restatement. A fiscal fourth quarter can never be derived
    from a single filing - the full year is in the 10-K, the nine months are in
    the Q3 10-Q - so the derivation necessarily spans two filings, and the
    basis filter is what makes those two filings comparable.
    """
    rows = rows_on_basis(rows, basis)
    stated = candidates(rows, start, end)
    if stated:
        row = stated[-1]
        return Resolved(
            start,
            end,
            value_of(row),
            "reported",
            str(row.get("form")),
            str(row.get("accn")),
            str(row.get("filed")),
        )

    # Derive: the longest cumulative period ending here, minus the cumulative
    # period ending the day before this quarter began, sharing a start date.
    longs = [
        row
        for row in rows
        if date_of(row.get("end")) == end
        and date_of(row.get("start")) is not None
        and date_of(row.get("start")) < start
    ]
    if not longs:
        return None
    long_starts = {date_of(row["start"]) for row in longs}
    for long_start in sorted(long_starts):
        long_candidates = candidates(rows, long_start, end)
        short_candidates = candidates(rows, long_start, start - dt.timedelta(days=1))
        if not long_candidates or not short_candidates:
            continue
        longer = long_candidates[-1]
        shorter = short_candidates[-1]
        value = value_of(longer) - value_of(shorter)
        detail = (
            _months(longer)
            + " ("
            + f"{value_of(longer):,}"
            + ", filed "
            + str(longer.get("filed"))
            + ", "
            + str(longer.get("accn"))
            + ") minus "
            + _months(shorter)
            + " ("
            + f"{value_of(shorter):,}"
            + ", filed "
            + str(shorter.get("filed"))
            + ", "
            + str(shorter.get("accn"))
            + ")"
        )
        same_filing = longer.get("accn") == shorter.get("accn")
        return Resolved(
            start,
            end,
            value,
            "derived" if same_filing else "derived across two filings",
            str(longer.get("form")),
            str(longer.get("accn")) + " + " + str(shorter.get("accn")),
            str(longer.get("filed")),
            detail,
        )
    return None


def _months(row: dict) -> str:
    start, end = date_of(row["start"]), date_of(row["end"])
    days = (end - start).days + 1
    return str(max(1, round(days / 30.4))) + "M to " + str(end)


def restatement_warning(rows: list[dict], start: dt.date | None, end: dt.date) -> str:
    """Flag a period that two filings reported with different values."""
    stated = candidates(rows, start, end)
    values = {value_of(row) for row in stated}
    if len(values) > 1:
        return (
            "RESTATED: "
            + " | ".join(
                f"{value_of(row):,} (filed {row.get('filed')}, {row.get('accn')})"
                for row in stated
            )
        )
    return ""


def resolve_item(
    rows: list[dict],
    window: list[tuple[dt.date, dt.date]],
    item: str,
    *,
    basis: str,
) -> tuple[Decimal | None, list[Resolved]]:
    parts: list[Resolved] = []
    total = Decimal(0)
    for start, end in window:
        resolved = resolve_quarter(rows, start, end, basis=basis)
        if resolved is None:
            return None, parts
        parts.append(resolved)
        total += resolved.value
    return total, parts


def choose_basis(facts: dict, window: list[tuple[dt.date, dt.date]]) -> str:
    """The basis the whole calculation runs on.

    The restated figures are preferred, because they are the filer's current
    statement of the period. They are only usable if they can produce a
    complete window for everything the other basis could; when a restatement
    lands inside the window and the filer never reissued the comparative, they
    cannot, and the figures as originally reported are used instead.
    """
    resolvable: dict[str, set[str]] = {}
    for basis in BASES:
        found = set()
        for item, concept in DURATION_CONCEPTS.items():
            total, _parts = resolve_item(rows_for(facts, concept), window, item, basis=basis)
            if total is not None:
                found.add(item)
        resolvable[basis] = found
    union: set[str] = set()
    for found in resolvable.values():
        union |= found
    for basis in BASES:
        if resolvable[basis] == union:
            return basis
    return max(BASES, key=lambda b: (len(resolvable[b]), b == "as_restated"))


# ---------------------------------------------------------------- the maths --


def main() -> int:
    print(RULE)
    print("Independent recalculation of the Teleflex golden case")
    print("No backend imports. Standard library only.")
    print(RULE)

    facts = companyfacts()
    print("    entity:", facts.get("entityName"), "| CIK", facts.get("cik"))
    window = find_quarter_windows(facts)

    chosen = CHOSEN_BASIS or choose_basis(facts, window)
    print()
    print(RULE)
    print("Reporting basis")
    print(RULE)
    print("A restatement inside the window splits each year-to-date series in")
    print("two. A window is built from one side only, never across the cut.")
    print()
    for name in BASES:
        resolvable = [
            item
            for item, concept in DURATION_CONCEPTS.items()
            if resolve_item(rows_for(facts, concept), window, item, basis=name)[0] is not None
        ]
        mark = " <-- used" if name == chosen else ""
        print(
            "   ",
            BASIS_LABELS[name].ljust(24),
            "resolves",
            str(len(resolvable)) + "/" + str(len(DURATION_CONCEPTS)),
            "items",
            mark,
        )
        missing = [item for item in DURATION_CONCEPTS if item not in resolvable]
        if missing:
            print("        cannot build:", ", ".join(missing))
    if chosen != "as_restated":
        note(
            "the window is built from the figures as originally reported: the "
            "restated figures cannot produce a complete window, because the "
            "filer restated the year without reissuing every comparative"
        )

    print()
    print(RULE)
    print("TTM flows, quarter by quarter -", BASIS_LABELS[chosen])
    print(RULE)

    ttm: dict[str, Decimal] = {}
    all_parts: dict[str, list[Resolved]] = {}

    for item, concept in DURATION_CONCEPTS.items():
        rows = rows_for(facts, concept)
        if not rows:
            raise SystemExit("no usable rows for " + concept)
        print()
        print(THIN)
        print(item, "<-", concept)
        total, parts = resolve_item(rows, window, item, basis=chosen)
        if total is None:
            print("    NOT RESOLVABLE on", BASIS_LABELS[chosen])
            note(item + ": could not be resolved on " + BASIS_LABELS[chosen])
            continue
        for part in parts:
            warning = restatement_warning(rows, part.start, part.end)
            print(
                "   ",
                part.start.isoformat(),
                "..",
                part.end.isoformat(),
                f"{part.value:>16,}",
                part.origin.ljust(8),
                part.form.ljust(5),
                part.accession,
                "filed " + part.basis,
            )
            if part.detail:
                print("        derived:", part.detail)
            if warning:
                print("        " + warning)
            if part.origin == "derived" and part.value < 0 and item in (
                "depreciation_amortization",
                "interest_expense",
            ):
                print("        !! IMPLAUSIBLE: this item cannot be negative")
                note(
                    item
                    + ": derived quarter "
                    + part.start.isoformat()
                    + ".."
                    + part.end.isoformat()
                    + " is negative, which it cannot be"
                )
        print("    TTM".ljust(34), f"{total:>16,}")
        ttm[item] = total
        all_parts[item] = parts

    # -- the same window on the basis that was NOT used ---------------------
    other = "as_originally_reported" if chosen == "as_restated" else "as_restated"
    print()
    print(RULE)
    print("The same window on the basis that was NOT used:", BASIS_LABELS[other])
    print(RULE)
    print("Teleflex restated 2024 and 2025 when it separated its business, so the")
    print("two bases are materially different. Neither is wrong; mixing them is.")
    original: dict[str, Decimal] = {}
    print()
    print(
        "    item".ljust(34),
        BASIS_LABELS[chosen].rjust(22),
        BASIS_LABELS[other].rjust(22),
        "   difference",
    )
    for item, concept in DURATION_CONCEPTS.items():
        rows = rows_for(facts, concept)
        total, parts = resolve_item(rows, window, item, basis=other)
        if total is None:
            print("   ", item.ljust(30), "not resolvable on " + BASIS_LABELS[other])
            continue
        original[item] = total
        used_total = ttm.get(item)
        if used_total is None:
            continue
        delta = total - used_total
        flag = "" if delta == 0 else "  <-- differs"
        print(
            "   ",
            item.ljust(30),
            f"{used_total:>20,}",
            f"{total:>22,}",
            f"{delta:>18,}",
            flag,
        )
    if original:
        o_required = [i for i in required_items() if i in original]
        if len(o_required) == 4:
            s3_original = sum((original[i] for i in o_required), Decimal(0))
            print()
            print("    S3 on " + BASIS_LABELS[chosen] + " (the basis used):")
            print("       ", f"{sum((ttm[i] for i in o_required), Decimal(0)):>18,}")
            print("    S3 on " + BASIS_LABELS[other] + ":")
            print("       ", f"{s3_original:>18,}")
            note(
                "S3 differs by "
                + f"{s3_original - sum((ttm[i] for i in o_required), Decimal(0)):,}"
                + " depending on which reporting basis is used"
            )

    # -- balances --------------------------------------------------------
    print()
    print(RULE)
    print("Balances at", TEST_DATE.isoformat(), "- dated exactly, nothing interpolated")
    print(RULE)
    balances: dict[str, Decimal] = {}
    balance_facts: dict[str, dict] = {}
    for item, concept in INSTANT_CONCEPTS.items():
        rows = rows_for(facts, concept)
        stated = candidates(rows, None, TEST_DATE)
        if not stated:
            raise SystemExit("no " + concept + " dated " + TEST_DATE.isoformat())
        row = stated[-1]
        balances[item] = value_of(row)
        balance_facts[item] = row
        warning = restatement_warning(rows, None, TEST_DATE)
        print(
            "   ",
            item.ljust(32),
            f"{value_of(row):>16,}",
            str(row.get("form")).ljust(5),
            row.get("accn"),
            "filed " + str(row.get("filed")),
        )
        if warning:
            print("        " + warning)

    # -- the impairment add-back ------------------------------------------
    print()
    print(RULE)
    print("Clause (b)(v) add-back: impairment, summed quarter by quarter")
    print(RULE)
    impairment = Decimal(0)
    impairment_rows: list[tuple] = []
    for concept in IMPAIRMENT_CONCEPTS:
        rows = rows_for(facts, concept)
        print()
        print("   ", concept)
        if not rows:
            print("        not reported by this filer")
            continue
        for start, end in window:
            resolved = resolve_quarter(rows, start, end, basis=chosen)
            if resolved is None:
                print(
                    "       ",
                    start.isoformat(),
                    "..",
                    end.isoformat(),
                    "no fact reported (the filer tags this only when non-zero)",
                )
                continue
            impairment += resolved.value
            impairment_rows.append(
                (concept, start, end, resolved.value, resolved.origin, resolved.form, resolved.accession)
            )
            print(
                "       ",
                start.isoformat(),
                "..",
                end.isoformat(),
                f"{resolved.value:>14,}",
                resolved.origin.ljust(8),
                resolved.form.ljust(5),
                resolved.accession,
            )
            if resolved.detail:
                print("            derived:", resolved.detail)
    print()
    print("    impairment TTM".ljust(34), f"{impairment:>16,}")

    # -- scenarios --------------------------------------------------------
    print()
    print(RULE)
    print("Covenant arithmetic")
    print(RULE)

    required = required_items()
    if any(item not in ttm for item in required):
        print("    cannot compute S3: a standard item did not resolve")
        return 1

    s3 = sum((ttm[item] for item in required), Decimal(0))
    print()
    print("S3, standard adjustments only:")
    for item in required:
        print(("    " + item).ljust(38), f"{ttm[item]:>16,}")
    print("  = S3 covenant EBITDA".ljust(38), f"{s3:>16,}")

    non_cash_gains = Decimal(0)  # the golden set records this as a sourced nil
    s2 = s3 + ttm["stock_based_compensation"] + impairment - non_cash_gains
    print()
    print("S2, plus the non-cash class:")
    print("    S3".ljust(38), f"{s3:>16,}")
    print("  + stock based compensation".ljust(38), f"{ttm['stock_based_compensation']:>16,}")
    print("  + impairment, clause (b)(v)".ljust(38), f"{impairment:>16,}")
    print("  - non-cash gains, recorded nil".ljust(38), f"{non_cash_gains:>16,}")
    print("  = S2 covenant EBITDA".ljust(38), f"{s2:>16,}")

    transaction_costs = Decimal(0)  # also a sourced nil in the golden set
    e_before_pool = s2 + transaction_costs
    cap = RESTRUCTURING_CAP_PCT * e_before_pool
    allowed = min(ttm["restructuring_charges"], max(cap, Decimal(0)))
    s1 = e_before_pool + allowed
    s0 = s1
    print()
    print("S1 and S0, plus the one-time class:")
    print("    S2".ljust(38), f"{s2:>16,}")
    print("  + transaction costs, recorded nil".ljust(38), f"{transaction_costs:>16,}")
    print("  = EBITDA before the clause (b)(x) pool".ljust(38), f"{e_before_pool:>16,}")
    print("    cap, 5% of that".ljust(38), f"{cap:>16,}")
    print("    restructuring requested".ljust(38), f"{ttm['restructuring_charges']:>16,}")
    print(
        "    allowed".ljust(38),
        f"{allowed:>16,}",
        "(cap binds)" if ttm["restructuring_charges"] > cap else "(cap does not bind)",
    )
    print("  = S1 = S0 covenant EBITDA".ljust(38), f"{s0:>16,}", "(no pro forma clause)")

    net_debt = (
        balances["long_term_debt"]
        + balances["current_portion_long_term_debt"]
        - balances["cash_and_equivalents"]
    )
    print()
    print("Net debt, cash netted without a cap:")
    print("    long term debt".ljust(38), f"{balances['long_term_debt']:>16,}")
    print("  + current portion".ljust(38), f"{balances['current_portion_long_term_debt']:>16,}")
    print("  - cash and equivalents".ljust(38), f"{balances['cash_and_equivalents']:>16,}")
    print("  = net debt".ljust(38), f"{net_debt:>16,}")

    print()
    print(RULE)
    print("Results")
    print(RULE)
    results: dict[str, dict] = {}
    for name, ebitda in (("S0", s0), ("S1", s1), ("S2", s2), ("S3", s3)):
        leverage = net_debt / ebitda
        cushion = Decimal(1) - net_debt / (LEVERAGE_CAP * ebitda)
        coverage = ebitda / ttm["interest_expense"]
        if net_debt > LEVERAGE_CAP * ebitda:
            verdict = "BREACH"
        elif net_debt > (Decimal(1) - TIGHT_BAND) * LEVERAGE_CAP * ebitda:
            verdict = "TIGHT"
        else:
            verdict = "PASS"
        results[name] = {
            "ebitda": ebitda,
            "leverage": leverage,
            "cushion": cushion,
            "coverage": coverage,
            "verdict": verdict,
        }
        print(
            "   ",
            name,
            f"EBITDA {ebitda:>15,}",
            f"leverage {leverage:7.4f}x",
            f"cushion {cushion * 100:8.4f}%",
            verdict.ljust(6),
            f"coverage {coverage:7.4f}x",
        )
    dependence = (s0 - s3) / s0
    print()
    print("    adjustment dependence = (S0 - S3) / S0 =", f"{dependence * 100:.4f}%")

    # -- comparison --------------------------------------------------------
    print()
    print(RULE)
    print("Comparison with data/golden/teleflex-2025q2/")
    print(RULE)
    differences: list[str] = []
    expected_path = Path("data/golden/teleflex-2025q2/expected.json")
    inputs_path = Path("data/golden/teleflex-2025q2/ttm_inputs.json")

    if inputs_path.exists():
        stored = json.loads(inputs_path.read_text(encoding="utf-8"))["items"]
        print()
        print("Per-item TTM inputs:")
        for item in list(DURATION_CONCEPTS) + list(INSTANT_CONCEPTS):
            if item not in stored:
                continue
            theirs = stored[item]["value"]
            mine = ttm.get(item, balances.get(item))
            if mine is None or theirs is None:
                continue
            same = mine == Decimal(theirs)
            print(
                "   ",
                ("OK   " if same else "DIFF ") + item.ljust(32),
                f"mine {mine:>16,}",
                "" if same else f"| app {Decimal(theirs):>16,}",
            )
            if not same:
                differences.append(
                    item + ": mine " + str(mine) + ", app " + str(theirs)
                )

    if expected_path.exists():
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        print()
        print("Scenario results:")

        def compare(label: str, mine: Decimal, theirs: str) -> None:
            # The golden file was written at 40 significant digits; this script
            # carries 50. Compare at the golden value's own precision so a
            # difference means a difference, not a longer tail.
            other = Decimal(theirs)
            try:
                same = mine.quantize(other) == other
            except Exception:  # noqa: BLE001 - exponent out of range
                same = mine == other
            print(
                "   ",
                ("OK   " if same else "DIFF ") + label.ljust(32),
                "mine " + str(mine)[:26],
                "" if same else "| golden " + str(theirs)[:26],
            )
            if not same:
                differences.append(label + ": mine " + str(mine) + ", golden " + theirs)

        compare("net debt", net_debt, expected["net_debt"])
        for name in ("S0", "S1", "S2", "S3"):
            compare(name + " EBITDA", results[name]["ebitda"], expected["scenarios"][name]["ebitda"])
        compare("adjustment dependence", dependence, expected["adjustment_dependence"])
        for name in ("S0", "S3"):
            covenant = expected["scenarios"][name]["covenants"]["max_total_net_leverage"]
            compare(name + " leverage", results[name]["leverage"], covenant["ratio"])
            compare(name + " cushion", results[name]["cushion"], covenant["cushion"])
            if results[name]["verdict"] != covenant["verdict"]:
                print(
                    "    DIFF ",
                    (name + " verdict").ljust(32),
                    "mine " + results[name]["verdict"],
                    "| golden " + covenant["verdict"],
                )
                differences.append(
                    name + " verdict: mine " + results[name]["verdict"]
                    + ", golden " + covenant["verdict"]
                )
            else:
                print("    OK   ", (name + " verdict").ljust(32), "mine " + results[name]["verdict"])

    # -- the analyst values -----------------------------------------------
    print()
    print(RULE)
    print("Inputs the golden set records as analyst values")
    print(RULE)
    mappings_path = Path("data/golden/teleflex-2025q2/mappings.json")
    if mappings_path.exists():
        mappings = json.loads(mappings_path.read_text(encoding="utf-8"))
        for record in mappings["records"]:
            if record.get("analyst_value") is None:
                continue
            claimed = Decimal(record["analyst_value"])
            if record["formula_item"] == "impairment_charges":
                same = claimed == impairment
                print(
                    "   ",
                    ("OK   " if same else "DIFF ") + "impairment_charges".ljust(32),
                    "golden " + f"{claimed:,}",
                    "| recomputed " + f"{impairment:,}",
                )
                if not same:
                    differences.append(
                        "impairment analyst value: golden "
                        + str(claimed)
                        + ", recomputed "
                        + str(impairment)
                    )
            else:
                print(
                    "    CHECK",
                    record["formula_item"].ljust(32),
                    "golden " + f"{claimed:,}",
                    "| nil asserted from reading the filings; not machine-checkable",
                )
                note(
                    record["formula_item"]
                    + ": recorded as a nil analyst value; must be checked by reading the filings"
                )

    print()
    print(RULE)
    if differences:
        print(len(differences), "DIFFERENCE(S) against the golden set:")
        for line in differences:
            print("   -", line)
    else:
        print("No differences against the golden set.")
    if findings:
        print()
        print("Findings to look at by hand:")
        for line in findings:
            print("   *", line)
    print(RULE)
    return 1 if differences else 0


def _basis_from_argv() -> str | None:
    """``--basis <name>``, for inspecting the basis the run did not choose."""
    if "--basis" not in sys.argv:
        return None
    wanted = sys.argv[sys.argv.index("--basis") + 1]
    if wanted not in BASES:
        raise SystemExit("--basis must be one of " + ", ".join(BASES))
    return wanted


if __name__ == "__main__":
    CHOSEN_BASIS = _basis_from_argv()
    sys.exit(main())
