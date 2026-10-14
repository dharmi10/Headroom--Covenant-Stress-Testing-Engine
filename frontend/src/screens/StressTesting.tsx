/* Screen 3. How dependent is compliance on discretionary adjustments?
 *
 * The ladder with its steps answers the question directly: each rung is a
 * full recalculation, and the step between two rungs names the components that
 * explain the fall. The chart repeats the same four figures for people who
 * read shapes faster than columns; it is the echo, not the argument.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CovenantResult, RunResult, ScenarioResult } from "../api";
import { exact, itemLabel, percent, ratio, stateLabel } from "../format";
import { Ladder } from "../components/Ladder";

const INK = "#3c4d66";
const BREACH = "#a42a24";
const RULE = "#d5dce5";

export function StressTesting({
  run,
  onTraceEbitda,
  onTraceCovenant,
}: {
  run: RunResult;
  onTraceEbitda: (scenario: ScenarioResult) => void;
  onTraceCovenant: (covenant: CovenantResult, scenario: ScenarioResult) => void;
}) {
  const covenantIds = run.scenarios[0]?.covenants.map((row) => row.covenant_id) ?? [];
  const contractual = run.scenarios.find((row) => row.id === "S0");

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Aggressive adjustment dependence</h2>
            <p>
              The share of contractual covenant EBITDA that rests on add-backs a lender would
              argue with &mdash; projected savings, and &ldquo;one-time&rdquo; charges the
              filings show recurring &mdash; measured as (S0 &minus; S2) &divide; S0. Accepted
              non-cash charges are counted separately below, because impairment and
              amortisation are normally allowed and lumping them in would overstate the case.
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 26, fontWeight: 600 }}>
              {percent(run.aggressive_dependence)}
            </div>
            <div className="small muted">
              accepted non-cash: {percent(run.accepted_non_cash_share)}
            </div>
            <div className="small muted">
              {contractual?.ebitda.ebitda
                ? exact(contractual.ebitda.ebitda) + " contractual"
                : "not computable"}
            </div>
          </div>
        </div>
      </section>

      {covenantIds.map((covenantId) => {
        const sample = run.scenarios
          .flatMap((scenario) => scenario.covenants)
          .find((row) => row.covenant_id === covenantId);
        const data = run.scenarios.map((scenario) => {
          const covenant = scenario.covenants.find((row) => row.covenant_id === covenantId);
          return {
            name: scenario.id,
            label: scenario.label,
            ratio: covenant?.ratio ? Number(covenant.ratio) : null,
            verdict: covenant?.verdict ?? "NOT_COMPUTABLE",
            cushion: covenant?.cushion ?? null,
          };
        });
        const threshold = sample?.threshold ? Number(sample.threshold) : null;
        const isMax = sample?.covenant_type === "max_ratio";

        return (
          <section className="panel" key={covenantId}>
            <div className="panel-head">
              <div>
                <h2>{sample?.covenant_name ?? covenantId}</h2>
                <p>
                  Each scenario is recalculated from scratch. Removing an item can free cap room for
                  the items that remain, so subtracting from the contractual result would give the
                  wrong number.
                </p>
              </div>
              <div className="small muted">
                {isMax ? "Ceiling" : "Floor"} {ratio(sample?.threshold ?? null)}
              </div>
            </div>
            <div className="panel-body flush">
              <Ladder
                run={run}
                covenantId={covenantId}
                onTraceEbitda={onTraceEbitda}
                onTraceCovenant={onTraceCovenant}
              />
            </div>
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={190}>
                <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke={RULE} vertical={false} />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={{ stroke: RULE }}
                    tick={{ fontSize: 12, fill: INK }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 12, fill: INK }}
                    tickFormatter={(value: number) => value.toFixed(1) + "x"}
                    width={46}
                  />
                  <Tooltip
                    formatter={(value: number) => value.toFixed(2) + "x"}
                    labelFormatter={(name: string) =>
                      name + " " + (data.find((row) => row.name === name)?.label ?? "")
                    }
                    contentStyle={{
                      border: "1px solid " + RULE,
                      borderRadius: 2,
                      fontSize: 13,
                      fontFamily: "inherit",
                    }}
                  />
                  {threshold !== null ? (
                    <ReferenceLine
                      y={threshold}
                      stroke={INK}
                      strokeDasharray="4 3"
                      label={{
                        value: (isMax ? "max " : "min ") + threshold.toFixed(2) + "x",
                        position: "right",
                        fontSize: 11,
                        fill: INK,
                      }}
                    />
                  ) : null}
                  <Bar dataKey="ratio" barSize={46} radius={[1, 1, 0, 0]}>
                    {data.map((row) => (
                      <Cell key={row.name} fill={row.verdict === "BREACH" ? BREACH : INK} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        );
      })}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>What each scenario included</h2>
            <p>
              Every component of the definition, and what happened to it in each scenario. A
              component with no usable input is never treated as zero.
            </p>
          </div>
        </div>
        <div className="panel-body flush">
          <table>
            <thead>
              <tr>
                <th>Clause</th>
                <th>Item</th>
                {run.scenarios.map((scenario) => (
                  <th className="num" key={scenario.id}>
                    {scenario.id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {componentRows(run).map((row) => (
                <tr key={row.key}>
                  <td className="clause-ref">{row.clause ?? "—"}</td>
                  <td>{itemLabel(row.item)}</td>
                  {run.scenarios.map((scenario) => {
                    const line = scenario.ebitda.components.find(
                      (candidate) => candidate.component === row.key,
                    );
                    return (
                      <td className="num" key={scenario.id}>
                        {line && line.state === "included" ? (
                          exact(line.contribution)
                        ) : (
                          <span className="state" title={line ? stateLabel(line.state) : ""}>
                            {line ? short(line.state) : "—"}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function componentRows(run: RunResult) {
  const seen = new Map<string, { key: string; item: string; clause: string | null }>();
  for (const scenario of run.scenarios) {
    for (const line of scenario.ebitda.components) {
      if (!seen.has(line.component)) {
        seen.set(line.component, {
          key: line.component,
          item: line.item,
          clause: line.clause,
        });
      }
    }
  }
  return Array.from(seen.values());
}

function short(state: string): string {
  switch (state) {
    case "excluded_by_scenario":
      return "out of scope";
    case "excluded_by_reviewer":
      return "rejected";
    case "excluded_unsupported":
      return "unsupported";
    case "not_computable":
      return "no input";
    default:
      return state;
  }
}
