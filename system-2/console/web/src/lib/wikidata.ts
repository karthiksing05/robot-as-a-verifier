// Data behind the wiki's Models, Device theory and Devices sections. Both files come from
// `uv run python -m rav_harness.results_page` in system-2, so nothing here is typed in by hand.

export type RoundStatus = "done" | "running" | "planned";

export interface ModelRow {
  model: string;
  baseline: boolean;
  runs: number;
  score: number | null;
  faults_found: number;
  faults_planted: number;
  false_findings: number;
  coverage: number | null;
  recovered: number;
  recovery_tries: number;
  tokens: number;
  turns: number;
  median_turn_s: number | null;
  tool_errors: number;
  crashes: number;
  reasoning_chars: number;
  reasoning: string | null;
  missed: string[];
  credits: number | null;
  usd: number | null;
  per_run: RunCost[];
}

export interface RunCost {
  run: string;
  tokens: number;
  credits: number;
  usd: number;
}

export interface Cost {
  tokens: number;
  credits: number;
  usd: number;
}

export interface Pricing {
  unit: string;
  source: string | null;
  usd_per_credit: number;
  usd_is: string;
}

export interface Round {
  id: string;
  title: string;
  status: RoundStatus;
  date: string | null;
  kind: "soft" | "eval";
  test_set: string;
  spend: string | null;
  takeaway: string | null;
  cost: Cost | null;
  rows: ModelRow[];
}

export interface Results {
  generated: string;
  route: string | null;
  models: string[];
  pricing: Pricing | null;
  rounds: Round[];
}

const STATUSES: RoundStatus[] = ["done", "running", "planned"];
const num = (v: unknown, fallback = 0) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const maybe = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const text = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

const cost = (v: unknown): Cost | null => {
  const c = (v ?? null) as Record<string, unknown> | null;
  return c && typeof c === "object" && maybe(c.credits) !== null ? { tokens: num(c.tokens), credits: num(c.credits), usd: num(c.usd) } : null;
};

function pricing(v: unknown): Pricing | null {
  const p = (v ?? null) as Record<string, unknown> | null;
  if (!p || typeof p !== "object" || maybe(p.usd_per_credit) === null) return null;
  return { unit: text(p.unit) ?? "AI credits", source: text(p.source), usd_per_credit: num(p.usd_per_credit), usd_is: text(p.usd_is) ?? "an assumption" };
}

/** Reads the generated file defensively: a missing field shows as a dash, never as a crash. */
export function loadResults(raw: unknown): Results {
  const d = (raw ?? {}) as Record<string, unknown>;
  const rounds = Array.isArray(d.rounds) ? d.rounds : [];
  return {
    generated: text(d.generated) ?? "",
    route: text(d.route),
    models: Array.isArray(d.models) ? d.models.filter((m): m is string => typeof m === "string") : [],
    pricing: pricing(d.pricing),
    rounds: rounds.map((r: Record<string, unknown>) => {
      const rows = Array.isArray(r.rows) ? r.rows : [];
      const status = STATUSES.includes(r.status as RoundStatus) ? (r.status as RoundStatus) : "planned";
      return {
        id: String(r.id ?? ""), title: text(r.title) ?? "", status, date: text(r.date), kind: r.kind === "eval" ? "eval" : "soft",
        test_set: text(r.test_set) ?? "", spend: text(r.spend), takeaway: text(r.takeaway), cost: status === "planned" ? null : cost(r.cost),
        rows: status === "planned" ? [] : rows.map((x: Record<string, unknown>) => ({
          model: String(x.model ?? "?"), baseline: x.baseline === true, runs: num(x.runs), score: maybe(x.score),
          faults_found: num(x.faults_found), faults_planted: num(x.faults_planted), false_findings: num(x.false_findings), coverage: maybe(x.coverage),
          recovered: num(x.recovered), recovery_tries: num(x.recovery_tries), tokens: num(x.tokens), turns: num(x.turns),
          median_turn_s: maybe(x.median_turn_s), tool_errors: num(x.tool_errors), crashes: num(x.crashes), reasoning_chars: num(x.reasoning_chars),
          reasoning: text(x.reasoning), missed: Array.isArray(x.missed) ? x.missed.map(String) : [],
          credits: maybe(x.credits), usd: maybe(x.usd),
          per_run: Array.isArray(x.per_run) ? x.per_run.map((y: Record<string, unknown>) => ({ run: String(y.run ?? "?"), tokens: num(y.tokens), credits: num(y.credits), usd: num(y.usd) })) : [],
        })),
      };
    }),
  };
}

const NAMES: Record<string, string> = {
  "claude-haiku-5-5": "Claude Haiku 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "openai-gpt-5.4": "GPT-5.4", "grok-4.7": "Grok 4.7", rules: "Rules (baseline)",
};
export const modelName = (id: string) => NAMES[id] ?? id;

export const fmtTokens = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
export const fmtCredits = (v: number | null) => (v === null ? "–" : v > 0 && v < 0.01 ? "<0.01" : v.toFixed(2));
export const fmtUsd = (v: number | null) => (v === null ? "–" : v > 0 && v < 0.01 ? "<$0.01" : `$${v.toFixed(2)}`);
export const fmtRatio = (a: number, b: number) => (b ? `${a} of ${b}` : "–");
export const fmtShare = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
export const fmtScore = (v: number | null) => (v === null ? "–" : v.toFixed(2));

/** True when every model (not the baseline) has the same score, so the round can't rank them on it. */
export function tiedOnScore(round: Round): boolean {
  const scores = round.rows.filter((r) => !r.baseline).map((r) => r.score);
  return scores.length > 1 && scores.every((s) => s !== null && s === scores[0]);
}

// ---- docs/device-theory.md and docs/devices.md, carried as markdown in wiki-docs.json ----

export interface DocSection {
  title: string;
  fields: [string, string][];
  body: string[];
}

const FIELD = /^\s*(?:[-*]\s+)?\*{0,2}([A-Za-z][A-Za-z /-]{0,30}?)\*{0,2}:\*{0,2}\s+(.+)$/;
const BOLD_FIELD = /(?=\*\*[A-Za-z][A-Za-z /-]{0,30}:\*\*)/;

/** Splits a doc at its `##` headings (or `###`, with `##` as groups). Lines like "- **Split:** dev" become fields, and a line
 *  holding several, like "**Split:** dev. **Revisions:** A, B", becomes one field each. Everything else stays as body. */
export function sections(markdown: string | null | undefined, level = 2): { intro: string[]; parts: DocSection[] } {
  const intro: string[] = [];
  const parts: DocSection[] = [];
  const heading = new RegExp(`^#{${level}}\\s`), above = new RegExp(`^#{1,${level - 1}}\\s`);
  for (const line of (markdown ?? "").split("\n")) {
    if (above.test(line)) continue;
    if (heading.test(line)) { parts.push({ title: line.replace(/^#+\s+/, "").trim(), fields: [], body: [] }); continue; }
    const at = parts[parts.length - 1];
    if (!at) { intro.push(line); continue; }
    const pieces = /^\s*\*\*/.test(line) ? line.split(BOLD_FIELD) : [line];
    for (const piece of pieces) {
      const f = !/^\s*\|/.test(piece) && FIELD.exec(piece);
      if (f) at.fields.push([f[1].trim(), f[2].trim().replace(/\.$/, "")]);
      else at.body.push(piece);
    }
  }
  return { intro, parts };
}

export const field = (s: DocSection, ...names: string[]) => s.fields.find(([k]) => names.some((n) => k.toLowerCase().startsWith(n)))?.[1] ?? null;

export interface DeviceCard {
  id: string | null;
  name: string;
  split: string | null;
  heldOut: boolean;
  revisions: string[];
  controls: string[];
  theory: string[];
  planted: string | null; // what is broken in Rev A. Never for a held-out device
  project: string | null;
  body: string[];
  extra: [string, string][];
}

/** A list in a field, split where it isn't inside brackets: at semicolons and sentences if it has them, else at commas. */
export function listOf(v: string | null): string[] {
  if (!v) return [];
  const split = (text: string, at: RegExp) => {
    const out: string[] = [];
    let depth = 0, from = 0;
    for (let i = 0; i < text.length; i++) {
      depth += text[i] === "(" ? 1 : text[i] === ")" ? -1 : 0;
      const m = depth === 0 ? at.exec(text.slice(i)) : null;
      if (m && m.index === 0) { out.push(text.slice(from, i)); from = i + m[0].length; i += m[0].length - 1; }
    }
    return [...out, text.slice(from)];
  };
  const tidy = (x: string) => x.replace(/[`*]/g, "").replace(/^\s*(and|or)\s+/, "").replace(/\.\s*$/, "").trim();
  const firstPass = split(v, /^(;\s*|\.\s+)/).map(tidy).filter(Boolean);
  return (firstPass.length > 1 ? firstPass : split(v, /^,\s*/).map(tidy)).filter(Boolean);
}

/** A theory piece's name, without what it says in brackets: "drives (dial to speed)" is "drives". */
export const pieceName = (piece: string) => piece.split(" (")[0];

/** One card per device. A held-out device never shows a field or line about its faults, even if the doc has one. */
export function deviceCards(markdown: string | null | undefined): DeviceCard[] {
  const level = /^###\s/m.test(markdown ?? "") ? 3 : 2;
  return sections(markdown, level).parts.map((s) => {
    const split = field(s, "split");
    const heldOut = !!split && /held/i.test(split);
    const safe = (v: string) => !(heldOut && /fault/i.test(v));
    const used = ["split", "revisions", "controls", "theory", "exercises", "faults", "project", "demo"];
    const id = /`([^`]+)`/.exec(s.title)?.[1] ?? null;
    return {
      id, name: s.title.replace(/\s*\(`[^`]+`\)/, "").trim(), split, heldOut,
      revisions: listOf(field(s, "revisions")), controls: listOf(field(s, "controls")), theory: listOf(field(s, "theory", "exercises")),
      planted: heldOut ? null : field(s, "faults"),
      project: field(s, "project", "demo")?.replace(/[`*]/g, "").trim() || id,
      body: s.body.filter(safe),
      extra: s.fields.filter(([k, v]) => !used.some((u) => k.toLowerCase().startsWith(u)) && safe(k) && safe(v)),
    };
  });
}

/** Where a device runs in the Demo: its project, if the doc names one, or the start form. */
export const demoHref = (card: DeviceCard) => (card.project ? `#/live?project=${encodeURIComponent(card.project)}` : "#/live");

// ---- the Models chart: faults found against cost per device ----

export interface ChartPoint { model: string; found: number; planted: number; share: number; perDevice: number }
export interface ChartPanel { id: string; title: string; points: ChartPoint[]; baseline: number | null }

/** One panel per finished scored round that ran at least two models. A point is one model's share of planted faults found
 *  against its dollars per device (a run is one device). The baseline costs nothing, so it's a line, not a point. */
export function chartPanels(results: Results): ChartPanel[] {
  return results.rounds
    .filter((r) => r.kind === "eval" && r.status === "done")
    .map((r) => {
      const points = r.rows
        .filter((x) => !x.baseline && x.usd !== null && x.runs > 0 && x.faults_planted > 0)
        .map((x) => ({ model: x.model, found: x.faults_found, planted: x.faults_planted, share: x.faults_found / x.faults_planted, perDevice: (x.usd ?? 0) / x.runs }));
      const base = r.rows.find((x) => x.baseline && x.faults_planted > 0);
      return { id: r.id, title: r.title, points, baseline: base ? base.faults_found / base.faults_planted : null };
    })
    .filter((p) => p.points.length >= 2);
}

/** Powers of ten that cover every value, for a log axis. */
export function logDomain(values: number[]): [number, number] {
  const pos = values.filter((v) => v > 0);
  if (!pos.length) return [0.001, 1];
  const lo = Math.floor(Math.log10(Math.min(...pos))), hi = Math.ceil(Math.log10(Math.max(...pos)));
  return [10 ** lo, 10 ** Math.max(hi, lo + 1)];
}
