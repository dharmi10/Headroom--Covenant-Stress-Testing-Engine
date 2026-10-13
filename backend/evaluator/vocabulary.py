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

Category = Literal["standard", "non_cash", "one_time", "pro_forma"]
CATEGORIES: tuple[str, ...] = get_args(Category)

Sign = Literal["+", "-"]

#: The categories each scenario keeps. S0 keeps every permitted component.
SCENARIO_CATEGORIES: dict[str, frozenset[str] | None] = {
    "S0": None,
    "S1": frozenset({"standard", "non_cash", "one_time"}),
    "S2": frozenset({"standard", "non_cash"}),
    "S3": frozenset({"standard"}),
}

SCENARIO_LABELS = {
    "S0": "Contractual",
    "S1": "No pro forma",
    "S2": "No one-time",
    "S3": "Standard adjustments only",
}

SCENARIO_IDS = ("S0", "S1", "S2", "S3")


def period_type_for(item: str) -> str:
    """``instant`` for balance-sheet items, ``duration`` for flows."""
    return "instant" if item in INSTANT_ITEMS else "duration"
