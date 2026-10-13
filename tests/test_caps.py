"""The cap engine: fixed, percentage before and after pool, greater_of, and
the shared-pool reallocation that makes recalculating from scratch necessary."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.evaluator.scenarios import evaluate_ebitda
from backend.evaluator.schema import EbitdaFormula
from tests.conftest import component, ebitda_formula, inputs


def _data(**values: str):
    base = {"net_income": "100"}
    base.update(values)
    return inputs(base)


def test_fixed_cap_limits_the_pool():
    formula = ebitda_formula(
        [component("restructuring_charges", "one_time", cap_pool="A")],
        {"A": {"kind": "fixed", "fixed_amount": "20"}},
    )
    data = _data(restructuring_charges="35")
    result = evaluate_ebitda(formula, data, "S0")
    assert result.value == Decimal("120")
    pool = result.pools["A"]
    assert (pool.a, pool.cap, pool.allowed, pool.binding) == (
        Decimal("35"),
        Decimal("20"),
        Decimal("20"),
        True,
    )


def test_fixed_cap_that_does_not_bind_leaves_the_pool_alone():
    formula = ebitda_formula(
        [component("restructuring_charges", "one_time", cap_pool="A")],
        {"A": {"kind": "fixed", "fixed_amount": "20"}},
    )
    result = evaluate_ebitda(formula, _data(restructuring_charges="12"), "S0")
    assert result.value == Decimal("112")
    assert result.pools["A"].binding is False


def test_percentage_cap_measured_before_the_pool():
    """15% of EBITDA calculated before the add-backs: 0.15 x 100 = 15."""
    formula = ebitda_formula(
        [component("run_rate_cost_savings", "pro_forma", cap_pool="A")],
        {"A": {"kind": "percentage", "pct": "0.15", "basis": "before_pool"}},
    )
    result = evaluate_ebitda(formula, _data(run_rate_cost_savings="40"), "S0")
    assert result.pools["A"].cap == Decimal("15")
    assert result.value == Decimal("115")


def test_percentage_cap_measured_after_the_pool():
    """x <= 0.15(E + x) with E = 100 gives x <= 17.647...; EBITDA = 117.647..."""
    formula = ebitda_formula(
        [component("run_rate_cost_savings", "pro_forma", cap_pool="A")],
        {"A": {"kind": "percentage", "pct": "0.15", "basis": "after_pool"}},
    )
    result = evaluate_ebitda(formula, _data(run_rate_cost_savings="40"), "S0")
    cap = result.pools["A"].cap
    assert cap.quantize(Decimal("0.000001")) == Decimal("17.647059")
    # The defining property: the allowance is exactly 15% of the post-pool total.
    assert (cap / (Decimal("100") + cap)).quantize(Decimal("0.0000000001")) == Decimal("0.15")


def test_greater_of_takes_the_larger_cap():
    formula = ebitda_formula(
        [component("transaction_costs", "one_time", cap_pool="A")],
        {
            "A": {
                "kind": "greater_of",
                "fixed_amount": "50",
                "pct": "0.15",
                "basis": "before_pool",
            }
        },
    )
    # E = 100 so the percentage cap is 15; the fixed 50 is larger.
    big_fixed = evaluate_ebitda(formula, _data(transaction_costs="80"), "S0")
    assert big_fixed.pools["A"].cap == Decimal("50")

    # With E = 1000 the percentage cap of 150 wins.
    rich = inputs({"net_income": "1000", "transaction_costs": "400"})
    big_pct = evaluate_ebitda(formula, rich, "S0")
    assert big_pct.pools["A"].cap == Decimal("150")


def test_negative_base_gives_a_zero_percentage_cap_not_a_negative_one():
    formula = ebitda_formula(
        [component("restructuring_charges", "one_time", cap_pool="A")],
        {"A": {"kind": "percentage", "pct": "0.20", "basis": "before_pool"}},
    )
    data = inputs({"net_income": "-50", "restructuring_charges": "30"})
    result = evaluate_ebitda(formula, data, "S0")
    assert result.pools["A"].cap == Decimal("-10")  # the raw cap is negative
    assert result.pools["A"].allowed == Decimal("0")  # but nothing is allowed
    assert result.value == Decimal("-50")


def test_shared_pool_reallocates_when_an_item_is_removed():
    """The PRD's example. Pool A is capped at 20 with restructuring 15 and
    projected savings 15. S0 allows 20 of 30; S1 drops the savings and the
    restructuring's full 15 now fits. Subtracting would wrongly give 5."""
    formula = ebitda_formula(
        [
            component("restructuring_charges", "one_time", cap_pool="A"),
            component("run_rate_cost_savings", "pro_forma", cap_pool="A"),
        ],
        {"A": {"kind": "fixed", "fixed_amount": "20"}},
    )
    data = _data(restructuring_charges="15", run_rate_cost_savings="15")

    s0 = evaluate_ebitda(formula, data, "S0")
    assert s0.pools["A"].a == Decimal("30")
    assert s0.pools["A"].allowed == Decimal("20")
    assert s0.value == Decimal("120")

    s1 = evaluate_ebitda(formula, data, "S1")
    assert s1.pools["A"].a == Decimal("15")
    assert s1.pools["A"].allowed == Decimal("15")
    assert s1.value == Decimal("115")

    # Subtracting the removed item from S0 would have given 105, not 115.
    assert s0.value - Decimal("15") == Decimal("105")

    s2 = evaluate_ebitda(formula, data, "S2")
    assert s2.value == Decimal("100")


def test_capped_pool_is_attributed_pro_rata_and_sums_exactly():
    formula = ebitda_formula(
        [
            component("restructuring_charges", "one_time", cap_pool="A"),
            component("transaction_costs", "one_time", cap_pool="A"),
        ],
        {"A": {"kind": "fixed", "fixed_amount": "10"}},
    )
    data = _data(restructuring_charges="20", transaction_costs="10")
    result = evaluate_ebitda(formula, data, "S0")
    pool = result.pools["A"]
    shares = {part.item: part.allowed for part in pool.attribution}
    # 20/30 and 10/30 of the allowance of 10, rounded to cents.
    assert shares["restructuring_charges"] == Decimal("6.67")
    assert shares["transaction_costs"] == Decimal("3.33")
    assert sum(shares.values()) == pool.allowed == Decimal("10")


def test_attribution_residual_keeps_the_total_exact():
    """A pro rata split of 10 across three equal items cannot be exact in
    decimal, so the residual has to land somewhere and the sum must still
    equal the allowed amount."""
    formula = ebitda_formula(
        [
            component("restructuring_charges", "one_time", cap_pool="A"),
            component("transaction_costs", "one_time", cap_pool="A"),
            component("impairment_charges", "one_time", cap_pool="A"),
        ],
        {"A": {"kind": "fixed", "fixed_amount": "10"}},
    )
    data = _data(
        restructuring_charges="10", transaction_costs="10", impairment_charges="10"
    )
    pool = evaluate_ebitda(formula, data, "S0").pools["A"]
    assert sum(part.allowed for part in pool.attribution) == Decimal("10")


def test_two_pools_before_pool_do_not_inflate_each_other():
    """A before-pool percentage is measured prior to all capped add-backs, so
    neither pool's allowance feeds the other's cap."""
    formula = ebitda_formula(
        [
            component("restructuring_charges", "one_time", cap_pool="A"),
            component("run_rate_cost_savings", "pro_forma", cap_pool="B"),
        ],
        {
            "A": {"kind": "percentage", "pct": "0.10", "basis": "before_pool"},
            "B": {"kind": "percentage", "pct": "0.10", "basis": "before_pool"},
        },
    )
    data = _data(restructuring_charges="50", run_rate_cost_savings="50")
    result = evaluate_ebitda(formula, data, "S0")
    assert result.pools["A"].e == result.pools["B"].e == Decimal("100")
    assert result.pools["A"].cap == result.pools["B"].cap == Decimal("10")
    assert result.value == Decimal("120")


def test_an_after_pool_percentage_sees_the_other_pools_allowance():
    formula = ebitda_formula(
        [
            component("restructuring_charges", "one_time", cap_pool="A"),
            component("run_rate_cost_savings", "pro_forma", cap_pool="B"),
        ],
        {
            "A": {"kind": "fixed", "fixed_amount": "20"},
            "B": {"kind": "percentage", "pct": "0.10", "basis": "after_pool"},
        },
    )
    data = _data(restructuring_charges="20", run_rate_cost_savings="50")
    result = evaluate_ebitda(formula, data, "S0")
    assert result.pools["A"].allowed == Decimal("20")
    # B measures against 100 + 20 = 120, so its cap is 0.10 x 120 / 0.90.
    assert result.pools["B"].e == Decimal("120")
    expected = Decimal("0.10") * Decimal("120") / Decimal("0.90")
    assert result.pools["B"].cap.quantize(Decimal("0.00000001")) == expected.quantize(
        Decimal("0.00000001")
    )


def test_two_after_pool_pools_are_rejected_as_unsupported():
    with pytest.raises(ValidationError) as excinfo:
        ebitda_formula(
            [
                component("restructuring_charges", "one_time", cap_pool="A"),
                component("run_rate_cost_savings", "pro_forma", cap_pool="B"),
            ],
            {
                "A": {"kind": "percentage", "pct": "0.10", "basis": "after_pool"},
                "B": {"kind": "percentage", "pct": "0.10", "basis": "after_pool"},
            },
        )
    assert "depend on each other" in str(excinfo.value)


def test_undefined_and_unused_pools_are_rejected():
    with pytest.raises(ValidationError, match="undefined cap pools"):
        ebitda_formula([component("restructuring_charges", "one_time", cap_pool="A")], {})
    with pytest.raises(ValidationError, match="never used"):
        ebitda_formula(
            [component("restructuring_charges", "one_time")],
            {"A": {"kind": "fixed", "fixed_amount": "20"}},
        )


def test_prd_example_formula_validates_as_written():
    """The example in the PRD has to be a legal document of this language."""
    payload = {
        "formula_id": "acme-2025-ca",
        "version": 1,
        "status": "approved",
        "source_hash": "sha256:abc",
        "drafted_with": {"model": "claude-opus-5", "prompt_version": "compile-v3", "attempts": 1},
        "metric": "consolidated_ebitda",
        "base": {
            "item": "net_income",
            "span": {
                "start": 48210,
                "end": 48249,
                "quote": "Consolidated Net Income for such period",
            },
        },
        "components": [
            {
                "item": "interest_expense",
                "sign": "+",
                "category": "standard",
                "span": {"start": 48300, "end": 48320, "quote": "interest expense"},
                "review": {"decision": "accepted"},
            },
            {
                "item": "restructuring_charges",
                "sign": "+",
                "category": "one_time",
                "cap_pool": "A",
                "span": {"start": 48400, "end": 48425, "quote": "restructuring charges"},
                "review": {"decision": "edited", "note": "category was non_cash"},
            },
            {
                "item": "run_rate_cost_savings",
                "sign": "+",
                "category": "pro_forma",
                "cap_pool": "A",
                "span": {"start": 48500, "end": 48530, "quote": "run rate cost savings"},
                "review": {"decision": "accepted"},
            },
        ],
        "cap_pools": {
            "A": {
                "kind": "greater_of",
                "fixed_amount": "50000000",
                "pct": "0.15",
                "basis": "before_pool",
            }
        },
    }
    formula = EbitdaFormula.model_validate(payload)
    assert formula.cap_pools["A"].fixed_amount == Decimal("50000000")
    assert [c.item for c in formula.pool_items("A")] == [
        "restructuring_charges",
        "run_rate_cost_savings",
    ]
