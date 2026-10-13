"""Scenario selection, adjustment dependence, step attribution, determinism."""

from __future__ import annotations

from decimal import Decimal

from backend.evaluator.run import canonical_hash, evaluate_run
from backend.evaluator.scenarios import evaluate_ebitda
from tests.conftest import (
    component,
    coverage_covenant,
    ebitda_formula,
    formula_version,
    inputs,
    leverage_covenant,
)


def _formula():
    return ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("income_tax_expense", "standard"),
            component("depreciation_amortization", "standard"),
            component("stock_based_compensation", "non_cash"),
            component("restructuring_charges", "one_time"),
            component("run_rate_cost_savings", "pro_forma"),
        ]
    )


def _inputs():
    return inputs(
        {
            "net_income": "40",
            "interest_expense": "25",
            "income_tax_expense": "10",
            "depreciation_amortization": "25",
            "stock_based_compensation": "8",
            "restructuring_charges": "15",
            "run_rate_cost_savings": "12",
            "long_term_debt": "450",
        }
    )


def test_each_scenario_keeps_the_right_categories():
    formula, data = _formula(), _inputs()
    values = {s: evaluate_ebitda(formula, data, s).value for s in ("S0", "S1", "S2", "S3")}
    assert values["S0"] == Decimal("135")  # 100 + 8 + 15 + 12
    assert values["S1"] == Decimal("123")  # drops projected savings
    assert values["S2"] == Decimal("108")  # drops one-time charges too
    assert values["S3"] == Decimal("100")  # standard adjustments only


def test_scenarios_are_strictly_ordered_for_positive_add_backs():
    formula, data = _formula(), _inputs()
    values = [evaluate_ebitda(formula, data, s).value for s in ("S0", "S1", "S2", "S3")]
    assert values == sorted(values, reverse=True)


def test_deductions_are_subtracted_in_the_scenarios_that_include_them():
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("gain_on_asset_sales", "non_cash", sign="-"),
        ]
    )
    data = inputs(
        {"net_income": "100", "interest_expense": "20", "gain_on_asset_sales": "30"}
    )
    assert evaluate_ebitda(formula, data, "S0").value == Decimal("90")
    # S3 keeps only standard components, so the deduction drops out as well.
    assert evaluate_ebitda(formula, data, "S3").value == Decimal("120")


def test_adjustment_dependence_is_the_share_coming_from_adjustments():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, _inputs())
    # (135 - 100) / 135
    assert run.adjustment_dependence.quantize(Decimal("0.000001")) == Decimal("0.259259")
    assert run.as_dict()["adjustment_dependence_display"] == "0.2593"


def test_step_attribution_names_the_components_behind_each_fall():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, _inputs())
    by_pair = {(s.from_scenario, s.to_scenario): s for s in run.steps}

    savings = by_pair[("S0", "S1")]
    assert savings.delta == Decimal("-12")
    assert [(item, delta) for _, item, delta in savings.contributions] == [
        ("run_rate_cost_savings", Decimal("-12"))
    ]

    one_time = by_pair[("S1", "S2")]
    assert one_time.delta == Decimal("-15")
    assert [item for _, item, _ in one_time.contributions] == ["restructuring_charges"]

    non_cash = by_pair[("S2", "S3")]
    assert non_cash.delta == Decimal("-8")
    assert [item for _, item, _ in non_cash.contributions] == ["stock_based_compensation"]


def test_verdicts_tighten_across_the_scenarios():
    version = formula_version(_formula(), [leverage_covenant("4.00"), coverage_covenant("3.00")])
    run = evaluate_run(version, _inputs())
    leverage = {s: run.covenants[s]["max_total_leverage"] for s in ("S0", "S1", "S2", "S3")}
    assert leverage["S0"].ratio.quantize(Decimal("0.0001")) == Decimal("3.3333")
    assert leverage["S0"].verdict == "PASS"
    assert leverage["S3"].verdict == "BREACH"  # 450 / 100 = 4.50x against a 4.00x cap
    assert run.headline_verdict == "PASS"  # the deal is reported on contractual terms


def test_a_run_is_identical_across_ten_identical_runs():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    hashes = {evaluate_run(version, _inputs()).output_hash for _ in range(10)}
    assert len(hashes) == 1


def test_the_output_hash_changes_when_the_evaluator_version_changes():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    first = evaluate_run(version, _inputs())
    second = evaluate_run(version, _inputs(), evaluator_version="evaluator-2")
    assert first.output_hash != second.output_hash


def test_the_output_hash_changes_when_an_input_changes():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    first = evaluate_run(version, _inputs())
    moved = _inputs()
    moved.items["long_term_debt"].value = Decimal("451")
    assert first.output_hash != evaluate_run(version, moved).output_hash


def test_component_order_does_not_change_the_result():
    forward = _formula()
    reversed_components = ebitda_formula(list(reversed(forward.components)))
    data = _inputs()
    for scenario in ("S0", "S1", "S2", "S3"):
        assert (
            evaluate_ebitda(forward, data, scenario).value
            == evaluate_ebitda(reversed_components, data, scenario).value
        )


def test_canonical_hash_ignores_key_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
