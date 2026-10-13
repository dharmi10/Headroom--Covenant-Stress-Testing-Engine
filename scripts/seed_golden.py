"""Load the golden deal into a database and run its quarter.

This is what ``make demo`` runs. It goes through the same service layer the API
uses, so the two gates apply here too: the formula is stored as a draft, then
approved, then every mapping is decided with its rationale, and only then does
a run produce numbers.

By default it works from the committed golden fixtures, so a fresh clone
reproduces the run with no network. ``--live`` fetches the agreement and the
companyfacts from EDGAR instead and checks that the agreement still hashes to
what the approved formula was written against.

Run with::

    python -m scripts.seed_golden            # offline, from data/golden
    python -m scripts.seed_golden --live     # fetch from EDGAR
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from backend.api import service
from backend.api.db import Deal, make_session_factory
from backend.edgar.client import CachedResponse, EdgarClient, OfflineError
from backend.evaluator.schema import FormulaVersion
from backend.pipeline import load_golden

GOLDEN = Path("data/golden/teleflex-2025q2")


class FixtureEdgar(EdgarClient):
    """Serves the committed golden fixtures, so the demo runs offline."""

    def __init__(self) -> None:
        super().__init__(cache_dir="data/cache", allow_network=False)
        self._agreement = (GOLDEN / "agreement.txt").read_text(encoding="utf-8")
        self._facts = json.loads((GOLDEN / "companyfacts.json").read_text(encoding="utf-8"))

    def get(self, url: str, *, refresh: bool = False) -> CachedResponse:
        if url.endswith((".htm", ".html", ".txt")):
            return CachedResponse(
                url=url,
                body=self._agreement.encode("utf-8"),
                content_type="text/plain; charset=utf-8",
                from_cache=True,
            )
        raise OfflineError("the fixture client does not serve " + url)

    def company_facts(self, cik, *, refresh: bool = False) -> dict:  # noqa: ANN001
        return self._facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="fetch from EDGAR instead of the committed fixtures"
    )
    parser.add_argument("--database", default="sqlite:///headroom.db")
    args = parser.parse_args()

    deal_meta, golden_version, golden_mappings = load_golden(GOLDEN)
    context = service.Context(
        edgar=EdgarClient() if args.live else FixtureEdgar(), sources_cache={}
    )
    factory = make_session_factory(args.database)
    session = factory()

    try:
        existing = session.get(Deal, deal_meta["deal_id"])
        if existing is not None:
            print("deal", deal_meta["deal_id"], "already exists; nothing to seed")
            _report(session, context, existing)
            return 0

        print("fetching the agreement" + (" from EDGAR" if args.live else " from data/golden"))
        deal = service.create_deal(
            session,
            context,
            deal_id=deal_meta["deal_id"],
            borrower=deal_meta["borrower"],
            cik=deal_meta["cik"],
            exhibit_url=deal_meta["exhibit_url"],
            notes=deal_meta.get("notes"),
        )
        if deal.source_hash != golden_version.source_hash:
            print("the agreement text no longer matches the approved formula version")
            print("  expected", golden_version.source_hash)
            print("  found   ", deal.source_hash)
            return 1
        print("  agreement:", len(deal.agreement_text), "characters,", deal.source_hash)

        print("storing the hand-written formula as a draft")
        draft = _rewind_to_draft(golden_version)
        service.store_draft(session, deal, draft)

        print("approving the formula version")
        row = service.approve_version(session, deal, draft.version, reviewer="golden set")
        approved = FormulaVersion.model_validate(row.payload)

        print("recording the mapping decisions")
        service.sync_mappings(session, context, deal, approved)
        for item, record in golden_mappings.items():
            service.decide_mapping(
                session,
                deal,
                item,
                status=record.status,
                rationale=record.rationale or "",
                concept=record.concept,
                analyst_value=record.analyst_value,
                analyst_value_as_of=record.analyst_value_as_of,
                reviewer="golden set",
            )
        verified, required = service.coverage(approved, service.mapping_records(session, deal.id))
        print("  mappings verified:", verified, "of", required)

        test_date = dt.date.fromisoformat(deal_meta["test_date"])
        print("running the quarter ending", test_date)
        stored = service.execute_run(session, context, deal, test_date)
        _print_run(stored.payload)
        _compare_with_expected(stored.payload)
        print("\nstored run #" + str(stored.id) + "; start the API with 'make api'")
        return 0
    finally:
        session.close()


def _rewind_to_draft(version: FormulaVersion) -> FormulaVersion:
    """The golden formula as the draft it was before approval.

    Seeding through the real gate rather than inserting an approved row means
    the demo exercises the approval checks instead of bypassing them.
    """
    payload = version.model_dump(mode="json", by_alias=True)
    payload["status"] = "draft"
    payload["approved_by"] = None
    payload["approved_at"] = None
    payload["ebitda"]["status"] = "draft"
    return FormulaVersion.model_validate(payload)


def _print_run(payload: dict) -> None:
    print("\n  scenario                         EBITDA     leverage   cushion   verdict")
    for scenario in payload["scenarios"]:
        ebitda = scenario["ebitda"]["ebitda"]
        leverage = next(
            (c for c in scenario["covenants"] if c["covenant_type"] == "max_ratio"), None
        )
        print(
            "  "
            + (scenario["id"] + " " + scenario["label"]).ljust(32)
            + (ebitda or "n/a").rjust(12)
            + "  "
            + ((leverage or {}).get("ratio_display") or "n/a").rjust(9)
            + "  "
            + ((leverage or {}).get("cushion_display") or "n/a").rjust(8)
            + "  "
            + ((leverage or {}).get("verdict") or "n/a")
        )
    print("\n  adjustment dependence:", payload["adjustment_dependence_display"])
    print("  headline verdict:     ", payload["headline_verdict"])
    print("  output hash:          ", payload["output_hash"])


def _compare_with_expected(payload: dict) -> None:
    expected = json.loads((GOLDEN / "expected.json").read_text(encoding="utf-8"))
    by_id = {scenario["id"]: scenario for scenario in payload["scenarios"]}
    mismatches = []
    for name, want in expected["scenarios"].items():
        got = by_id[name]["ebitda"]["ebitda"]
        if got != want["ebitda"]:
            mismatches.append(name + ": expected " + want["ebitda"] + ", got " + str(got))
    if payload["adjustment_dependence"] != expected["adjustment_dependence"]:
        mismatches.append("adjustment dependence differs from the hand calculation")
    if mismatches:
        print("\n  MISMATCH against the hand calculation:")
        for line in mismatches:
            print("   ", line)
    else:
        print("  matches the independent hand calculation in expected.json")


if __name__ == "__main__":
    sys.exit(main())
