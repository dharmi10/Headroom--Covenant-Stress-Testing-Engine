"""Trim the golden deal's companyfacts into a committed test fixture.

The full companyfacts response for a large filer is tens of megabytes of
concepts the golden deal never touches. The fixture keeps the concepts the
formula and the mappings actually name, with every row untouched, so the
offline tests exercise the real parsing and TTM code against real filing data.

Run with::

    python -m scripts.build_fixture
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.edgar.client import EdgarClient
from backend.edgar.mapping import candidates_for, required_items
from backend.pipeline import load_formula, load_mappings

GOLDEN = Path("data/golden/teleflex-2025q2")

#: Kept beyond the mapped concepts so the tests can show a candidate that the
#: company does not report, and so the available-test-dates anchor works.
EXTRA_CONCEPTS = ("NetIncomeLoss", "ProfitLoss")


def main() -> None:
    deal = json.loads((GOLDEN / "deal.json").read_text(encoding="utf-8"))
    version = load_formula(GOLDEN / "formula.json")
    records = load_mappings(GOLDEN / "mappings.json")

    wanted: set[str] = set(EXTRA_CONCEPTS)
    for item in required_items(version):
        wanted.update(candidates_for(item))
        record = records.get(item)
        if record is not None and record.concept:
            wanted.add(record.concept)

    payload = EdgarClient().company_facts(deal["cik"])
    concepts = payload.get("facts", {}).get("us-gaap", {})
    kept = {name: body for name, body in sorted(concepts.items()) if name in wanted}

    trimmed = {
        "cik": payload.get("cik"),
        "entityName": payload.get("entityName"),
        "_fixture_note": (
            "Trimmed from the live companyfacts response for CIK "
            + str(deal["cik"])
            + ". Only the concepts the golden formula's mappings name are kept; "
            "every fact row is unmodified."
        ),
        "facts": {"us-gaap": kept},
    }
    target = GOLDEN / "companyfacts.json"
    target.write_text(json.dumps(trimmed, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", target, "with", len(kept), "concepts")
    missing = sorted(wanted - set(kept))
    if missing:
        print("not reported by this filer:", ", ".join(missing))


if __name__ == "__main__":
    main()
