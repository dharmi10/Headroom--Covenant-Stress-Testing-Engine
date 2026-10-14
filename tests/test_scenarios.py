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
            component("stock_based_compensation", "accepted_non_cash"),
            component("restructuring_charges", "one_time"),
            component("run_rate_cost_savings", "aggressive_pro_forma"),
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
    """The ladder under the credit taxonomy. S2 removes what a lender would
    argue with - projected savings, and "one-time" charges that recur - and S3
    additionally removes the genuinely non-recurring one-time charges, leaving
    standard plus accepted non-cash."""
    formula, data = _formula(), _inputs()
    values = {s: evaluate_ebitda(formula, data, s).value for s in ("S0", "S1", "S2", "S3")}
    assert values["S0"] == Decimal("135")  # 100 + 8 SBC + 15 one-time + 12 savings
    assert values["S1"] == Decimal("123")  # drops the projected savings
    assert values["S2"] == Decimal("123")  # the one-time charge does not recur here
    assert values["S3"] == Decimal("108")  # drops the one-time charge as well


def test_a_one_time_charge_the_filings_show_recurring_is_dropped_by_s2():
    """The same formula, with the restructuring charge promoted because the
    borrower reported it in most of the last four fiscal years. Nothing about
    the contract changed; the evidence did."""
    formula, data = _formula(), _inputs()
    recurring = {
        "restructuring_charges": "reported in 4 of the last 4 fiscal years",
    }
    values = {
        s: evaluate_ebitda(formula, data, s, recurring=recurring).value
        for s in ("S0", "S1", "S2", "S3")
    }
    assert values["S0"] == Decimal("135")
    assert values["S1"] == Decimal("123")
    assert values["S2"] == Decimal("108")  # the recurring charge is now aggressive
    assert values["S3"] == Decimal("108")

    line = next(
        row
        for row in evaluate_ebitda(formula, data, "S2", recurring=recurring).lines
        if row.item == "restructuring_charges"
    )
    assert line.category == "one_time"  # what the contract says
    assert line.judged_as == "aggressive_recurring"  # what the filings say
    assert line.state == "excluded_by_scenario"
    assert "4 of the last 4" in (line.detail or "")


def test_only_the_promotable_category_is_promoted():
    """Recurrence says nothing about depreciation. A finding against an item in
    another category must not move it."""
    formula, data = _formula(), _inputs()
    recurring = {"depreciation_amortization": "reported every year, as it would be"}
    line = next(
        row
        for row in evaluate_ebitda(formula, data, "S3", recurring=recurring).lines
        if row.item == "depreciation_amortization"
    )
    assert line.judged_as == "standard"
    assert line.state == "included"


def test_scenarios_are_strictly_ordered_for_positive_add_backs():
    formula, data = _formula(), _inputs()
    values = [evaluate_ebitda(formula, data, s).value for s in ("S0", "S1", "S2", "S3")]
    assert values == sorted(values, reverse=True)


def test_deductions_are_subtracted_in_the_scenarios_that_include_them():
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("gain_on_asset_sales", "accepted_non_cash", sign="-"),
        ]
    )
    data = inputs(
        {"net_income": "100", "interest_expense": "20", "gain_on_asset_sales": "30"}
    )
    assert evaluate_ebitda(formula, data, "S0").value == Decimal("90")
    # S3 keeps standard and accepted non-cash, and this deduction is accepted
    # non-cash, so it survives into S3 under the credit taxonomy.
    assert evaluate_ebitda(formula, data, "S3").value == Decimal("90")


def test_aggressive_dependence_is_the_share_resting_on_aggressive_add_backs():
    """``(S0 - S2) / S0``. With no recurring charge, only the projected savings
    are aggressive: (135 - 123) / 135."""
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, _inputs())
    assert run.aggressive_dependence.quantize(Decimal("0.000001")) == Decimal("0.088889")
    assert run.as_dict()["aggressive_dependence_display"] == "0.0889"


def test_aggressive_dependence_rises_when_a_one_time_charge_recurs():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(
        version,
        _inputs(),
        recurrence={
            "restructuring_charges": {
                "item": "restructuring_charges",
                "recurs": True,
                "evidence": "reported in 4 of the last 4 fiscal years",
            }
        },
    )
    # (135 - 108) / 135: the savings and the recurring charge together.
    assert run.aggressive_dependence.quantize(Decimal("0.000001")) == Decimal("0.200000")
    assert run.recurrence[0]["item"] == "restructuring_charges"


def test_the_accepted_non_cash_share_is_reported_separately():
    """Stock compensation is accepted non-cash, so it belongs in its own
    figure rather than in the aggressive one: 8 / 135."""
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, _inputs())
    assert run.accepted_non_cash_share.quantize(Decimal("0.000001")) == Decimal("0.059259")
    assert run.as_dict()["arguably_accepted_items"] == ["stock_based_compensation"]


def test_step_attribution_names_the_components_behind_each_fall():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(version, _inputs())
    by_pair = {(s.from_scenario, s.to_scenario): s for s in run.steps}

    savings = by_pair[("S0", "S1")]
    assert savings.delta == Decimal("-12")
    assert [(item, delta) for _, item, delta in savings.contributions] == [
        ("run_rate_cost_savings", Decimal("-12"))
    ]

    # Nothing is aggressive-recurring here, so S1 to S2 is an empty step. The
    # ladder still has four rungs and the UI says which ones are empty.
    aggressive = by_pair[("S1", "S2")]
    assert aggressive.delta == Decimal("0")
    assert aggressive.contributions == []

    one_time = by_pair[("S2", "S3")]
    assert one_time.delta == Decimal("-15")
    assert [item for _, item, _ in one_time.contributions] == ["restructuring_charges"]


def test_step_attribution_moves_the_charge_when_it_recurs():
    version = formula_version(_formula(), [leverage_covenant("5.00")])
    run = evaluate_run(
        version,
        _inputs(),
        recurrence={
            "restructuring_charges": {
                "item": "restructuring_charges",
                "recurs": True,
                "evidence": "reported in 4 of the last 4 fiscal years",
            }
        },
    )
    by_pair = {(s.from_scenario, s.to_scenario): s for s in run.steps}
    assert by_pair[("S1", "S2")].delta == Decimal("-15")
    assert [item for _, item, _ in by_pair[("S1", "S2")].contributions] == [
        "restructuring_charges"
    ]
    assert by_pair[("S2", "S3")].delta == Decimal("0")


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


def test_the_output_hash_does_not_depend_on_the_ambient_decimal_context():
    """A run is stored and rehashed from whatever thread serves the request,
    so nothing in the canonical payload may depend on the ambient decimal
    precision. This caught dec_str using Decimal.normalize, which rounds to
    the context precision and silently changed the hash."""
    import decimal
    from concurrent.futures import ThreadPoolExecutor

    version = formula_version(_formula(), [leverage_covenant("5.00")])

    def run_at(precision: int) -> tuple[str, str]:
        decimal.getcontext().prec = precision
        result = evaluate_run(version, _inputs())
        return result.output_hash, result.as_dict()["aggressive_dependence"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run_at, [12, 28, 60]))
    assert len({row[0] for row in results}) == 1
    assert len({row[1] for row in results}) == 1


def test_dec_str_is_exact_and_strips_only_trailing_zeros():
    from decimal import Decimal, localcontext

    from backend.evaluator.money import dec_str

    with localcontext() as ctx:
        ctx.prec = 6
        long_value = Decimal("0.4264456597491684089754007310088347986987")
        assert dec_str(long_value) == "0.4264456597491684089754007310088347986987"
    assert dec_str(Decimal("1.2300")) == "1.23"
    assert dec_str(Decimal("-0.000")) == "0"
    assert dec_str(Decimal("1E+3")) == "1000"
    assert dec_str(Decimal("0")) == "0"
