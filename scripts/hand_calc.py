"""An independent hand calculation of the golden deal's expected results.

This file deliberately does not import the evaluator. It writes the covenant
arithmetic out longhand from the TTM figures, the way a spreadsheet would, so
that ``expected.json`` is produced by a second implementation rather than by
the code under test. If the two ever disagree, one of them is wrong and the
test says so.

Run with::

    python -m scripts.hand_calc
"""

from __future__ import annotations

import json
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40

OUT = Path("data/golden/teleflex-2025q2/expected.json")

D = Decimal

# TTM figures for the four quarters ending 2025-06-29, each hand-checked
# against the filing it came from (see ttm_inputs.json for accessions).
NET_INCOME = D("191930000")
INCOME_TAX = D("2224000")
INTEREST = D("79902000")
DEP_AMORT = D("102869000")
STOCK_COMP = D("22508000")
IMPAIRMENT = D("253841000")
RESTRUCTURING = D("3900000")
TRANSACTION_COSTS = D("0")
NON_CASH_GAINS = D("0")

LT_DEBT = D("1801645000")
CURRENT_DEBT = D("100000000")
CASH = D("253697000")

LEVERAGE_CAP = D("4.50")
COVERAGE_FLOOR = D("3.50")
TIGHT_BAND = D("0.15")
RESTRUCTURING_CAP_PCT = D("0.05")

# Which categories each scenario keeps.
#   standard : income tax, interest, depreciation and amortisation
#   non_cash : stock compensation, the clause (b)(v) impairment add-back,
#              the clause (c)(ii) non-cash gain deduction
#   one_time : transaction costs, restructuring (capped)
#   pro_forma: none - this agreement permits no projected cost savings
STANDARD = INCOME_TAX + INTEREST + DEP_AMORT
NON_CASH = STOCK_COMP + IMPAIRMENT - NON_CASH_GAINS
ONE_TIME_UNCAPPED = TRANSACTION_COSTS


def scenario(keep_non_cash: bool, keep_one_time: bool) -> dict[str, object]:
    """Recalculate from scratch, exactly as the agreement reads."""
    outside_pool = NET_INCOME + STANDARD
    if keep_non_cash:
        outside_pool += NON_CASH
    if keep_one_time:
        outside_pool += ONE_TIME_UNCAPPED

    # Clause (b)(x): 5% of Consolidated EBITDA calculated without giving
    # effect to the add-back of any item pursuant to that clause.
    if keep_one_time:
        cap = RESTRUCTURING_CAP_PCT * outside_pool
        effective_cap = max(cap, D(0))
        allowed = min(RESTRUCTURING, effective_cap)
    else:
        cap = RESTRUCTURING_CAP_PCT * outside_pool
        effective_cap = max(cap, D(0))
        allowed = D(0)

    ebitda = outside_pool + allowed
    return {
        "e_outside_pools": str(outside_pool),
        "pool_cap": str(cap),
        "pool_requested": str(RESTRUCTURING if keep_one_time else D(0)),
        "pool_allowed": str(allowed),
        "pool_binding": bool(keep_one_time and RESTRUCTURING > effective_cap),
        "ebitda": str(ebitda),
        "_ebitda": ebitda,
    }


def max_ratio(debt: Decimal, ebitda: Decimal) -> dict[str, object]:
    ratio = debt / ebitda
    cushion = D(1) - debt / (LEVERAGE_CAP * ebitda)
    capacity = LEVERAGE_CAP * ebitda - debt
    headroom = ebitda - debt / LEVERAGE_CAP
    if debt > LEVERAGE_CAP * ebitda:
        verdict = "BREACH"
    elif debt > (D(1) - TIGHT_BAND) * LEVERAGE_CAP * ebitda:
        verdict = "TIGHT"
    else:
        verdict = "PASS"
    return {
        "threshold": str(LEVERAGE_CAP),
        "net_debt": str(debt),
        "ratio": str(ratio),
        "ratio_display": str(ratio.quantize(D("0.01"))),
        "cushion": str(cushion),
        "cushion_display": str(cushion.quantize(D("0.0001"))),
        "debt_capacity": str(capacity),
        "headroom_ebitda": str(headroom),
        "verdict": verdict,
    }


def min_ratio(ebitda: Decimal, interest: Decimal) -> dict[str, object]:
    ratio = ebitda / interest
    cushion = D(1) - COVERAGE_FLOOR * interest / ebitda
    headroom = ebitda - COVERAGE_FLOOR * interest
    if COVERAGE_FLOOR * interest > ebitda:
        verdict = "BREACH"
    elif COVERAGE_FLOOR * interest > (D(1) - TIGHT_BAND) * ebitda:
        verdict = "TIGHT"
    else:
        verdict = "PASS"
    return {
        "threshold": str(COVERAGE_FLOOR),
        "interest": str(interest),
        "ratio": str(ratio),
        "ratio_display": str(ratio.quantize(D("0.01"))),
        "cushion": str(cushion),
        "cushion_display": str(cushion.quantize(D("0.0001"))),
        "headroom_ebitda": str(headroom),
        "verdict": verdict,
    }


def main() -> None:
    net_debt = LT_DEBT + CURRENT_DEBT - CASH

    scenarios = {
        "S0": scenario(keep_non_cash=True, keep_one_time=True),
        "S1": scenario(keep_non_cash=True, keep_one_time=True),
        "S2": scenario(keep_non_cash=True, keep_one_time=False),
        "S3": scenario(keep_non_cash=False, keep_one_time=False),
    }

    payload: dict[str, object] = {
        "deal_id": "teleflex-2025q2",
        "test_date": "2025-06-29",
        "tight_band": str(TIGHT_BAND),
        "net_debt": str(net_debt),
        "note": (
            "Computed longhand from the TTM figures, independently of the "
            "evaluator. S0 and S1 are identical because the agreement permits "
            "no pro forma add-back: there are no projected cost savings to "
            "remove."
        ),
        "scenarios": {},
    }

    for name, result in scenarios.items():
        ebitda = result.pop("_ebitda")
        payload["scenarios"][name] = {  # type: ignore[index]
            **result,
            "covenants": {
                "max_total_net_leverage": max_ratio(net_debt, ebitda),
                "min_interest_coverage": min_ratio(ebitda, INTEREST),
            },
        }

    s0 = D(payload["scenarios"]["S0"]["ebitda"])  # type: ignore[index]
    s3 = D(payload["scenarios"]["S3"]["ebitda"])  # type: ignore[index]
    dependence = (s0 - s3) / s0
    payload["adjustment_dependence"] = str(dependence)
    payload["adjustment_dependence_display"] = str(dependence.quantize(D("0.0001")))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("net debt      ", net_debt)
    for name in ("S0", "S1", "S2", "S3"):
        row = payload["scenarios"][name]  # type: ignore[index]
        lev = row["covenants"]["max_total_net_leverage"]
        cov = row["covenants"]["min_interest_coverage"]
        print(
            name,
            "ebitda", row["ebitda"].rjust(12),
            "leverage", lev["ratio_display"].rjust(5) + "x",
            "cushion", lev["cushion_display"].rjust(8),
            lev["verdict"].ljust(6),
            "coverage", cov["ratio_display"].rjust(6) + "x", cov["verdict"],
        )
    print("adjustment dependence", payload["adjustment_dependence_display"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
