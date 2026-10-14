/* Screen 1. How much protection does the lender actually have?
 *
 * The screen opens with the finding stated in a sentence, because that is what
 * an analyst would write in a credit memo, and puts the evidence directly
 * under it. A large number with a gradient behind it would say less.
 */

import type { CovenantResult, DealStatus, RunResult, ScenarioResult } from "../api";
import { asOf, basisLabel, exact, percent, ratio } from "../format";
import { Ladder } from "../components/Ladder";
import { Verdict } from "../components/Verdict";
import { TraceValue } from "../components/Trace";

export function DealOverview({
  deal,
  run,
  onTraceEbitda,
  onTraceCovenant,
}: {
  deal: DealStatus;
  run: RunResult;
  onTraceEbitda: (scenario: ScenarioResult) => void;
  onTraceCovenant: (covenant: CovenantResult, scenario: ScenarioResult) => void;
}) {
  const contractual = run.scenarios.find((row) => row.id === "S0");
  const standard = run.scenarios.find((row) => row.id === "S3");
  const leverage = contractual?.covenants.find((row) => row.covenant_type === "max_ratio");
  const standardLeverage = standard?.covenants.find((row) => row.covenant_type === "max_ratio");
  const covenantIds = contractual?.covenants.map((row) => row.covenant_id) ?? [];

  return (
    <>
      <section className={"finding verdict-" + run.headline_verdict}>
        <h1>{headline(run, leverage, standardLeverage)}</h1>
        <dl className="finding-meta">
          <div>
            <dt>Borrower</dt>
            <dd>{deal.entity_name ?? deal.borrower}</dd>
          </div>
          <div>
            <dt>Test period</dt>
            <dd>TTM to {asOf(run.test_date)}</dd>
          </div>
          <div>
            <dt>Contractual verdict</dt>
            <dd>
              <Verdict verdict={run.headline_verdict} />
            </dd>
          </div>
          {leverage?.debt_capacity ? (
            <div>
              <dt>Debt capacity</dt>
              <dd>
                <TraceValue onOpen={() => onTraceCovenant(leverage, contractual!)}>
                  {exact(leverage.debt_capacity)}
                </TraceValue>{" "}
                <span className="muted">under this covenant only</span>
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Reporting basis</dt>
            <dd>
              Figures {basisLabel(run.reporting_basis)}
              {run.reporting_basis === "as_originally_reported" ? (
                <>
                  {" "}
                  <span className="muted">restatement inside the window</span>
                </>
              ) : null}
            </dd>
          </div>
          <div>
            <dt>Formula</dt>
            <dd>version {run.formula_version}</dd>
          </div>
        </dl>
      </section>

      <p className="disclaimer">
        These figures are an analyst's estimate built from public filings, not the borrower's
        official compliance numbers, and the scenarios show sensitivity to the adjustments the
        agreement permits rather than any claim about true earnings. Every figure is taken on
        one reporting basis &mdash; {basisLabel(run.reporting_basis)} &mdash; because a window
        that mixed a restatement with the figures it replaced would subtract numbers measured
        differently.
        {run.reporting_basis_note ? " " + run.reporting_basis_note : null}
      </p>

      {run.reasons.length > 0 ? (
        <div className="notice bad">
          {run.reasons.map((reason, index) => (
            <div key={index}>{reason.detail ?? reason.code}</div>
          ))}
        </div>
      ) : null}

      {covenantIds.map((covenantId) => {
        const sample = contractual?.covenants.find((row) => row.covenant_id === covenantId);
        return (
          <section className="panel" key={covenantId}>
            <div className="panel-head">
              <div>
                <h2>{sample?.covenant_name ?? covenantId}</h2>
                <p>
                  {sample?.covenant_type === "max_ratio"
                    ? "Tested quarterly on the last four quarters combined; the borrower must stay at or below the threshold."
                    : "Tested quarterly on the last four quarters combined; the borrower must stay at or above the threshold."}
                </p>
              </div>
              <div className="small muted">
                Threshold {ratio(sample?.threshold ?? null)} · tight band{" "}
                {percent(run.tight_band, 0)}
              </div>
            </div>
            <div className="panel-body flush">
              <Ladder
                run={run}
                covenantId={covenantId}
                onTraceEbitda={onTraceEbitda}
                onTraceCovenant={onTraceCovenant}
                showSteps={false}
              />
            </div>
          </section>
        );
      })}
    </>
  );
}

function headline(
  run: RunResult,
  leverage: CovenantResult | undefined,
  standardLeverage: CovenantResult | undefined,
) {
  if (run.headline_verdict === "NOT_COMPUTABLE" || !leverage || !leverage.ratio) {
    return (
      <>
        The contractual test cannot be computed from public filings yet. The inputs it is
        missing are listed on the audit trail, and nothing has been assumed to be zero.
      </>
    );
  }
  const dependence = run.adjustment_dependence;
  const word =
    leverage.verdict === "PASS" ? "Compliant" : leverage.verdict === "TIGHT" ? "Tight" : "In breach";
  return (
    <>
      {word} at <b>{ratio(leverage.ratio)}</b> against a {ratio(leverage.threshold)} covenant, with{" "}
      <b>{percent(leverage.cushion)}</b> of cushion.
      {dependence ? (
        <>
          {" "}
          <b>{percent(dependence)}</b> of that covenant EBITDA comes from discretionary
          adjustments
          {standardLeverage?.ratio ? (
            <>
              ; on plain EBITDA the ratio is {ratio(standardLeverage.ratio)} and the cushion is{" "}
              {percent(standardLeverage.cushion)}.
            </>
          ) : (
            "."
          )}
        </>
      ) : null}
    </>
  );
}
