"""Measure the compiler against the hand-written golden formulas.

Span verification proves a citation exists. Whether the clause was read
correctly is a separate question, and this script is the answer to it: it runs
real compiles against every golden agreement and compares each result with the
hand-written formula clause by clause, reporting accuracy per field with its
dataset size and listing every failure.

Run the same agreement several times with ``--runs``. Current Claude models
reject the sampling parameters, so temperature 0 is not available and
determinism cannot be assumed; measuring the same agreement repeatedly is how
run-to-run stability is established rather than claimed.

The number is reported, never asserted. A compiler metric that the test suite
enforces is a metric nobody will ever let fall, which is not the same as a
metric that is true.

Needs Anthropic credentials. Run with::

    python -m scripts.measure_compiler                  # one run per deal
    python -m scripts.measure_compiler --runs 5         # five runs per deal
    python -m scripts.measure_compiler --replay         # score saved compiles
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.compiler.aggregate import aggregate, markdown_report
from backend.compiler.draft import (
    DEFAULT_MODEL,
    CompileError,
    anthropic_client,
    compile_agreement,
    save_transcript,
)
from backend.compiler.prompt import PROMPT_VERSION
from backend.compiler.score import Scorecard, score_components
from backend.evaluator.schema import FormulaVersion
from backend.pipeline import load_golden

GOLDEN_ROOT = Path("data/golden")
TRANSCRIPTS = Path("data/transcripts")
REPORT = Path("docs/evaluation/compiler.md")


def golden_deals() -> list[Path]:
    """Every golden deal with a hand-written formula and an agreement text."""
    found = [
        folder
        for folder in sorted(GOLDEN_ROOT.iterdir())
        if folder.is_dir()
        and (folder / "formula.json").exists()
        and (folder / "agreement.txt").exists()
    ]
    return found


def transcript_path(deal_id: str, run: int) -> Path:
    return TRANSCRIPTS / (deal_id + ".run" + str(run) + ".json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs", type=int, default=1, help="compiles per agreement (default 1)"
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="score the saved compiles instead of calling the model again",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--deal", default=None, help="one deal id instead of all of them")
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()

    folders = golden_deals()
    if args.deal:
        folders = [folder for folder in folders if folder.name == args.deal]
    if not folders:
        print("no golden deals found under", GOLDEN_ROOT)
        return 1

    client = None
    if not args.replay:
        try:
            client = anthropic_client()
        except CompileError as exc:
            print(exc)
            print()
            print("Nothing was measured. Options:")
            print("  - set ANTHROPIC_API_KEY and run again, or")
            print("  - run with --replay to score compiles recorded earlier.")
            print()
            print("No figure is written to", args.report, "without a real compile:")
            print("an unmeasured accuracy is worse than an absent one.")
            return 2

    cards: list[tuple[str, int, Scorecard]] = []
    calls: list[dict] = []
    model_used = args.model or DEFAULT_MODEL
    hard_failures: list[str] = []

    for folder in folders:
        deal, golden, _records = load_golden(folder)
        deal_id = deal["deal_id"]
        text = (folder / "agreement.txt").read_text(encoding="utf-8")

        for run in range(1, args.runs + 1):
            path = transcript_path(deal_id, run)
            if args.replay:
                if not path.exists():
                    print("no transcript at", path, "- skipping")
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                drafted = FormulaVersion.model_validate(payload["version"])
                run_calls = payload.get("calls", [])
                if run_calls:
                    model_used = run_calls[0].get("model", model_used)
            else:
                print(
                    "compiling",
                    deal["borrower"],
                    "run",
                    str(run) + "/" + str(args.runs),
                    "-",
                    len(text),
                    "characters",
                )
                try:
                    result = compile_agreement(
                        text, deal_id=deal_id, client=client, model=args.model
                    )
                except CompileError as exc:
                    # A compile that cannot produce a validated draft at all is
                    # a result too, and a worse one than a wrong clause.
                    print("  the compile FAILED:", exc)
                    hard_failures.append(deal_id + " run " + str(run) + ": " + str(exc))
                    continue
                save_transcript(path, result)
                drafted = result.version
                run_calls = [log.as_dict() for log in result.logs]
                if run_calls:
                    model_used = run_calls[0].get("model", model_used)

            calls.extend(run_calls)
            card = score_components(golden, drafted)
            cards.append((deal_id, run - 1, card))
            print()
            print(card.report())
            print()

    if not cards:
        print("nothing was scored")
        return 1

    measurement = aggregate(
        cards, model=model_used, prompt_version=PROMPT_VERSION, calls=calls
    )

    note = ""
    if hard_failures:
        note = "\n".join(
            ["**Compiles that produced no validated draft at all:**", ""]
            + ["- " + line for line in hard_failures]
        )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown_report(measurement, note=note), encoding="utf-8")
    json_path = report_path.with_suffix(".json")
    json_path.write_text(
        json.dumps(measurement.as_dict(), indent=2) + "\n", encoding="utf-8"
    )

    print("=" * 72)
    print("agreements        ", measurement.n_agreements)
    print("distinct clauses  ", measurement.n_clauses)
    print("observations      ", measurement.n_component_observations)
    whole = measurement.components_whole
    print(
        "components correct",
        str(whole.correct) + "/" + str(whole.total),
        "" if whole.accuracy is None else format(whole.accuracy * 100, ".1f") + "%",
    )
    print("unstable clauses  ", len(measurement.unstable_clauses))
    print("report            ", report_path)
    print("scorecard         ", json_path)
    if hard_failures:
        print()
        print("FAILED COMPILES:")
        for line in hard_failures:
            print("  -", line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
