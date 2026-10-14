"""Write the hand-verified golden set for the Teleflex deal.

The formula below is written by hand from the clause text of the agreement,
clause by clause, and the spans are located in the normalised agreement so the
golden formula is checkable against the same source the compiler sees. The
expected results in ``expected.json`` were computed by hand from the figures in
``ttm_inputs.json`` before this script was ever run against the evaluator; the
test suite then asserts the engine reproduces them.

Run with::

    python -m scripts.build_golden
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from backend.agreement.fetch import fetch_agreement
from backend.compiler.spans import locate, verify_version
from backend.edgar.client import EdgarClient
from backend.evaluator.schema import FormulaVersion

GOLDEN_DIR = Path("data/golden/teleflex-2025q2")

DEAL = {
    "deal_id": "teleflex-2025q2",
    "borrower": "Teleflex Incorporated",
    "ticker": "TFX",
    "cik": "0000096943",
    "agreement": (
        "Third Amended and Restated Credit Agreement dated November 4, 2022, "
        "as amended by Amendment No. 2 dated June 24, 2025"
    ),
    "exhibit_url": (
        "https://www.sec.gov/Archives/edgar/data/96943/000009694325000107/"
        "ex101to6-27x20258xkrecredi.htm"
    ),
    "exhibit_accession": "0000096943-25-000107",
    "exhibit_form": "8-K",
    "exhibit_filed": "2025-06-30",
    "test_date": "2025-06-29",
    "fiscal_period": "Q2 2025",
    "notes": (
        "Chosen because the agreement uses only constructs the formula language "
        "supports: a percentage cap measured before its own pool on clause (b)(x), "
        "a fixed cap on clause (b)(xi), net debt with uncapped cash netting, and "
        "flat thresholds on both maintenance covenants."
    ),
}

#: Each entry is (clause, quote, item, sign, category, cap_pool).
#: The quotes are the exact clause text; the offsets are located at build time.
COMPONENTS: list[tuple[str, str, str, str, str, str | None]] = [
    ("(b)(i)", "income tax expense", "income_tax_expense", "+", "standard", None),
    (
        "(b)(ii)",
        "Consolidated Interest Expense, amortization or writeoff of debt discount",
        "interest_expense",
        "+",
        "standard",
        None,
    ),
    (
        "(b)(iii)",
        "depreciation and amortization expense, including amortization of intangibles",
        "depreciation_amortization",
        "+",
        "standard",
        None,
    ),
    (
        "(b)(iv)",
        "losses, charges or expenses relating to or incurred in connection with the Transactions",
        "transaction_costs",
        "+",
        "one_time",
        None,
    ),
    ("(b)(v)", "any non-cash charges, expenses or losses", "impairment_charges", "+", "accepted_non_cash", None),
    (
        "(b)(vi)",
        "non-cash costs associated with inventory purchase price adjustments and in process research and development",
        "unmapped",
        "+",
        "accepted_non_cash",
        None,
    ),
    (
        "(b)(vii)",
        "non-cash stock based compensation expense relating to stock options and restricted stock granted to employees and directors",
        "stock_based_compensation",
        "+",
        "accepted_non_cash",
        None,
    ),
    (
        "(b)(viii)",
        "extraordinary, unusual or non-recurring cash losses or charges",
        "unmapped",
        "+",
        "one_time",
        None,
    ),
    (
        "(b)(ix)",
        "any net losses from disposed, abandoned or discontinued operations or assets",
        "unmapped",
        "+",
        "one_time",
        None,
    ),
    (
        "(b)(x)",
        "cash restructuring and restructuring related charges",
        "restructuring_charges",
        "+",
        "one_time",
        "clause_x",
    ),
    (
        "(b)(xi)",
        "cash charges incurred by the Borrower in connection with the termination of its existing pension plan",
        "unmapped",
        "+",
        "one_time",
        "clause_xi",
    ),
    (
        "(b)(xiii)",
        "pre-tax mark-to-market losses on pension plans and settlement/curtailment losses thereon",
        "unmapped",
        "+",
        "accepted_non_cash",
        None,
    ),
    (
        "proviso to (b)",
        "any cash payment made with respect to any non-cash charges added back in computing Consolidated EBITDA for any period pursuant to clauses (b)(v), (b)(vi) or (b)(vii) above",
        "unsupported",
        "-",
        "accepted_non_cash",
        None,
    ),
    (
        "(c)(i)",
        "extraordinary, unusual or non-recurring cash income or gains",
        "unmapped",
        "-",
        "one_time",
        None,
    ),
    ("(c)(ii)", "non- cash income or gains", "other_non_cash_gains", "-", "accepted_non_cash", None),
    (
        "(c)(iii)",
        "any net gains from disposed, abandoned or discontinued operations or assets",
        "unmapped",
        "-",
        "one_time",
        None,
    ),
    (
        "(c)(iv)",
        "pre-tax mark-to-market gains on pension plans and settlement/curtailment gains thereon",
        "unmapped",
        "-",
        "accepted_non_cash",
        None,
    ),
]

#: Why each component was accepted, edited, or taken out of the calculation.
REVIEWS: dict[str, dict[str, str]] = {
    "(b)(i)": {"decision": "accepted"},
    "(b)(ii)": {
        "decision": "edited",
        "note": (
            "Clause (b)(ii) adds Consolidated Interest Expense together with "
            "amortisation and write-off of debt discount, issuance costs and "
            "financing fees. Mapped to interest_expense alone; the financing-cost "
            "components are not separately reported, so this understates the "
            "contractual add-back."
        ),
    },
    "(b)(iii)": {"decision": "accepted"},
    "(b)(iv)": {
        "decision": "accepted",
        "note": "Transaction and acquisition-related charges.",
    },
    "(b)(v)": {
        "decision": "edited",
        "note": (
            "Clause (b)(v) is a catch-all for any non-cash charge. Mapped to "
            "impairment_charges because goodwill and intangible impairments are "
            "the only non-cash charges Teleflex quantifies in this period other "
            "than stock compensation, which clause (b)(vii) adds back separately. "
            "Mapping it to other_non_cash_charges as well would double count."
        ),
    },
    "(b)(vi)": {
        "decision": "excluded_unsupported",
        "note": (
            "Non-cash inventory purchase price adjustments and in-process research "
            "and development have no item in the vocabulary and no reported "
            "concept. Excluded, which understates covenant EBITDA."
        ),
    },
    "(b)(vii)": {"decision": "accepted"},
    "(b)(viii)": {
        "decision": "excluded_unsupported",
        "note": (
            "Extraordinary or non-recurring cash losses are only addable when the "
            "borrower classifies them as such in its published statements. That "
            "condition is not representable, and no vocabulary item covers the "
            "charge. Excluded, which understates covenant EBITDA."
        ),
    },
    "(b)(ix)": {
        "decision": "excluded_unsupported",
        "note": (
            "Net losses from discontinued operations have no vocabulary item. "
            "Excluded, which understates covenant EBITDA."
        ),
    },
    "(b)(x)": {
        "decision": "accepted",
        "note": "Capped at 5% of Consolidated EBITDA measured before this clause.",
    },
    "(b)(xi)": {
        "decision": "excluded_unsupported",
        "note": (
            "Pension termination cash charges have no vocabulary item. The $25m "
            "fixed cap is recorded on the pool so the cap rule survives the "
            "exclusion, but nothing is added. Excluded, which understates "
            "covenant EBITDA."
        ),
    },
    "(b)(xiii)": {
        "decision": "excluded_unsupported",
        "note": (
            "Conditional on the borrower adopting mark-to-market pension "
            "accounting, which the language cannot express, and Teleflex has not "
            "adopted it. Excluded."
        ),
    },
    "proviso to (b)": {
        "decision": "excluded_unsupported",
        "note": (
            "The claw-back of cash paid in a later period against a non-cash "
            "charge added back in an earlier one depends on prior periods. The "
            "language has no cross-period state, so this is unsupported rather "
            "than approximated. Excluded, which overstates covenant EBITDA if "
            "such payments occurred."
        ),
    },
    "(c)(i)": {
        "decision": "excluded_unsupported",
        "note": (
            "The mirror of clause (b)(viii) on the deduction side, with the same "
            "classification condition and no vocabulary item. Excluded, which "
            "overstates covenant EBITDA."
        ),
    },
    "(c)(ii)": {"decision": "accepted"},
    "(c)(iii)": {
        "decision": "excluded_unsupported",
        "note": (
            "Net gains from discontinued operations have no vocabulary item. "
            "Excluded, which overstates covenant EBITDA."
        ),
    },
    "(c)(iv)": {
        "decision": "excluded_unsupported",
        "note": "Mirror of clause (b)(xiii); the same accounting condition applies.",
    },
}

CAP_POOLS: dict[str, dict[str, Any]] = {
    "clause_x": {
        "kind": "percentage",
        "pct": "0.05",
        "basis": "before_pool",
        "label": "clause (b)(x) restructuring cap",
        "quote": (
            "the aggregate amount of such charges permitted to be added back "
            "pursuant to this clause (x) during any four consecutive fiscal quarter "
            "period of the Borrower shall not exceed 5% of Consolidated EBITDA for "
            "such period (calculated without giving effect to the add-back of any "
            "item pursuant to this clause (x))"
        ),
    },
    "clause_xi": {
        "kind": "fixed",
        "fixed_amount": "25000000",
        "label": "clause (b)(xi) pension termination cap",
        "quote": (
            "the aggregate amount of such charges permitted to be added back "
            "pursuant to this clause (xi) shall not exceed $25,000,000"
        ),
    },
}

COVENANTS: list[dict[str, Any]] = [
    {
        "id": "max_total_net_leverage",
        "name": "Maximum Consolidated Total Net Leverage Ratio",
        "type": "max_ratio",
        "quote": (
            "The Borrower will not permit the Consolidated Total Net Leverage Ratio, "
            "as at the last day of any period of four consecutive fiscal quarters of "
            "the Borrower which period ends on or after September 30, 2022 to exceed "
            "4.50 to 1.00."
        ),
        "items": ["long_term_debt", "current_portion_long_term_debt"],
        "items_quote": (
            "(I) (a) all obligations for borrowed money (including any obligations "
            "convertible into capital stock or other securities), (b) all obligations "
            "evidenced by bonds, debentures, notes or similar instruments and (c) all "
            "Capital Lease Obligations"
        ),
        "net_of_cash": {"enabled": True},
        "net_of_cash_quote": "minus (II) the amount of Qualified Cash at such date",
        "schedule": [{"from": "2022-09-30", "threshold": "4.50"}],
        "review": {
            "decision": "edited",
            "note": (
                "The Acquisition Holiday raises the cap to 5.00x for four quarters "
                "after a qualifying acquisition. That is conditional on an event the "
                "language cannot express, so only the standing 4.50x threshold is "
                "recorded; if a holiday is in force the covenant is reported tighter "
                "than it is. Capital Lease Obligations are not separately reported "
                "and are omitted from the numerator, which understates net debt."
            ),
        },
    },
    {
        "id": "min_interest_coverage",
        "name": "Minimum Consolidated Interest Coverage Ratio",
        "type": "min_ratio",
        "quote": (
            "The Borrower will not permit the Consolidated Interest Coverage Ratio "
            "for any period of four consecutive fiscal quarters of the Borrower which "
            "period ends on or after September 30, 2022 to be less than 3.50 to 1.00."
        ),
        "items": ["interest_expense"],
        "items_quote": "Consolidated Interest Expense paid in cash for such period",
        "schedule": [{"from": "2022-09-30", "threshold": "3.50"}],
        "review": {
            "decision": "edited",
            "note": (
                "The covenant divides by Consolidated Interest Expense paid in cash. "
                "The mapped concept is accrued interest expense, which differs from "
                "cash interest; the mapping rationale records that."
            ),
        },
    },
]

DEFINITIONS = [
    ("Consolidated EBITDA", 0, '"Consolidated EBITDA" means'),
    ("Consolidated Net Income", 1, '"Consolidated Net Income" means'),
    ("Consolidated Interest Expense", 1, '"Consolidated Interest Expense" means'),
    ("Consolidated Total Funded Indebtedness", 1, '"Consolidated Total Funded Indebtedness" means'),
    ("Consolidated Total Net Leverage Ratio", 1, '"Consolidated Total Net Leverage Ratio" means'),
    ("Consolidated Interest Coverage Ratio", 1, '"Consolidated Interest Coverage Ratio" means'),
    ("Qualified Cash", 2, '"Qualified Cash" means'),
]

BASE_QUOTE = "Consolidated Net Income for such period"


def build_formula(text: str) -> FormulaVersion:
    """The hand-written formula, with every span located in ``text``."""
    definition_start = text.find('"Consolidated EBITDA" means')
    if definition_start < 0:
        raise SystemExit("the Consolidated EBITDA definition was not found")

    components: list[dict[str, Any]] = []
    cursor = definition_start
    for clause, quote, item, sign, category, pool in COMPONENTS:
        span = locate(text, quote, start=cursor)
        cursor = span.start + 1
        entry: dict[str, Any] = {
            "item": item,
            "sign": sign,
            "category": category,
            "clause": clause,
            "span": span.model_dump(),
            "review": REVIEWS[clause],
        }
        if pool:
            entry["cap_pool"] = pool
        if item in ("unmapped", "unsupported"):
            entry["reason"] = REVIEWS[clause]["note"]
        components.append(entry)

    pools: dict[str, Any] = {}
    for name, spec in CAP_POOLS.items():
        body = {key: value for key, value in spec.items() if key != "quote"}
        body["span"] = locate(text, spec["quote"], start=definition_start).model_dump()
        pools[name] = body

    covenants: list[dict[str, Any]] = []
    for spec in COVENANTS:
        side: dict[str, Any] = {
            "items": spec["items"],
            "span": locate(text, spec["items_quote"]).model_dump(),
        }
        if "net_of_cash" in spec:
            netting = dict(spec["net_of_cash"])
            netting["span"] = locate(text, spec["net_of_cash_quote"]).model_dump()
            side["net_of_cash"] = netting
        if spec["type"] == "max_ratio":
            numerator: Any = side
            denominator: Any = "consolidated_ebitda"
        else:
            numerator = "consolidated_ebitda"
            denominator = side
        covenants.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "type": spec["type"],
                "numerator": numerator,
                "denominator": denominator,
                "schedule": spec["schedule"],
                "test": {"frequency": "quarterly", "period": "ttm"},
                "span": locate(text, spec["quote"]).model_dump(),
                "review": spec["review"],
            }
        )

    definitions = {}
    for term, depth, needle in DEFINITIONS:
        span = locate(text, needle)
        definitions[term] = {
            "term": term,
            "depth": depth,
            "span": span.model_dump(),
            "resolved": True,
            "references": [],
        }

    from backend.agreement.normalise import text_hash

    source_hash = text_hash(text)
    approved_at = "2026-10-13T00:00:00"
    payload = {
        "deal_id": DEAL["deal_id"],
        "version": 1,
        "status": "approved",
        "source_hash": source_hash,
        "approved_by": "golden set (hand-written from the clause text)",
        "approved_at": approved_at,
        "created_at": approved_at,
        "ebitda": {
            "formula_id": DEAL["deal_id"],
            "version": 1,
            "status": "approved",
            "source_hash": source_hash,
            "metric": "consolidated_ebitda",
            "base": {
                "item": "net_income",
                "clause": "(a)",
                "span": locate(text, BASE_QUOTE, start=definition_start).model_dump(),
            },
            "components": components,
            "cap_pools": pools,
        },
        "covenants": covenants,
        "definitions": definitions,
    }
    return FormulaVersion.model_validate(payload)


def main() -> None:
    client = EdgarClient()
    agreement = fetch_agreement(DEAL["exhibit_url"], client=client)
    version = build_formula(agreement.text)

    failures = verify_span_check(version, agreement.text)
    if failures:
        for failure in failures:
            print("SPAN FAILURE", failure.as_dict())
        raise SystemExit("the golden formula has unverified spans")

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    _write(GOLDEN_DIR / "deal.json", DEAL)
    _write(GOLDEN_DIR / "formula.json", version.model_dump(mode="json", by_alias=True))
    print("wrote", GOLDEN_DIR / "formula.json")
    print("source_hash", agreement.source_hash)
    print("components", len(version.ebitda.components))


def verify_span_check(version: FormulaVersion, text: str):
    return verify_version(version, text)


def _write(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
