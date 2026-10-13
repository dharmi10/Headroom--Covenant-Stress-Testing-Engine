"""Metric arithmetic, threshold boundaries and the degenerate EBITDA cases."""

from __future__ import annotations

from decimal import Decimal

from backend.evaluator.covenant import evaluate_covenant
from backend.evaluator.scenarios import evaluate_ebitda
from tests.conftest import (
    component,
    coverage_covenant,
    ebitda_formula,
    inputs,
    leverage_covenant,
)


def test_primer_example_matches_the_prd(primer_formula, primer_inputs):
    """Debt 450 over EBITDA 100 at a 5.00x cap: 4.50x, 10% cushion, 50 capacity."""
    ebitda = evaluate_ebitda(primer_formula, primer_inputs, "S0")
    assert ebitda.value == Decimal("100")

    result = evaluate_covenant(leverage_covenant("5.00"), ebitda, primer_inputs)
    assert result.ratio == Decimal("4.5")
    assert result.cushion == Decimal("0.10")
    assert result.debt_capacity == Decimal("50")
    assert result.verdict == "TIGHT"  # 10% sits inside the default 15% band


def test_one_add_back_doubles_the_apparent_cushion(primer_inputs):
    """The observation the whole project rests on: 15 of restructuring lifts
    EBITDA from 100 to 115 and the cushion from 10% to about 22%."""
    formula = ebitda_formula(
        [
            component("interest_expense", "standard"),
            component("income_tax_expense", "standard"),
            component("depreciation_amortization", "standard"),
            component("restructuring_charges", "one_time"),
        ]
    )
    data = inputs(
        {
            "net_income": "40",
            "interest_expense": "25",
            "income_tax_expense": "10",
            "depreciation_amortization": "25",
            "restructuring_charges": "15",
            "long_term_debt": "450",
        }
    )
    contractual = evaluate_ebitda(formula, data, "S0")
    standard_only = evaluate_ebitda(formula, data, "S3")
    assert contractual.value == Decimal("115")
    assert standard_only.value == Decimal("100")

    loose = evaluate_covenant(leverage_covenant("5.00"), contractual, data)
    tight = evaluate_covenant(leverage_covenant("5.00"), standard_only, data)
    assert loose.cushion.quantize(Decimal("0.0001")) == Decimal("0.2174")
    assert tight.cushion == Decimal("0.10")


def test_exact_threshold_boundary_is_a_pass_not_a_breach():
    """Debt exactly at T x E must pass; a rounded ratio must not decide it."""
    formula = ebitda_formula([component("interest_expense", "standard")])
    # EBITDA 300, threshold 4.75 => the covenant allows debt of exactly 1425.
    data = inputs({"net_income": "200", "interest_expense": "100", "long_term_debt": "1425"})
    ebitda = evaluate_ebitda(formula, data, "S0")
    assert ebitda.value == Decimal("300")
    result = evaluate_covenant(leverage_covenant("4.75"), ebitda, data)
    assert result.cushion == 0
    assert result.verdict == "TIGHT"

    over = inputs({"net_income": "200", "interest_expense": "100", "long_term_debt": "1425.01"})
    breached = evaluate_covenant(
        leverage_covenant("4.75"), evaluate_ebitda(formula, over, "S0"), over
    )
    assert breached.verdict == "BREACH"
    assert breached.cushion < 0


def test_tight_band_boundary_is_exact():
    """A cushion of exactly 15% is a PASS, one cent of debt more is TIGHT."""
    formula = ebitda_formula([component("interest_expense", "standard")])
    # E = 100, T = 5 => cushion 15% at debt = 0.85 * 500 = 425.
    at_band = inputs({"net_income": "60", "interest_expense": "40", "long_term_debt": "425"})
    result = evaluate_covenant(
        leverage_covenant("5.00"), evaluate_ebitda(formula, at_band, "S0"), at_band
    )
    assert result.cushion == Decimal("0.15")
    assert result.verdict == "PASS"

    just_over = inputs({"net_income": "60", "interest_expense": "40", "long_term_debt": "425.01"})
    nudged = evaluate_covenant(
        leverage_covenant("5.00"), evaluate_ebitda(formula, just_over, "S0"), just_over
    )
    assert nudged.verdict == "TIGHT"


def test_zero_and_negative_ebitda_breach_a_leverage_test():
    formula = ebitda_formula([component("interest_expense", "standard")])
    for net_income, interest in (("-100", "100"), ("-200", "100")):
        data = inputs(
            {"net_income": net_income, "interest_expense": interest, "long_term_debt": "450"}
        )
        ebitda = evaluate_ebitda(formula, data, "S0")
        assert ebitda.value is not None and ebitda.value <= 0
        result = evaluate_covenant(leverage_covenant("5.00"), ebitda, data)
        assert result.verdict == "BREACH"
        assert result.ratio is None  # no finite leverage against non-positive EBITDA


def test_net_debt_applies_the_cash_cap():
    """"less unrestricted cash not exceeding $75,000,000" caps the netting."""
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs(
        {
            "net_income": "60",
            "interest_expense": "40",
            "long_term_debt": "500",
            "cash_and_equivalents": "120",
        }
    )
    covenant = leverage_covenant(
        "5.00", net_of_cash={"enabled": True, "cap": "75"}
    )
    result = evaluate_covenant(covenant, evaluate_ebitda(formula, data, "S0"), data)
    assert result.side.gross == Decimal("500")
    assert result.side.netted == Decimal("75")  # not the full 120
    assert result.side.value == Decimal("425")
    assert result.ratio == Decimal("4.25")


def test_uncapped_netting_uses_all_the_cash():
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs(
        {
            "net_income": "60",
            "interest_expense": "40",
            "long_term_debt": "500",
            "cash_and_equivalents": "120",
        }
    )
    covenant = leverage_covenant("5.00", net_of_cash={"enabled": True})
    result = evaluate_covenant(covenant, evaluate_ebitda(formula, data, "S0"), data)
    assert result.side.value == Decimal("380")


def test_interest_coverage_cushion():
    """Coverage 100 / 25 = 4.0x against a 3.00x floor: cushion 25%."""
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs({"net_income": "75", "interest_expense": "25"})
    result = evaluate_covenant(
        coverage_covenant("3.00"), evaluate_ebitda(formula, data, "S0"), data
    )
    assert result.ratio == Decimal("4")
    assert result.cushion == Decimal("0.25")
    assert result.verdict == "PASS"


def test_coverage_breaches_when_interest_outruns_ebitda():
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs({"net_income": "20", "interest_expense": "40"})
    result = evaluate_covenant(
        coverage_covenant("3.00"), evaluate_ebitda(formula, data, "S0"), data
    )
    assert result.ratio == Decimal("1.5")
    assert result.verdict == "BREACH"
    assert result.cushion < 0


def test_step_down_schedule_picks_the_threshold_in_force():
    covenant = leverage_covenant(
        schedule=[
            {"from": "2025-03-31", "threshold": "5.00"},
            {"from": "2026-03-31", "threshold": "4.75"},
        ]
    )
    import datetime as dt

    assert covenant.threshold_at(dt.date(2024, 12, 31)) is None
    assert covenant.threshold_at(dt.date(2025, 3, 31)) == Decimal("5.00")
    assert covenant.threshold_at(dt.date(2025, 12, 31)) == Decimal("5.00")
    assert covenant.threshold_at(dt.date(2026, 3, 31)) == Decimal("4.75")
    assert covenant.threshold_at(dt.date(2030, 6, 30)) == Decimal("4.75")


def test_threshold_before_the_schedule_starts_is_not_computable():
    formula = ebitda_formula([component("interest_expense", "standard")])
    data = inputs(
        {"net_income": "60", "interest_expense": "40", "long_term_debt": "100"},
        test_date="2024-12-31",
    )
    covenant = leverage_covenant(schedule=[{"from": "2025-03-31", "threshold": "5.00"}])
    result = evaluate_covenant(covenant, evaluate_ebitda(formula, data, "S0"), data)
    assert result.verdict == "NOT_COMPUTABLE"
    assert [r.code for r in result.reasons] == ["incompatible_facts"]
