/* Screen 4. Can I independently verify this number?
 *
 * Everything a second person needs to rebuild the run by hand: the clauses, the
 * filing facts with their accession numbers, the mapping decisions, each cap
 * pool's working, the versions, and the output hash.
 */

import type { FormulaVersion, MappingRecord, RunResult, StoredRun } from "../api";
import { asOf, exact, itemLabel, percent, reasonLabel, shortHash } from "../format";
import { FactTable } from "../components/FactTable";

export function AuditTrail({
  run,
  version,
  mappings,
  storedRuns,
}: {
  run: RunResult;
  version: FormulaVersion | null;
  mappings: MappingRecord[];
  storedRuns: StoredRun[];
}) {
  const analystSourced = Object.values(run.inputs.items).filter(
    (input) => input.origin === "analyst",
  );

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Versions this run was built from</h2>
            <p>
              The same formula version, mapping versions and evaluator against the same facts must
              always produce the output hash below.
            </p>
          </div>
        </div>
        <div className="panel-body">
          <dl className="kv">
            <div>
              <dt>Deal</dt>
              <dd>{run.deal_id}</dd>
            </div>
            <div>
              <dt>Test date</dt>
              <dd>
                {asOf(run.test_date)} · TTM of {run.inputs.quarters.join(", ") || "—"}
              </dd>
            </div>
            <div>
              <dt>Formula</dt>
              <dd>
                version {run.formula_version}
                {version?.approved_by ? ", approved by " + version.approved_by : ""}
                {version?.approved_at ? " on " + version.approved_at.slice(0, 10) : ""}
              </dd>
            </div>
            <div>
              <dt>Agreement</dt>
              <dd className="hash">{run.source_hash}</dd>
            </div>
            <div>
              <dt>Evaluator</dt>
              <dd>{run.evaluator_version}</dd>
            </div>
            <div>
              <dt>Tight band</dt>
              <dd>{percent(run.tight_band, 0)}</dd>
            </div>
            <div>
              <dt>Output hash</dt>
              <dd className="hash">{run.output_hash}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Every input, with its provenance</h2>
            <p>
              {analystSourced.length > 0
                ? analystSourced.length +
                  " of these came from an analyst rather than a reported concept, because no single reported concept carries the contractual item. Each one names the filings it was built from."
                : "Every input came from a reported concept."}
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th className="num">Value</th>
                <th>Source</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(run.inputs.items)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([item, input]) => (
                  <tr key={item}>
                    <td>{itemLabel(item)}</td>
                    <td className="num">
                      {input.value === null ? (
                        <span className="state">{reasonLabel(input.reason ?? "")}</span>
                      ) : (
                        exact(input.value)
                      )}
                    </td>
                    <td className="small">
                      {input.concept ?? (input.origin === "analyst" ? "analyst value" : "—")}
                      <span className="state" style={{ display: "block" }}>
                        {input.origin ?? "—"}
                        {input.mapping_version ? " · mapping v" + input.mapping_version : ""}
                      </span>
                    </td>
                    <td className="small">
                      {input.note ? (
                        <div style={{ marginBottom: 4, maxWidth: "60ch" }}>{input.note}</div>
                      ) : null}
                      <FactTable facts={input.facts} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Cap pools, scenario by scenario</h2>
            <p>
              For each pool: the EBITDA it was measured against, the amount requested, the cap, the
              amount allowed, and how the allowance was attributed across the pool's clauses.
              Attribution changes only this trace, never the EBITDA total.
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          <table>
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Pool</th>
                <th>Rule</th>
                <th className="num">Measured on (E)</th>
                <th className="num">Requested (A)</th>
                <th className="num">Cap (C)</th>
                <th className="num">Allowed</th>
              </tr>
            </thead>
            <tbody>
              {run.scenarios.flatMap((scenario) =>
                scenario.ebitda.pools.map((pool) => (
                  <tr key={scenario.id + pool.pool}>
                    <td>{scenario.id}</td>
                    <td>{pool.pool}</td>
                    <td className="small">
                      {pool.kind}
                      {pool.basis ? " · " + pool.basis.replace("_", " ") : ""}
                      {pool.binding ? (
                        <span className="pill flag" style={{ marginLeft: 6 }}>
                          binding
                        </span>
                      ) : null}
                    </td>
                    <td className="num">{exact(pool.e_before_pool)}</td>
                    <td className="num">{exact(pool.a_requested)}</td>
                    <td className="num">{exact(pool.cap)}</td>
                    <td className="num">{exact(pool.allowed)}</td>
                  </tr>
                )),
              )}
              {run.scenarios.every((scenario) => scenario.ebitda.pools.length === 0) ? (
                <tr>
                  <td colSpan={7} className="muted">
                    No cap pool had any item in any scenario.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Mapping decisions</h2>
            <p>Each item's source, status and the rationale the analyst wrote for it.</p>
          </div>
        </div>
        <div className="panel-body flush">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Source</th>
                <th>Status</th>
                <th>Version</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((record) => (
                <tr key={record.formula_item}>
                  <td>{itemLabel(record.formula_item)}</td>
                  <td className="small">
                    {record.analyst_value !== null
                      ? "analyst value " + record.analyst_value
                      : (record.concept ?? "—")}
                  </td>
                  <td className="small">{record.status.replace(/_/g, " ")}</td>
                  <td className="small">v{record.mapping_version}</td>
                  <td className="small" style={{ maxWidth: "70ch" }}>
                    {record.rationale ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {version ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Source clauses</h2>
              <p>
                Every component's citation, already checked against the agreement text at those
                offsets. Span verification proves the text exists; the review decision beside it is
                what addresses whether it was read correctly.
              </p>
            </div>
          </div>
          <div className="panel-body flush">
            <table>
              <thead>
                <tr>
                  <th>Clause</th>
                  <th>Item</th>
                  <th>Offsets</th>
                  <th>Quote</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {version.ebitda.components.map((component) => (
                  <tr key={component.item + (component.clause ?? component.span.start)}>
                    <td className="clause-ref">{component.clause ?? "—"}</td>
                    <td>{itemLabel(component.item)}</td>
                    <td className="small muted">
                      {component.span.start}–{component.span.end}
                    </td>
                    <td className="small" style={{ maxWidth: "52ch" }}>
                      {component.span.quote}
                    </td>
                    <td className="small">
                      {component.review?.decision.replace(/_/g, " ") ?? "not reviewed"}
                      {component.review?.note ? (
                        <span className="state" style={{ display: "block" }}>
                          {component.review.note}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Stored runs</h2>
            <p>
              A run built on a formula version that was later replaced is kept and marked
              superseded, so the number someone acted on last quarter is still there.
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Test date</th>
                <th>Formula</th>
                <th>Verdict</th>
                <th>Output hash</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {storedRuns.map((stored) => (
                <tr key={stored.run_id}>
                  <td>#{stored.run_id}</td>
                  <td>{asOf(stored.test_date)}</td>
                  <td>v{stored.formula_version}</td>
                  <td>{stored.headline_verdict ?? "—"}</td>
                  <td className="small hash">{shortHash(stored.output_hash)}</td>
                  <td className="small">{stored.superseded ? "superseded" : "current"}</td>
                </tr>
              ))}
              {storedRuns.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No runs stored yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
