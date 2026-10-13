/* A verdict always carries its word, never only its colour. */

import type { Verdict as VerdictCode } from "../api";

const WORDS: Record<VerdictCode, string> = {
  PASS: "Pass",
  TIGHT: "Tight",
  BREACH: "Breach",
  NOT_COMPUTABLE: "Not computable",
};

export function Verdict({ verdict }: { verdict: VerdictCode }) {
  return <span className={"verdict verdict-chip-" + verdict}>{WORDS[verdict]}</span>;
}
