/* Display formatting.
 *
 * The backend sends exact decimal strings. Nothing here recomputes a covenant
 * figure: these functions only decide how an already-computed number is read,
 * so a rounding choice in the UI can never change a verdict.
 */

export function money(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  const sign = amount < 0 ? "-" : "";
  const magnitude = Math.abs(amount);
  if (magnitude >= 1_000_000_000) return sign + (magnitude / 1_000_000_000).toFixed(2) + "bn";
  if (magnitude >= 1_000_000) return sign + (magnitude / 1_000_000).toFixed(1) + "m";
  if (magnitude >= 1_000) return sign + (magnitude / 1_000).toFixed(0) + "k";
  return sign + magnitude.toFixed(0);
}

export function exact(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  return amount.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function ratio(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  return amount.toFixed(2) + "x";
}

export function percent(value: string | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  return (amount * 100).toFixed(digits) + "%";
}

export function signedPercent(value: string | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return value;
  const prefix = amount > 0 ? "+" : "";
  return prefix + (amount * 100).toFixed(digits) + "%";
}

export function itemLabel(item: string): string {
  const words = item.split("_");
  const spelled = words
    .map((word) => {
      if (word === "ebitda") return "EBITDA";
      if (word === "ttm") return "TTM";
      return word;
    })
    .join(" ");
  return spelled.charAt(0).toUpperCase() + spelled.slice(1);
}

export function categoryLabel(category: string): string {
  switch (category) {
    case "standard":
      return "Standard";
    case "non_cash":
      return "Non-cash";
    case "one_time":
      return "One-time";
    case "pro_forma":
      return "Pro forma";
    default:
      return category;
  }
}

export function capRule(
  pool: { kind: string; fixed_amount: string | null; pct: string | null; basis: string | null },
): string {
  const basis =
    pool.basis === "after_pool"
      ? "of EBITDA after the pool"
      : pool.basis === "before_pool"
        ? "of EBITDA before the pool"
        : "";
  if (pool.kind === "fixed") return "Capped at " + exact(pool.fixed_amount);
  if (pool.kind === "percentage") return "Capped at " + percent(pool.pct, 0) + " " + basis;
  return (
    "Capped at the greater of " +
    exact(pool.fixed_amount) +
    " and " +
    percent(pool.pct, 0) +
    " " +
    basis
  );
}

export function stateLabel(state: string): string {
  switch (state) {
    case "included":
      return "Included";
    case "excluded_by_scenario":
      return "Out of scope for this scenario";
    case "excluded_by_reviewer":
      return "Rejected in review";
    case "excluded_unsupported":
      return "Excluded as unsupported";
    case "not_computable":
      return "No usable input";
    default:
      return state;
  }
}

export function reasonLabel(code: string): string {
  switch (code) {
    case "unapproved_formula":
      return "No approved formula version";
    case "ambiguous_mapping":
      return "Mapping still awaiting review";
    case "missing_quarter":
      return "A TTM quarter is neither reported nor derivable";
    case "missing_instant":
      return "No balance dated at the test date";
    case "incompatible_facts":
      return "Facts exist but cannot be combined";
    case "missing_analyst_input":
      return "Needs an analyst value";
    case "unsupported_adjustment":
      return "Clause excluded as unsupported";
    default:
      return code;
  }
}

export function blockerLabel(code: string): string {
  switch (code) {
    case "unmapped":
      return "Clause item outside the vocabulary";
    case "unsupported":
      return "Construct the formula language cannot express";
    case "unresolved_reference":
      return "Referenced definition not found";
    case "unreviewed_component":
      return "Component not yet reviewed";
    case "unreviewed_covenant":
      return "Covenant not yet reviewed";
    case "duplicate_item":
      return "Two components resolve to the same item";
    case "all_components_rejected":
      return "Every component was rejected";
    default:
      return code;
  }
}

export function shortHash(hash: string): string {
  const body = hash.replace(/^sha256:/, "");
  return body.slice(0, 12);
}

export function asOf(date: string): string {
  const parsed = new Date(date + "T00:00:00Z");
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
