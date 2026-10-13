"""Measure the compiler against the hand-written golden formula.

Span verification proves a citation exists. Whether the clause was read
correctly is a separate question, and this script is the answer to it: it runs
a real compile against the golden agreement and compares the result with the
hand-written formula clause by clause, reporting the accuracy with its dataset
size and listing every failure.

The number is reported, never asserted. A compiler metric that the test suite
enforces is a metric nobody will ever let fall, which is not the same as a
metric that is true.

Needs Anthropic credentials. Run with::

    python -m scripts.measure_compiler
    python -m scripts.measure_compiler --transcript data/transcripts/teleflex.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.compiler.draft import (
    CompileError,
    anthropic_client,
    compile_agreement,
    save_transcript,
)
from backend.compiler.score import score_components
from backend.evaluator.schema import FormulaVersion
from backend.pipeline import load_golden

GOLDEN = Path("data/golden/teleflex-2025q2")
TRANSCRIPT = Path("data/transcripts/teleflex-2025q2.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript",
        default=str(TRANSCRIPT),
        help="where to write the compile, or read it from with --replay",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="score a recorded compile instead of calling the model again",
    )
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    deal, golden, _ = load_golden(GOLDEN)
    text = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")

    if args.replay:
        path = Path(args.transcript)
        if not path.exists():
            print("no transcript at", path)
            return 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        drafted = FormulaVersion.model_validate(payload["version"])
        calls = payload.get("calls", [])
    else:
        try:
            client = anthropic_client()
        except CompileError as exc:
            print(exc)
            print("Run with --replay to score a recorded compile instead.")
            return 2
        print("compiling", deal["borrower"], "-", len(text), "characters of agreement")
        try:
            result = compile_agreement(
                text, deal_id=deal["deal_id"], client=client, model=args.model
            )
        except CompileError as exc:
            print("the compile failed:", exc)
            return 1
        save_transcript(args.transcript, result)
        print("transcript written to", args.transcript)
        drafted = result.version
        calls = [log.as_dict() for log in result.logs]

    card = score_components(golden, drafted)
    print()
    print(card.report())
    print()
    for call in calls:
        print(
            "  call",
            call["target"],
            "- model",
            call["model"],
            "prompt",
            call["prompt_version"],
            "attempts",
            call["attempts"],
        )
        for attempt, errors in enumerate(call.get("errors", []), start=1):
            for error in errors:
                print("      attempt", attempt, "rejected:", error)

    summary = card.as_dict()
    summary["calls"] = calls
    out = Path(args.transcript).with_suffix(".scorecard.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\nscorecard written to", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
