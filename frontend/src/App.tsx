/* The shell.
 *
 * Four screens in the order an analyst asks the questions, and each tab says
 * which question it answers. State is deliberately plain: one deal, one
 * formula version, one run. There is no router because there is one deal on
 * screen at a time and a URL for each screen would not help the analyst do
 * anything they cannot do here.
 */

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type {
  CovenantResult,
  DealStatus,
  DealSummary,
  FormulaVersion,
  MappingRecord,
  RunResult,
  ScenarioResult,
  StoredRun,
} from "./api";
import { asOf } from "./format";
import { AuditTrail } from "./screens/AuditTrail";
import { DealOverview } from "./screens/DealOverview";
import { FormulaReview } from "./screens/FormulaReview";
import { StressTesting } from "./screens/StressTesting";
import {
  TraceDrawer,
  covenantTrace,
  ebitdaTrace,
} from "./components/Trace";
import type { TraceTarget } from "./components/Trace";
import { NewDeal } from "./screens/NewDeal";

type Screen = "overview" | "review" | "stress" | "audit";

const TABS: { id: Screen; label: string; question: string }[] = [
  { id: "overview", label: "Deal", question: "How much protection does the lender have?" },
  { id: "review", label: "Formula review", question: "Does the formula match the contract?" },
  { id: "stress", label: "Stress testing", question: "How much rests on adjustments?" },
  { id: "audit", label: "Audit trail", question: "Can I verify this myself?" },
];

export default function App() {
  const [deals, setDeals] = useState<DealSummary[]>([]);
  const [dealId, setDealId] = useState<string | null>(null);
  const [deal, setDeal] = useState<DealStatus | null>(null);
  const [version, setVersion] = useState<FormulaVersion | null>(null);
  const [blockers, setBlockers] = useState<DealStatus["blockers"]>([]);
  const [mappings, setMappings] = useState<MappingRecord[]>([]);
  const [run, setRun] = useState<RunResult | null>(null);
  const [storedRuns, setStoredRuns] = useState<StoredRun[]>([]);
  const [testDates, setTestDates] = useState<string[]>([]);
  const [screen, setScreen] = useState<Screen>("overview");
  const [trace, setTrace] = useState<TraceTarget | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const loadDeals = useCallback(async () => {
    const rows = await api.deals();
    setDeals(rows);
    setDealId((current) => current ?? rows[0]?.deal_id ?? null);
    return rows;
  }, []);

  useEffect(() => {
    loadDeals()
      .catch((exc: Error) => setError(exc.message))
      .finally(() => setLoading(false));
  }, [loadDeals]);

  const loadDeal = useCallback(async (id: string) => {
    setError(null);
    const status = await api.deal(id);
    setDeal(status);
    setBlockers(status.blockers);

    const target = status.approved_version ?? status.latest_version;
    if (target === null) {
      setVersion(null);
      setMappings([]);
      setRun(null);
      setStoredRuns([]);
      setTestDates([]);
      return;
    }
    const detail = await api.version(id, target);
    setVersion(detail.formula);
    setBlockers(detail.blockers);

    try {
      const mapped = await api.mappings(id);
      setMappings(mapped.records);
    } catch {
      setMappings([]);
    }

    const runs = await api.runs(id);
    setStoredRuns(runs);
    const current = runs.find((row) => !row.superseded) ?? runs[0];
    if (current) {
      const full = await api.run(id, current.run_id);
      setRun(full.result);
    } else {
      setRun(null);
    }

    try {
      const dates = await api.testDates(id);
      setTestDates(dates.test_dates.slice(-8).reverse());
    } catch {
      setTestDates([]);
    }
  }, []);

  useEffect(() => {
    if (!dealId) return;
    setLoading(true);
    loadDeal(dealId)
      .catch((exc: Error) => setError(exc.message))
      .finally(() => setLoading(false));
  }, [dealId, loadDeal]);

  const refresh = useCallback(() => {
    if (dealId) void loadDeal(dealId).catch((exc: Error) => setError(exc.message));
  }, [dealId, loadDeal]);

  async function runQuarter(testDate: string) {
    if (!dealId) return;
    setRunning(true);
    setError(null);
    try {
      const created = await api.createRun(dealId, testDate);
      setRun(created.result);
      setStoredRuns(await api.runs(dealId));
      setScreen("overview");
    } catch (exc) {
      if (exc instanceof ApiError) {
        setError(
          exc.message +
            (exc.blockers.length ? ": " + exc.blockers.map((b) => b.detail).join("; ") : ""),
        );
      } else {
        setError(String(exc));
      }
    } finally {
      setRunning(false);
    }
  }

  const onTraceEbitda = (scenario: ScenarioResult) => setTrace(ebitdaTrace(scenario));
  const onTraceCovenant = (covenant: CovenantResult, scenario: ScenarioResult) =>
    setTrace(covenantTrace(covenant, scenario, run?.tight_band ?? "0.15"));

  return (
    <div className="shell">
      <header className="masthead">
        <div className="masthead-top">
          <div className="wordmark">
            Headroom
            <span>covenant sensitivity for private credit</span>
          </div>
          <div className="deal-picker">
            {deals.length > 0 ? (
              <>
                <label htmlFor="deal">Deal</label>
                <select
                  id="deal"
                  value={dealId ?? ""}
                  onChange={(event) => setDealId(event.target.value)}
                >
                  {deals.map((row) => (
                    <option key={row.deal_id} value={row.deal_id}>
                      {row.entity_name ?? row.borrower}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            {testDates.length > 0 ? (
              <>
                <label htmlFor="quarter">Quarter</label>
                <select
                  id="quarter"
                  value={run?.test_date ?? ""}
                  disabled={running}
                  onChange={(event) => void runQuarter(event.target.value)}
                >
                  {run ? null : <option value="">Select…</option>}
                  {testDates.map((date) => (
                    <option key={date} value={date}>
                      {asOf(date)}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
          </div>
        </div>
        <nav className="tabs" aria-label="Screens">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className="tab"
              aria-current={screen === tab.id ? "page" : undefined}
              onClick={() => setScreen(tab.id)}
            >
              {tab.label}
              <span className="tab-question">{tab.question}</span>
            </button>
          ))}
        </nav>
      </header>

      <main>
        {error ? <div className="notice bad">{error}</div> : null}
        {loading ? <p className="loading">Loading…</p> : null}

        {!loading && deals.length === 0 ? (
          <NewDeal
            onCreated={async (id) => {
              await loadDeals();
              setDealId(id);
            }}
          />
        ) : null}

        {!loading && deal && screen === "overview" ? (
          run ? (
            <DealOverview
              deal={deal}
              run={run}
              onTraceEbitda={onTraceEbitda}
              onTraceCovenant={onTraceCovenant}
            />
          ) : (
            <NoRunYet deal={deal} testDates={testDates} running={running} onRun={runQuarter} />
          )
        ) : null}

        {!loading && deal && screen === "review" ? (
          version ? (
            <FormulaReview
              dealId={deal.deal_id}
              version={version}
              blockers={blockers}
              mappings={mappings}
              testDate={run?.test_date ?? testDates[0] ?? null}
              onChanged={refresh}
            />
          ) : (
            <NoFormulaYet dealId={deal.deal_id} onChanged={refresh} />
          )
        ) : null}

        {!loading && deal && screen === "stress" ? (
          run ? (
            <StressTesting
              run={run}
              onTraceEbitda={onTraceEbitda}
              onTraceCovenant={onTraceCovenant}
            />
          ) : (
            <NoRunYet deal={deal} testDates={testDates} running={running} onRun={runQuarter} />
          )
        ) : null}

        {!loading && deal && screen === "audit" ? (
          run ? (
            <AuditTrail
              run={run}
              version={version}
              mappings={mappings}
              storedRuns={storedRuns}
            />
          ) : (
            <NoRunYet deal={deal} testDates={testDates} running={running} onRun={runQuarter} />
          )
        ) : null}
      </main>

      {run ? <TraceDrawer target={trace} run={run} onClose={() => setTrace(null)} /> : null}
    </div>
  );
}

function NoRunYet({
  deal,
  testDates,
  running,
  onRun,
}: {
  deal: DealStatus;
  testDates: string[];
  running: boolean;
  onRun: (date: string) => void;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>No run yet for {deal.entity_name ?? deal.borrower}</h2>
          <p>
            {deal.approved_version === null
              ? "Approve a formula version on the formula review screen first. Nothing computes until a human has approved the formula and the data mappings."
              : "Pick a quarter to run. Only quarters with a full set of four TTM periods are offered."}
          </p>
        </div>
      </div>
      {deal.approved_version !== null && testDates.length > 0 ? (
        <div className="panel-body">
          <div className="actions">
            {testDates.slice(0, 4).map((date) => (
              <button
                key={date}
                type="button"
                className="btn secondary"
                disabled={running}
                onClick={() => onRun(date)}
              >
                Run {asOf(date)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function NoFormulaYet({ dealId, onChanged }: { dealId: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>No formula drafted yet</h2>
          <p>
            Drafting reads the EBITDA definition and the covenant section out of the agreement,
            resolves the terms they refer to, and asks the model for a typed formula. Every span it
            cites is checked against the agreement before you see it.
          </p>
        </div>
      </div>
      <div className="panel-body">
        {error ? <div className="notice bad">{error}</div> : null}
        <div className="actions">
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await api.compile(dealId);
                onChanged();
              } catch (exc) {
                setError(exc instanceof Error ? exc.message : String(exc));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Drafting…" : "Draft the formula"}
          </button>
          <span className="small muted">
            Needs Anthropic credentials on the backend. A hand-written formula can be loaded
            instead with <code>make golden</code>.
          </span>
        </div>
      </div>
    </section>
  );
}
