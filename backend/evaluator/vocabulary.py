"""The closed item vocabulary of the formula language.

Nothing outside these names can enter a formula. A clause item that has no
name here is recorded as ``unmapped``; a construct the language cannot express
is recorded as ``unsupported``. Both block approval until a reviewer resolves
them, which is what keeps the language closed instead of merely suggestive.
"""

from __future__ import annotations

from typing import Literal, get_args

BASE_ITEMS = ("net_income",)

STANDARD_ADJUSTMENTS = (
    "interest_expense",
    "income_tax_expense",
    "depreciation_amortization",
)

DISCRETIONARY_ADJUSTMENTS = (
    "stock_based_compensation",
    "restructuring_charges",
    "impairment_charges",
    "transaction_costs",
    "run_rate_cost_savings",
    "other_non_cash_charges",
)

DEDUCTIONS = (
    "gain_on_asset_sales",
    "other_non_cash_gains",
)

DEBT_ITEMS = (
    "long_term_debt",
    "current_portion_long_term_debt",
    "short_term_borrowings",
    "finance_lease_liabilities",
    "cash_and_equivalents",
)

SENTINEL_ITEMS = ("unmapped", "unsupported")

ItemName = Literal[
    "net_income",
    "interest_expense",
    "income_tax_expense",
    "depreciation_amortization",
    "stock_based_compensation",
    "restructuring_charges",
    "impairment_charges",
    "transaction_costs",
    "run_rate_cost_savings",
    "other_non_cash_charges",
    "gain_on_asset_sales",
    "other_non_cash_gains",
    "long_term_debt",
    "current_portion_long_term_debt",
    "short_term_borrowings",
    "finance_lease_liabilities",
    "cash_and_equivalents",
    "unmapped",
    "unsupported",
]

ALL_ITEMS: tuple[str, ...] = get_args(ItemName)

#: Items that are never resolvable to a financial fact and therefore never
#: computable. They exist so a draft can say "there is something here I cannot
#: express" instead of silently dropping a clause.
BLOCKING_ITEMS = frozenset(SENTINEL_ITEMS)

#: Items whose facts are point-in-time balances rather than flows.
INSTANT_ITEMS = frozenset(DEBT_ITEMS)

#: Items with no XBRL concept at all: only an analyst can supply a value.
ANALYST_ONLY_ITEMS = frozenset({"run_rate_cost_savings"})

#: Items that cannot be negative over a trailing twelve month period. A
#: derived quarter is a subtraction of two cumulative figures, so it is where a
#: basis error shows up as an arithmetic impossibility: depreciation cannot run
#: backwards and a borrower cannot be paid to hold debt. A negative here is
#: reported as ``implausible_value`` rather than summed into a TTM total.
#:
#: Tax expense is deliberately absent: a tax benefit is a real negative, and so
#: is a net loss.
NON_NEGATIVE_FLOW_ITEMS = frozenset(
    {
        "depreciation_amortization",
        "interest_expense",
    }
)

# -- the add-back taxonomy ---------------------------------------------------
#
# The categories a credit professional actually argues about, rather than a
# neutral description of where a charge sits in the accounts:
#
# * ``standard``          interest, taxes, depreciation and amortisation. The
#                         "ITDA" of EBITDA. Nobody disputes these.
# * ``accepted_non_cash`` impairment, amortisation of acquired intangibles and
#                         stock-based compensation. Non-cash charges a lender
#                         will normally accept being added back - though stock
#                         compensation is only *arguably* accepted, since it is
#                         a real economic cost, and the UI says so.
# * ``one_time``          a charge the contract calls unusual or non-recurring
#                         and which the filings do not show recurring.
# * ``aggressive_recurring``
#                         a charge added back as "one-time" that the borrower
#                         has in fact reported in most of the last four fiscal
#                         years. Not a category a drafter writes: it is decided
#                         from the filings at run time by
#                         ``backend/edgar/recurrence.py``, and a ``one_time``
#                         component is promoted into it when the evidence says
#                         so. The evidence travels with the result.
# * ``aggressive_pro_forma``
#                         projected cost savings, synergies and run-rate
#                         adjustments: money the borrower has not earned.
#
# ``one_time`` and ``aggressive_recurring`` are both needed, and the reason is
# in the scenarios below: S2 removes the *recurring* "one-time" charges and
# keeps the genuinely non-recurring ones, so the two cannot be one category.

Category = Literal[
    "standard",
    "accepted_non_cash",
    "one_time",
    "aggressive_recurring",
    "aggressive_pro_forma",
]
CATEGORIES: tuple[str, ...] = get_args(Category)

#: Categories a lender would call aggressive. Removing exactly these is what
#: S2 does, and their share of covenant EBITDA is the headline figure.
AGGRESSIVE_CATEGORIES = frozenset({"aggressive_recurring", "aggressive_pro_forma"})

#: The category a ``one_time`` component is promoted to when the filings show
#: the charge recurring. Only this promotion is data-driven; every other
#: category is a property of the clause.
RECURRING_CATEGORY = "aggressive_recurring"
PROMOTABLE_CATEGORY = "one_time"

#: Stock compensation is in ``accepted_non_cash`` because that is where the
#: market puts it, not because it is obviously right: it is a real cost of
#: paying people. Flagged rather than silently filed away.
ARGUABLY_ACCEPTED_ITEMS = frozenset({"stock_based_compensation"})

Sign = Literal["+", "-"]

#: The categories each scenario keeps. S0 keeps every component the agreement
#: permits; each later scenario removes one class of argument.
SCENARIO_CATEGORIES: dict[str, frozenset[str] | None] = {
    "S0": None,
    "S1": frozenset(
        {"standard", "accepted_non_cash", "one_time", "aggressive_recurring"}
    ),
    "S2": frozenset({"standard", "accepted_non_cash", "one_time"}),
    "S3": frozenset({"standard", "accepted_non_cash"}),
}

SCENARIO_LABELS = {
    "S0": "Contractual",
    "S1": "Without pro forma",
    "S2": "Without aggressive adjustments",
    "S3": "Conservative EBITDA",
}

SCENARIO_QUESTIONS = {
    "S0": "What does the agreement permit?",
    "S1": "What if the projected savings never arrive?",
    "S2": "What survives if every aggressive add-back is disallowed?",
    "S3": "What does the business earn on standard and accepted non-cash terms?",
}

SCENARIO_IDS = ("S0", "S1", "S2", "S3")


def period_type_for(item: str) -> str:
    """``instant`` for balance-sheet items, ``duration`` for flows."""
    return "instant" if item in INSTANT_ITEMS else "duration"
