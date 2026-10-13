"""Property tests for the evaluator invariants.

These are the claims the stress view rests on. Examples can only show that they
hold for the cases someone thought of; Hypothesis searches for the case nobody
thought of.
"""

from __future__ import annotations

import random
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backend.evaluator.caps import attribute_pro_rata, cap_amount
from backend.evaluator.covenant import evaluate_covenant
from backend.evaluator.scenarios import evaluate_ebitda
from backend.evaluator.money import exact
from backend.evaluator.schema import CapPool
from tests.conftest import component, ebitda_formula, inputs, leverage_covenant

MONEY = st.integers(min_value=-5_000_000, max_value=5_000_000).map(Decimal)
POSITIVE_MONEY = st.integers(min_value=0, max_value=5_000_000).map(Decimal)
PCT = st.sampled_from(["0.05", "0.10", "0.15", "0.20", "0.25", "0.3333", "0.5"]).map(Decimal)

ADD_BACK_ITEMS = [
    "stock_based_compensation",
    "restructuring_charges",
    "impairment_charges",
    "transaction_costs",
    "run_rate_cost_savings",
    "other_non_cash_charges",
]
CATEGORIES = ["non_cash", "one_time", "pro_forma"]


@settings(max_examples=200, deadline=None)
@given(
    net_income=MONEY,
    amounts=st.lists(POSITIVE_MONEY, min_size=1, max_size=6),
    categories=st.lists(st.sampled_from(CATEGORIES), min_size=1, max_size=6),
    cap=st.one_of(st.none(), POSITIVE_MONEY),
)
def test_removing_a_positive_add_back_never_raises_the_cushion(
    net_income, amounts, categories, cap
):
    """S0 >= S1 >= S2 >= S3 for non-negative add-backs, and the cushion of a
    maximum leverage covenant is monotone in EBITDA, so tightening the
    scenario can never make the covenant look safer."""
    count = min(len(amounts), len(categories), len(ADD_BACK_ITEMS))
    amounts, categories = amounts[:count], categories[:count]
    pool = {"A": {"kind": "fixed", "fixed_amount": str(cap)}} if cap is not None else {}
    pool_name = "A" if cap is not None else None
    formula = ebitda_formula(
        [
            component(ADD_BACK_ITEMS[i], categories[i], cap_pool=pool_name)
            for i in range(count)
        ],
        pool,
    )
    values = {"net_income": str(net_income), "long_term_debt": "1000000"}
    for index in range(count):
        values[ADD_BACK_ITEMS[index]] = str(amounts[index])
    data = inputs(values)

    ebitda = [evaluate_ebitda(formula, data, s).value for s in ("S0", "S1", "S2", "S3")]
    assert all(value is not None for value in ebitda)
    for earlier, later in zip(ebitda, ebitda[1:]):
        assert earlier >= later

    covenant = leverage_covenant("5.00")
    cushions = []
    for scenario in ("S0", "S1", "S2", "S3"):
        result = evaluate_covenant(covenant, evaluate_ebitda(formula, data, scenario), data)
        cushions.append(result.cushion if result.cushion is not None else Decimal("-1e9"))
    for earlier, later in zip(cushions, cushions[1:]):
        assert earlier >= later


@settings(max_examples=300, deadline=None)
@given(
    kind=st.sampled_from(["fixed", "percentage", "greater_of"]),
    basis=st.sampled_from(["before_pool", "after_pool"]),
    fixed=POSITIVE_MONEY,
    pct=PCT,
    e=MONEY,
    requested=POSITIVE_MONEY,
)
def test_a_pools_allowed_amount_never_exceeds_its_cap(kind, basis, fixed, pct, e, requested):
    spec: dict[str, object] = {"kind": kind}
    if kind in ("fixed", "greater_of"):
        spec["fixed_amount"] = str(fixed)
    if kind in ("percentage", "greater_of"):
        spec["pct"] = str(pct)
        spec["basis"] = basis
    pool = CapPool.model_validate(spec)

    formula = ebitda_formula(
        [component("restructuring_charges", "one_time", cap_pool="A")], {"A": spec}
    )
    data = inputs({"net_income": str(e), "restructuring_charges": str(requested)})
    result = evaluate_ebitda(formula, data, "S0")
    allowed = result.pools["A"].allowed
    cap = cap_amount(pool, e)
    assert allowed <= max(cap, Decimal(0))
    assert allowed <= requested
    assert allowed >= 0
    with exact():
        assert result.value == e + allowed


@settings(max_examples=200, deadline=None)
@given(
    net_income=MONEY,
    amounts=st.lists(POSITIVE_MONEY, min_size=2, max_size=5),
    cap=POSITIVE_MONEY,
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_scenario_results_do_not_depend_on_component_order(net_income, amounts, cap, seed):
    count = min(len(amounts), len(ADD_BACK_ITEMS))
    amounts = amounts[:count]
    spec = {"A": {"kind": "fixed", "fixed_amount": str(cap)}}
    components = [
        component(ADD_BACK_ITEMS[i], CATEGORIES[i % len(CATEGORIES)], cap_pool="A")
        for i in range(count)
    ]
    values = {"net_income": str(net_income)}
    for index in range(count):
        values[ADD_BACK_ITEMS[index]] = str(amounts[index])
    data = inputs(values)

    shuffled = list(components)
    random.Random(seed).shuffle(shuffled)
    for scenario in ("S0", "S1", "S2", "S3"):
        straight = evaluate_ebitda(ebitda_formula(components, spec), data, scenario)
        mixed = evaluate_ebitda(ebitda_formula(shuffled, spec), data, scenario)
        assert straight.value == mixed.value
        if "A" in straight.pools and "A" in mixed.pools:
            assert straight.pools["A"].allowed == mixed.pools["A"].allowed
            assert {
                (part.item, part.allowed) for part in straight.pools["A"].attribution
            } == {(part.item, part.allowed) for part in mixed.pools["A"].attribution}


@settings(max_examples=300, deadline=None)
@given(
    amounts=st.lists(POSITIVE_MONEY, min_size=1, max_size=8),
    allowed=POSITIVE_MONEY,
)
def test_pro_rata_attribution_always_sums_to_the_allowed_amount(amounts, allowed):
    total = sum(amounts, Decimal(0))
    assume(total > 0)
    allowed = min(allowed, total)
    parts = [("k" + str(i), "item" + str(i), amount) for i, amount in enumerate(amounts)]
    attribution = attribute_pro_rata(parts, allowed, total)
    assert sum(part.allowed for part in attribution) == allowed
    assert all(part.allowed >= 0 for part in attribution)
    assert all(part.allowed <= part.requested for part in attribution)


@settings(max_examples=200, deadline=None)
@given(debt=POSITIVE_MONEY, ebitda=st.integers(min_value=1, max_value=5_000_000).map(Decimal))
def test_the_verdict_always_agrees_with_the_exact_comparison(debt, ebitda):
    """The verdict must never disagree with D <= T x E, whatever rounding the
    displayed ratio and cushion go through."""
    threshold = Decimal("4.75")
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs(
        {"net_income": str(ebitda), "interest_expense": "0", "long_term_debt": str(debt)}
    )
    result = evaluate_covenant(
        leverage_covenant("4.75"), evaluate_ebitda(formula, data, "S0"), data
    )
    breached = debt > threshold * ebitda
    assert (result.verdict == "BREACH") == breached
    if not breached:
        assert result.cushion >= 0
        assert result.debt_capacity >= 0
