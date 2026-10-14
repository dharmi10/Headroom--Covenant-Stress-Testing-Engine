"""Rebuild the golden deal's resolved input snapshot.

``ttm_inputs.json`` is what ``tests/test_golden.py`` replays, so it has to be
regenerable rather than hand-maintained: a change to how a TTM window is built
has to be able to show up here. The snapshot is built from the committed
``companyfacts.json`` fixture, so it is reproducible from a fresh clone and
offline.

The figures are cross-checked by ``scripts/verify_teleflex.py``, which imports
nothing from ``backend`` and re-derives each quarter from the raw companyfacts
JSON. Run both after changing anything about fact selection.

Run with::

    python -m scripts.build_inputs
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from backend.edgar.facts import parse_company_facts
from backend.pipeline import (
    DealSources,
    load_golden,
    run_quarter,
    write_inputs_snapshot,
)
from scripts.seed_golden import FixtureEdgar

GOLDEN = Path("data/golden/teleflex-2025q2")


def main() -> None:
    deal, version, records = load_golden(GOLDEN)
    payload = FixtureEdgar().company_facts(deal["cik"])
    sources = DealSources(
        cik=deal["cik"],
        facts_by_concept=parse_company_facts(payload),
        entity_name=payload.get("entityName"),
    )
    run = run_quarter(
        version, sources, records, dt.date.fromisoformat(deal["test_date"])
    )

    target = GOLDEN / "ttm_inputs.json"
    write_inputs_snapshot(target, run)
    print("wrote", target)
    print("basis", run.inputs.basis)
    print("quarters", ", ".join(run.inputs.quarters))
    for item, resolved in sorted(run.inputs.items.items()):
        print(
            "   ",
            item.ljust(32),
            (str(resolved.value) if resolved.usable else resolved.reason).rjust(16),
            resolved.origin or "",
        )
    for scenario in ("S0", "S1", "S2", "S3"):
        print(scenario, run.ebitda[scenario].value)
    print("output_hash", run.output_hash)

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["basis"] == run.inputs.basis


if __name__ == "__main__":
    main()
