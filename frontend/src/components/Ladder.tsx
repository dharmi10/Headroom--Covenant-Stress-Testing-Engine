/* The scenario ladder.
 *
 * S0 to S3 is a real sequence: each rung removes one class of adjustment and
 * recalculates the whole formula, so the descent itself is the information.
 * Each bar shows the leverage ratio against its covenant threshold, with the
 * threshold drawn as a rule the bar can cross - the moment a bar passes the
 * rule is the moment the covenant fails, and that is visible without reading
 * a single number.
 *
 * The steps between rungs name what was removed and what it cost.
 */

import type { CovenantResult, RunResult, ScenarioResult } from "../api";
import { exact, itemLabel, percent, ratio } from "../format";
import { Verdict } from "./Verdict";
import { TraceValue } from "./Trace";

const QUESTIONS: Record<string, string> = {
  S0: "Does it pass on the agreement's own terms?",
  S1: "Does it pass without projected savings?",
  S2: "Does it pass without one-time charges too?",
  S3: "Does it pass on plain EBITDA?",
};

export function Ladder({
  run,
  covenantId,
  onTraceEbitda,
  onTraceCovenant,
  showSteps = true,
}: {
  run: RunResult;
  covenantId: string;
  onTraceEbitda: (scenario: ScenarioResult) => void;
  onTraceCovenant: (covenant: CovenantResult, scenario: ScenarioResult) => void;
  showSteps?: boolean;
}) {
  const rows = run.scenarios;
  const covenantOf = (scenario: ScenarioResult) =>
    scenario.covenants.find((row) => row.covenant_id === covenantId);
  const isMax = rows.map(covenantOf).find(Boolean)?.covenant_type === "max_ratio";

  // One scale for every rung, so the bars are comparable down the column.
  const ratios = rows
    .map((scenario) => covenantOf(scenario)?.ratio)
    .filter((value): value is string => Boolean(value))
    .map(Number);
  const thresholds = rows
    .map((scenario) => covenantOf(scenario)?.threshold)
    .filter((value): value is string => Boolean(value))
    .map(Number);
  const scale = Math.max(1, ...ratios, ...thresholds) * 1.12;

  const stepsByPair = new Map(run.steps.map((step) => [step.from + ">" + step.to, step]));

  return (
    <ol className="ladder">
      {rows.map((scenario, index) => {
        const covenant = covenantOf(scenario);
        const previous = index > 0 ? rows[index - 1] : null;
        const step = previous ? stepsByPair.get(previous.id + ">" + scenario.id) : undefined;
        return (
          <li key={scenario.id}>
            {showSteps && step ? <StepRow step={step} /> : null}
            <div className="rung">
              <div>
                <div className="rung-label">
                  <span className="rung-id">{scenario.id}</span>
                  {scenario.label}
                </div>
                <span className="rung-question">{QUESTIONS[scenario.id] ?? ""}</span>
              </div>

              <div
                className="rung-bar"
                role="img"
                aria-label={
                  covenant?.ratio
                    ? ratio(covenant.ratio) +
                      " against a " +
                      ratio(covenant.threshold) +
                      (isMax ? " ceiling" : " floor")
                    : "not computable"
                }
              >
                {covenant?.ratio ? (
                  <i
                    className={covenant.verdict === "BREACH" ? "over" : undefined}
                    style={{ width: Math.min(100, (Number(covenant.ratio) / scale) * 100) + "%" }}
                  />
                ) : null}
                {covenant?.threshold ? (
                  <u style={{ left: (Number(covenant.threshold) / scale) * 100 + "%" }} />
                ) : null}
              </div>

              <div className="num">
                {covenant ? (
                  <TraceValue onOpen={() => onTraceCovenant(covenant, scenario)}>
                    {ratio(covenant.ratio)}
                  </TraceValue>
                ) : (
                  "—"
                )}
              </div>

              <div className="num">
                <TraceValue onOpen={() => onTraceEbitda(scenario)}>
                  {scenario.ebitda.ebitda === null ? "—" : exact(scenario.ebitda.ebitda)}
                </TraceValue>
              </div>

              <div className="num">
                {covenant ? <Verdict verdict={covenant.verdict} /> : <Verdict verdict="NOT_COMPUTABLE" />}
                {covenant?.cushion ? (
                  <div className="state">{percent(covenant.cushion)} cushion</div>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function StepRow({
  step,
}: {
  step: { from: string; to: string; delta: string | null; contributions: { item: string; delta: string }[] };
}) {
  if (step.delta === null) {
    return (
      <div className="step">
        <b>{step.from} → {step.to}</b>
        <span>not comparable: one of the two is not computable</span>
      </div>
    );
  }
  if (Number(step.delta) === 0) {
    return (
      <div className="step">
        <b>{step.from} → {step.to}</b>
        <span>no change: the agreement permits nothing in this class</span>
      </div>
    );
  }
  return (
    <div className="step">
      <b>{step.from} → {step.to}</b>
      <span className="delta">{exact(step.delta)}</span>
      <span>
        from{" "}
        {step.contributions
          .slice(0, 3)
          .map((row) => itemLabel(row.item))
          .join(", ")}
        {step.contributions.length > 3 ? " and " + (step.contributions.length - 3) + " more" : ""}
      </span>
    </div>
  );
}
