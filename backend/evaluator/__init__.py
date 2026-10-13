"""Deterministic covenant arithmetic: formula language, caps, scenarios, verdicts."""

from backend.evaluator.approval import Blocker, approval_blockers, can_approve
from backend.evaluator.covenant import (
    DEFAULT_TIGHT_BAND,
    CovenantResult,
    evaluate_covenant,
    worst_verdict,
)
from backend.evaluator.inputs import FactRef, ItemInput, PeriodInputs, analyst_input
from backend.evaluator.reasons import Reason
from backend.evaluator.run import RunResult, canonical_hash, evaluate_run
from backend.evaluator.scenarios import EbitdaResult, evaluate_ebitda
from backend.evaluator.schema import (
    CapPool,
    Component,
    Covenant,
    EbitdaFormula,
    FormulaVersion,
    Span,
)

__all__ = [
    "Blocker",
    "CapPool",
    "Component",
    "Covenant",
    "CovenantResult",
    "DEFAULT_TIGHT_BAND",
    "EbitdaFormula",
    "EbitdaResult",
    "FactRef",
    "FormulaVersion",
    "ItemInput",
    "PeriodInputs",
    "Reason",
    "RunResult",
    "Span",
    "analyst_input",
    "approval_blockers",
    "can_approve",
    "canonical_hash",
    "evaluate_covenant",
    "evaluate_ebitda",
    "evaluate_run",
    "worst_verdict",
]
