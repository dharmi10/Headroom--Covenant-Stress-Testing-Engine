"""One run: every covenant under every scenario, plus the audit trail.

A run is a pure function of an approved formula version and a resolved set of
inputs. Nothing in here fetches, caches or guesses. The canonical output hash
at the end is the proof: the same version and the same inputs must always
produce the same hash, which is what makes a quarterly rerun checkable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from backend.evaluator.covenant import (
    DEFAULT_TIGHT_BAND,
    CovenantResult,
    evaluate_covenant,
    worst_verdict,
)
from backend.evaluator.inputs import PeriodInputs
from backend.evaluator.money import ZERO, dec_str, div, exact, quantize_percent
from backend.evaluator.reasons import Reason
from backend.evaluator.scenarios import EbitdaResult, evaluate_ebitda
from backend.evaluator.schema import FormulaVersion
from backend.evaluator.vocabulary import (
    AGGRESSIVE_CATEGORIES,
    ARGUABLY_ACCEPTED_ITEMS,
    SCENARIO_IDS,
    SCENARIO_LABELS,
    SCENARIO_QUESTIONS,
)

#: Bumped whenever the arithmetic changes, so a stored run says which rules
#: produced it. Set from the git commit at build time where available.
EVALUATOR_VERSION = "evaluator-1"


@dataclass
class StepAttribution:
    """Why EBITDA fell between two neighbouring scenarios."""

    from_scenario: str
    to_scenario: str
    delta: Decimal | None
    contributions: list[tuple[str, str, Decimal]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "from": self.from_scenario,
            "to": self.to_scenario,
            "delta": None if self.delta is None else dec_str(self.delta),
            "contributions": [
                {"component": key, "item": item, "delta": dec_str(value)}
                for key, item, value in self.contributions
            ],
        }


@dataclass
class RunResult:
    """Everything the UI needs for one deal and one test quarter."""

    deal_id: str
    test_date: dt.date
    formula_version: int
    source_hash: str
    evaluator_version: str
    tight_band: Decimal
    ebitda: dict[str, EbitdaResult]
    covenants: dict[str, dict[str, CovenantResult]]
    #: ``(S0 - S2) / S0``: the share of covenant EBITDA that depends on
    #: add-backs a lender would call aggressive.
    aggressive_dependence: Decimal | None
    #: The share contributed by accepted non-cash charges, reported separately
    #: because it is a different argument: impairment and amortisation of
    #: acquired intangibles are normally allowed, and lumping them in with
    #: projected synergies would overstate the case.
    accepted_non_cash_share: Decimal | None
    steps: list[StepAttribution]
    inputs: PeriodInputs
    mapping_versions: dict[str, int] = field(default_factory=dict)
    reasons: list[Reason] = field(default_factory=list)
    #: One entry per item whose recurrence was tested, with the years behind it.
    recurrence: list[dict[str, object]] = field(default_factory=list)
    output_hash: str = ""

    @property
    def headline_verdict(self) -> str:
        contractual = self.covenants.get("S0", {})
        if not contractual:
            return "NOT_COMPUTABLE"
        return worst_verdict([result.verdict for result in contractual.values()])

    def covenant_ids(self) -> list[str]:
        for scenario in SCENARIO_IDS:
            if scenario in self.covenants:
                return list(self.covenants[scenario])
        return []

    def as_dict(self) -> dict[str, object]:
        return {
            "deal_id": self.deal_id,
            "test_date": self.test_date.isoformat(),
            "formula_version": self.formula_version,
            "source_hash": self.source_hash,
            "evaluator_version": self.evaluator_version,
            "tight_band": dec_str(self.tight_band),
            "headline_verdict": self.headline_verdict,
            # Lifted out of the inputs so the deal screen can say which
            # vintage of the filer's figures it is showing without digging.
            "reporting_basis": self.inputs.basis,
            "reporting_basis_note": self.inputs.basis_note,
            "aggressive_dependence": None
            if self.aggressive_dependence is None
            else dec_str(self.aggressive_dependence),
            "aggressive_dependence_display": None
            if self.aggressive_dependence is None
            else dec_str(quantize_percent(self.aggressive_dependence)),
            "accepted_non_cash_share": None
            if self.accepted_non_cash_share is None
            else dec_str(self.accepted_non_cash_share),
            "accepted_non_cash_share_display": None
            if self.accepted_non_cash_share is None
            else dec_str(quantize_percent(self.accepted_non_cash_share)),
            "arguably_accepted_items": sorted(ARGUABLY_ACCEPTED_ITEMS),
            "recurrence": self.recurrence,
            "scenarios": [
                {
                    "id": scenario,
                    "label": SCENARIO_LABELS[scenario],
                    "question": SCENARIO_QUESTIONS[scenario],
                    "ebitda": self.ebitda[scenario].as_dict(),
                    "covenants": [
                        self.covenants[scenario][cid].as_dict()
                        for cid in self.covenants.get(scenario, {})
                    ],
                }
                for scenario in SCENARIO_IDS
                if scenario in self.ebitda
            ],
            "steps": [step.as_dict() for step in self.steps],
            "inputs": self.inputs.model_dump(mode="json"),
            "mapping_versions": self.mapping_versions,
            "reasons": [reason.as_dict() for reason in self.reasons],
            "output_hash": self.output_hash,
        }

    def canonical_payload(self) -> dict[str, object]:
        """The subset that the output hash covers.

        Deliberately excludes wall-clock time and anything else that changes
        between two identical runs, and deliberately includes every version
        number, so a changed rule changes the hash.
        """
        payload = self.as_dict()
        payload.pop("output_hash", None)
        return payload


def canonical_hash(payload: dict[str, object]) -> str:
    """sha256 of sorted-key JSON with every decimal already a string."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_run(
    version: FormulaVersion,
    inputs: PeriodInputs,
    *,
    tight_band: Decimal = DEFAULT_TIGHT_BAND,
    evaluator_version: str = EVALUATOR_VERSION,
    require_approved: bool = True,
    mapping_versions: dict[str, int] | None = None,
    recurrence: dict[str, object] | None = None,
) -> RunResult:
    """Run every scenario and every covenant for one test quarter.

    ``recurrence`` maps an item to a :class:`RecurrenceFinding`-shaped dict (as
    produced by ``backend/edgar/recurrence.py``). An item whose finding says
    ``recurs`` promotes its ``one_time`` component to ``aggressive_recurring``,
    which is what S2 removes. The findings travel into the stored run and into
    the output hash, so a run says on what evidence it called a charge
    recurring.
    """
    run_reasons: list[Reason] = []
    if require_approved and version.status != "approved":
        run_reasons.append(
            Reason(
                "unapproved_formula",
                item=version.deal_id,
                detail="formula version " + str(version.version) + " is " + version.status,
            )
        )

    ebitda: dict[str, EbitdaResult] = {}
    covenants: dict[str, dict[str, CovenantResult]] = {}

    findings = dict(recurrence or {})
    recurring = {
        item: str(finding.get("evidence") or "")
        for item, finding in findings.items()
        if isinstance(finding, dict) and finding.get("recurs")
    }

    for scenario in SCENARIO_IDS:
        result = evaluate_ebitda(
            version.ebitda, inputs, scenario, recurring=recurring
        )
        if run_reasons:
            result.value = None
            result.reasons = list(run_reasons) + result.reasons
        ebitda[scenario] = result
        covenants[scenario] = {
            covenant.id: evaluate_covenant(covenant, result, inputs, tight_band=tight_band)
            for covenant in version.covenants
        }

    aggressive = _aggressive_dependence(ebitda)
    accepted = _accepted_non_cash_share(ebitda)
    steps = _steps(ebitda)

    run = RunResult(
        deal_id=version.deal_id,
        test_date=inputs.test_date,
        formula_version=version.version,
        source_hash=version.source_hash,
        evaluator_version=evaluator_version,
        tight_band=tight_band,
        ebitda=ebitda,
        covenants=covenants,
        aggressive_dependence=aggressive,
        accepted_non_cash_share=accepted,
        steps=steps,
        inputs=inputs,
        mapping_versions=dict(sorted((mapping_versions or {}).items())),
        reasons=run_reasons,
        recurrence=[findings[item] for item in sorted(findings)],  # type: ignore[misc]
    )
    run.output_hash = canonical_hash(run.canonical_payload())
    return run


def _aggressive_dependence(ebitda: dict[str, EbitdaResult]) -> Decimal | None:
    """``(S0 - S2) / S0``: the share of covenant EBITDA that rests on add-backs
    a lender would call aggressive - projected savings, and "one-time" charges
    the filings show recurring.

    S2 rather than S3 is the comparison on purpose. The old metric measured
    against standard EBITDA, which counted impairment and stock compensation as
    aggressive; a lender does not. ``None`` when either end is not computable
    or S0 is zero.
    """
    contractual = ebitda.get("S0")
    without_aggressive = ebitda.get("S2")
    if contractual is None or without_aggressive is None:
        return None
    if (
        contractual.value is None
        or without_aggressive.value is None
        or contractual.value == 0
    ):
        return None
    with exact():
        return div(contractual.value - without_aggressive.value, contractual.value)


def _accepted_non_cash_share(ebitda: dict[str, EbitdaResult]) -> Decimal | None:
    """The share of S0 contributed by accepted non-cash charges.

    Taken from the components themselves rather than from a difference between
    two scenarios, because no pair of scenarios isolates this class: S2 still
    holds the genuinely non-recurring one-time charges. Signed contributions
    are summed, so a non-cash *gain* deducted under the definition reduces the
    share, which is the honest direction.
    """
    contractual = ebitda.get("S0")
    if contractual is None or contractual.value is None or contractual.value == 0:
        return None
    with exact():
        total = sum(
            (
                line.contribution
                for line in contractual.included()
                if line.judged_as == "accepted_non_cash" and line.contribution is not None
            ),
            ZERO,
        )
        return div(total, contractual.value)


def _steps(ebitda: dict[str, EbitdaResult]) -> list[StepAttribution]:
    """Attribute each scenario-to-scenario fall to the components behind it."""
    steps: list[StepAttribution] = []
    pairs = list(zip(SCENARIO_IDS, SCENARIO_IDS[1:]))
    for first, second in pairs:
        left = ebitda.get(first)
        right = ebitda.get(second)
        if left is None or right is None:
            continue
        delta: Decimal | None = None
        if left.value is not None and right.value is not None:
            with exact():
                delta = right.value - left.value
        before = {line.key: line for line in left.included()}
        after = {line.key: line for line in right.included()}
        contributions: list[tuple[str, str, Decimal]] = []
        for key in sorted(set(before) | set(after)):
            was = before[key].contribution if key in before else ZERO
            now = after[key].contribution if key in after else ZERO
            was = ZERO if was is None else was
            now = ZERO if now is None else now
            if was != now:
                item = (before.get(key) or after[key]).item
                contributions.append((key, item, now - was))
        contributions.sort(key=lambda row: (row[2], row[0]))
        steps.append(
            StepAttribution(
                from_scenario=first,
                to_scenario=second,
                delta=delta,
                contributions=contributions,
            )
        )
    return steps
