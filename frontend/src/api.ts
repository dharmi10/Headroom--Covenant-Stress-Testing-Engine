/* The backend is the only thing the browser talks to.
 *
 * data.sec.gov sends no CORS headers, so every EDGAR fetch happens server
 * side; this module is a thin typed wrapper over the Python API and holds no
 * covenant logic of its own. Every number it carries is already a string,
 * because the backend computes in exact decimals and a JSON number would
 * quietly turn 4.75 into a float.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export type Verdict = "PASS" | "TIGHT" | "BREACH" | "NOT_COMPUTABLE";

export interface Span {
  start: number;
  end: number;
  quote: string;
}

export interface Review {
  decision: "accepted" | "edited" | "rejected" | "excluded_unsupported";
  note: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
}

export interface Component {
  item: string;
  sign: "+" | "-";
  category: string;
  cap_pool: string | null;
  clause: string | null;
  reason: string | null;
  span: Span;
  review: Review | null;
}

export interface CapPool {
  kind: string;
  fixed_amount: string | null;
  pct: string | null;
  basis: string | null;
  label: string | null;
  span: Span | null;
}

export interface ScheduleStep {
  from: string;
  threshold: string;
}

export interface CovenantSpec {
  id: string;
  name: string | null;
  type: "max_ratio" | "min_ratio";
  numerator: unknown;
  denominator: unknown;
  schedule: ScheduleStep[];
  span: Span;
  reason: string | null;
  review: Review | null;
}

export interface DefinitionNode {
  term: string;
  depth: number;
  span: Span | null;
  resolved: boolean;
  references: string[];
}

export interface FormulaVersion {
  deal_id: string;
  version: number;
  status: "draft" | "approved" | "superseded";
  source_hash: string;
  approved_by: string | null;
  approved_at: string | null;
  ebitda: {
    formula_id: string;
    version: number;
    status: string;
    source_hash: string;
    drafted_with: {
      model: string;
      prompt_version: string;
      attempts: number;
    } | null;
    base: { item: string; clause: string | null; span: Span; reason: string | null };
    components: Component[];
    cap_pools: Record<string, CapPool>;
  };
  covenants: CovenantSpec[];
  definitions: Record<string, DefinitionNode>;
}

export interface Blocker {
  code: string;
  target: string;
  detail: string;
}

export interface DealStatus {
  deal_id: string;
  borrower: string;
  entity_name: string | null;
  cik: string;
  exhibit_url: string;
  source_hash: string;
  agreement_chars: number;
  latest_version: number | null;
  latest_status: string | null;
  approved_version: number | null;
  blockers: Blocker[];
  mapping_coverage: { verified: number; required: number } | null;
}

export interface DealSummary {
  deal_id: string;
  borrower: string;
  entity_name: string | null;
  cik: string;
  created_at: string;
}

export interface MappingRecord {
  formula_item: string;
  concept: string | null;
  status: "review_required" | "verified" | "unavailable";
  period_type: "duration" | "instant";
  rationale: string | null;
  mapping_version: number;
  analyst_value: string | null;
  decided_by: string | null;
  decided_at: string | null;
  candidates: { concept: string; reported: boolean }[];
}

export interface Reason {
  code: string;
  item: string | null;
  detail: string | null;
}

export interface FactRef {
  concept: string;
  value: string;
  unit: string;
  period_type: string;
  start: string | null;
  end: string | null;
  instant: string | null;
  form: string | null;
  accession: string | null;
  filed: string | null;
  origin: string;
  transformation: string | null;
}

export interface ItemInput {
  item: string;
  value: string | null;
  reason: string | null;
  origin: string | null;
  concept: string | null;
  mapping_version: number | null;
  facts: FactRef[];
  note: string | null;
}

export interface PoolTrace {
  pool: string;
  kind: string;
  basis: string | null;
  e_before_pool: string;
  a_requested: string;
  cap: string;
  allowed: string;
  binding: boolean;
  attribution: { component: string; item: string; requested: string; allowed: string }[];
}

export interface ComponentLine {
  component: string;
  item: string;
  sign: string;
  category: string;
  cap_pool: string | null;
  clause: string | null;
  requested: string | null;
  contribution: string | null;
  state: string;
  detail: string | null;
}

export interface SideTrace {
  value: string | null;
  gross: string | null;
  cash_netted: string | null;
  cash_available: string | null;
  cash_cap: string | null;
  parts: { item: string; value: string }[];
  reasons: Reason[];
}

export interface CovenantResult {
  covenant_id: string;
  covenant_name: string | null;
  covenant_type: string;
  scenario: string;
  threshold: string | null;
  ebitda: string | null;
  ratio: string | null;
  ratio_display: string | null;
  cushion: string | null;
  cushion_display: string | null;
  headroom_ebitda: string | null;
  debt_capacity: string | null;
  verdict: Verdict;
  side: SideTrace;
  reasons: Reason[];
  disclosures: Reason[];
}

export interface ScenarioResult {
  id: string;
  label: string;
  ebitda: {
    scenario: string;
    label: string;
    ebitda: string | null;
    base: string | null;
    e_outside_pools: string | null;
    pools: PoolTrace[];
    components: ComponentLine[];
    reasons: Reason[];
    disclosures: Reason[];
  };
  covenants: CovenantResult[];
}

export interface StepAttribution {
  from: string;
  to: string;
  delta: string | null;
  contributions: { component: string; item: string; delta: string }[];
}

export interface RunResult {
  deal_id: string;
  test_date: string;
  formula_version: number;
  source_hash: string;
  evaluator_version: string;
  tight_band: string;
  headline_verdict: Verdict;
  adjustment_dependence: string | null;
  adjustment_dependence_display: string | null;
  scenarios: ScenarioResult[];
  steps: StepAttribution[];
  inputs: {
    deal_id: string;
    test_date: string;
    quarters: string[];
    items: Record<string, ItemInput>;
  };
  mapping_versions: Record<string, number>;
  reasons: Reason[];
  output_hash: string;
}

export interface StoredRun {
  run_id: number;
  test_date: string;
  formula_version: number;
  evaluator_version: string;
  output_hash: string;
  superseded: boolean;
  headline_verdict: Verdict | null;
  created_at: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly blockers: Blocker[];

  constructor(status: number, message: string, blockers: Blocker[] = []) {
    super(message);
    this.status = status;
    this.blockers = blockers;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let message = response.status + " " + response.statusText;
    let blockers: Blocker[] = [];
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        message = detail.message ?? message;
        blockers = detail.blockers ?? [];
      } else if (Array.isArray(body?.detail)) {
        message = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
      }
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    throw new ApiError(response.status, message, blockers);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  deals: () => request<DealSummary[]>("/deals"),

  deal: (id: string) => request<DealStatus>("/deals/" + id),

  createDeal: (body: {
    deal_id: string;
    borrower: string;
    cik: string;
    exhibit_url: string;
  }) => request<DealStatus>("/deals", { method: "POST", body: JSON.stringify(body) }),

  agreement: (id: string, start: number, end: number) =>
    request<{ start: number; end: number; total: number; text: string }>(
      "/deals/" + id + "/agreement?start=" + start + "&end=" + end,
    ),

  versions: (id: string) =>
    request<{ version: number; status: string; created_at: string; source_hash: string }[]>(
      "/deals/" + id + "/formula",
    ),

  version: (id: string, version: number) =>
    request<{
      version: number;
      status: string;
      formula: FormulaVersion;
      compile_log: { calls: unknown[] } | null;
      blockers: Blocker[];
    }>("/deals/" + id + "/formula/" + version),

  compile: (id: string) =>
    request<{ version: number; status: string; formula: FormulaVersion; blockers: Blocker[] }>(
      "/deals/" + id + "/compile",
      { method: "POST", body: JSON.stringify({}) },
    ),

  review: (
    id: string,
    version: number,
    body: {
      reviewer: string;
      decisions: {
        target: string;
        decision: string;
        note?: string | null;
        item?: string | null;
        sign?: string | null;
        category?: string | null;
        cap_pool?: string | null;
      }[];
    },
  ) =>
    request<{ version: number; formula: FormulaVersion; blockers: Blocker[] }>(
      "/deals/" + id + "/formula/" + version + "/review",
      { method: "POST", body: JSON.stringify(body) },
    ),

  approve: (id: string, version: number, reviewer: string) =>
    request<{ version: number; status: string }>(
      "/deals/" + id + "/formula/" + version + "/approve",
      { method: "POST", body: JSON.stringify({ reviewer }) },
    ),

  newDraft: (id: string, version: number) =>
    request<{ version: number; status: string }>(
      "/deals/" + id + "/formula/" + version + "/new-draft",
      { method: "POST" },
    ),

  mappings: (id: string) =>
    request<{ deal_id: string; formula_version: number; records: MappingRecord[] }>(
      "/deals/" + id + "/mappings",
    ),

  decideMapping: (
    id: string,
    item: string,
    body: {
      status: string;
      rationale: string;
      concept?: string | null;
      analyst_value?: string | null;
      reviewer?: string | null;
    },
  ) =>
    request<MappingRecord>("/deals/" + id + "/mappings/" + item, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  testDates: (id: string) =>
    request<{ test_dates: string[] }>("/deals/" + id + "/test-dates"),

  runs: (id: string) => request<StoredRun[]>("/deals/" + id + "/runs"),

  run: (id: string, runId: number) =>
    request<{ run_id: number; superseded: boolean; result: RunResult }>(
      "/deals/" + id + "/runs/" + runId,
    ),

  createRun: (id: string, testDate: string) =>
    request<{ run_id: number; output_hash: string; result: RunResult }>(
      "/deals/" + id + "/runs",
      { method: "POST", body: JSON.stringify({ test_date: testDate }) },
    ),
};
