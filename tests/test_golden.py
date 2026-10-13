"""The golden deal, end to end, against hand-computed expected results.

The expected numbers in ``expected.json`` come from ``scripts/hand_calc.py``,
which writes the covenant arithmetic out longhand and never imports the
evaluator. This test is therefore a comparison between two implementations,
not a snapshot of the code against itself.

The run replays the committed input snapshot, so it needs no network and the
golden set stays reproducible from a fresh clone.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.agreement.normalise import text_hash
from backend.compiler.spans import verify_version
from backend.evaluator.approval import approval_blockers
from backend.evaluator.inputs import PeriodInputs
from backend.evaluator.run import evaluate_run
from backend.pipeline import coverage, load_golden
from backend.edgar.mapping import required_items

GOLDEN = Path("data/golden/teleflex-2025q2")


@pytest.fixture(scope="module")
def golden():
    deal, version, records = load_golden(GOLDEN)
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    snapshot = json.loads((GOLDEN / "ttm_inputs.json").read_text(encoding="utf-8"))
    inputs = PeriodInputs.model_validate(
        {
            "deal_id": snapshot["deal_id"],
            "test_date": snapshot["test_date"],
            "quarters": snapshot["quarters"],
            "items": snapshot["items"],
        }
    )
    return deal, version, records, expected, inputs


@pytest.fixture(scope="module")
def run(golden):
    _, version, records, _, inputs = golden
    mapping_versions = {
        item: records[item].mapping_version
        for item in required_items(version)
        if item in records
    }
    return evaluate_run(version, inputs, mapping_versions=mapping_versions)


def test_the_agreement_text_still_hashes_to_the_approved_source(golden):
    """An approved formula is bound to the text it was approved against."""
    _, version, _, _, _ = golden
    text = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
    assert text_hash(text) == version.source_hash


def test_every_span_in_the_golden_formula_verifies(golden):
    _, version, _, _, _ = golden
    text = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
    failures = verify_version(version, text)
    assert failures == [], [failure.as_dict() for failure in failures]


def test_the_golden_formula_is_approvable(golden):
    _, version, _, _, _ = golden
    assert approval_blockers(version) == []
    assert version.status == "approved"
    assert version.approved_by is not None


def test_every_required_mapping_is_verified(golden):
    _, version, records, _, _ = golden
    verified, required = coverage(version, records)
    assert (verified, required) == (12, 12)


def test_the_agreement_permits_no_pro_forma_add_back(golden):
    """Teleflex's definition has no projected cost savings clause, so S0 and
    S1 have to be identical. The scenario ladder still works; the first step
    is simply empty."""
    _, version, _, expected, _ = golden
    categories = {component.category for component in version.ebitda.components}
    assert "pro_forma" not in categories
    assert expected["scenarios"]["S0"]["ebitda"] == expected["scenarios"]["S1"]["ebitda"]


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3"])
def test_scenario_ebitda_matches_the_hand_calculation(run, golden, scenario):
    _, _, _, expected, _ = golden
    result = run.ebitda[scenario]
    assert result.reasons == [], [reason.as_dict() for reason in result.reasons]
    assert result.value == Decimal(expected["scenarios"][scenario]["ebitda"])
    assert result.e_base == Decimal(expected["scenarios"][scenario]["e_outside_pools"])


@pytest.mark.parametrize("scenario", ["S0", "S1", "S2", "S3"])
@pytest.mark.parametrize("covenant_id", ["max_total_net_leverage", "min_interest_coverage"])
def test_covenant_results_match_the_hand_calculation(run, golden, scenario, covenant_id):
    _, _, _, expected, _ = golden
    want = expected["scenarios"][scenario]["covenants"][covenant_id]
    got = run.covenants[scenario][covenant_id]
    assert got.verdict == want["verdict"]
    assert got.ratio == Decimal(want["ratio"])
    assert got.cushion == Decimal(want["cushion"])
    assert got.headroom_amount == Decimal(want["headroom_ebitda"])
    if covenant_id == "max_total_net_leverage":
        assert got.side.value == Decimal(expected["net_debt"])
        assert got.debt_capacity == Decimal(want["debt_capacity"])


def test_the_restructuring_cap_is_measured_before_its_own_pool(run, golden):
    """Clause (b)(x) is capped at 5% of EBITDA calculated without giving
    effect to that clause, so the cap is 5% of the pre-pool total."""
    _, _, _, expected, _ = golden
    pool = run.ebitda["S0"].pools["clause_x"]
    assert pool.basis == "before_pool"
    assert pool.e == Decimal(expected["scenarios"]["S0"]["e_outside_pools"])
    assert pool.cap == Decimal(expected["scenarios"]["S0"]["pool_cap"])
    assert pool.allowed == Decimal(expected["scenarios"]["S0"]["pool_allowed"])
    assert pool.binding is False  # 3.9m of restructuring against a 32.7m cap


def test_the_excluded_pension_pool_contributes_nothing(run):
    """Clause (b)(xi) was excluded as unsupported, so its fixed cap pool has
    no items in any scenario and adds nothing."""
    assert "clause_xi" not in run.ebitda["S0"].pools


def test_adjustment_dependence_matches_the_hand_calculation(run, golden):
    _, _, _, expected, _ = golden
    assert run.adjustment_dependence == Decimal(expected["adjustment_dependence"])


def test_the_headline_is_pass_but_plain_ebitda_is_tight(run):
    """The finding the deal exists to show: comfortable on the agreement's own
    terms, two percent from a breach on plain EBITDA."""
    assert run.headline_verdict == "PASS"
    contractual = run.covenants["S0"]["max_total_net_leverage"]
    standard = run.covenants["S3"]["max_total_net_leverage"]
    assert contractual.verdict == "PASS"
    assert standard.verdict == "TIGHT"
    assert contractual.cushion > Decimal("0.44")
    assert standard.cushion < Decimal("0.03")


def test_exclusions_are_disclosed_on_every_scenario_that_would_include_them(run):
    disclosures = run.ebitda["S0"].disclosures
    assert disclosures, "the reviewer excluded unsupported clauses; S0 must say so"
    assert {reason.code for reason in disclosures} == {"unsupported_adjustment"}


def test_the_run_is_reproducible(golden):
    _, version, records, _, inputs = golden
    hashes = {evaluate_run(version, inputs).output_hash for _ in range(10)}
    assert len(hashes) == 1


def test_the_input_snapshot_keeps_provenance_for_every_reported_fact(golden):
    _, _, _, _, inputs = golden
    for item, resolved in inputs.items.items():
        assert resolved.usable, item
        assert resolved.facts, item
        if resolved.origin == "analyst":
            assert resolved.note
            continue
        for ref in resolved.facts:
            assert ref.accession, item
            assert ref.form in ("10-Q", "10-K", "10-Q/A", "10-K/A"), item


def test_the_test_date_is_a_real_quarter_end(golden):
    deal, _, _, _, inputs = golden
    assert inputs.test_date == dt.date.fromisoformat(deal["test_date"])
    assert len(inputs.quarters) == 4
