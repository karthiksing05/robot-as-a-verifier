// Builds the exploration DAG. Solid nodes come from the event log; dashed nodes come from operator edits. Nothing here changes a verdict.
import type { Status } from "./contracts";
import type { OperatorEdit } from "./edits";
import type { Run } from "./runs";

export type Provenance = "log" | "edit" | "plan"; // plan: a live run's step that hasn't happened yet
export type NodeKind = "input" | "scene" | "plan" | "step" | "finding" | "cause" | "patch" | "apply" | "revision" | "branch";

export interface GraphNode {
  id: string;
  kind: NodeKind;
  title: string;
  sub: string;
  provenance: Provenance;
  parents: string[];
  status?: Status | "planned" | "rejected" | "running" | "pending";
  seq?: number;
  target?: string;
  tier?: string;
  reason?: string;
  by?: string;
  editId?: string;
  flags: string[];
  linkRun?: string;
}

export interface PlacedNode extends GraphNode {
  rank: number;
  lane: number;
}

const GLYPH: Record<string, string> = { passed: "✓", failed: "✕", observed: "◐", skipped: "⊘", inconclusive: "?" };

function logNodes(run: Run, next: Run | undefined): GraphNode[] {
  const nodes: GraphNode[] = [];
  const flags: string[] = [];
  const add = (node: Omit<GraphNode, "flags">) => nodes.push({ ...node, flags: [...flags] });
  add({ id: "input", kind: "input", title: `Rev ${run.revision} request`, sub: run.manual ?? "no manual", provenance: "log", parents: [], seq: 1 });
  add({ id: "scene", kind: "scene", title: "Scene", sub: `${run.scene.controls.length} controls`, provenance: "log", parents: ["input"], seq: run.events.find((e) => e.type === "scene_ready")?.seq });
  const planApproval = run.approvals.find((a) => a.kind === "plan");
  add({ id: "plan", kind: "plan", title: "Plan", sub: planApproval ? `by ${planApproval.by}` : "not approved", provenance: "log", parents: ["scene"], seq: planApproval?.seq });
  let previous = "plan";
  for (const s of run.steps) {
    const status = s.verdict?.status;
    add({ id: s.step.id, kind: "step", title: `${s.step.id} ${status ? GLYPH[status] : ""}`.trim(), sub: s.step.target, provenance: "log", parents: [previous], status, seq: s.endSeq ?? s.startSeq, target: s.step.target });
    previous = s.step.id;
  }
  const patchIds: string[] = [];
  for (const f of run.findings) {
    add({ id: f.id, kind: "finding", title: f.id, sub: f.label, provenance: "log", parents: [f.step_ids[0]], status: "failed", seq: f.seq, target: f.target });
    const cause = run.causes.find((c) => c.finding === f.id);
    if (!cause) continue;
    const top = Math.max(...cause.hypotheses.map((h) => h.p));
    add({ id: `${f.id}-cause`, kind: "cause", title: "Root cause", sub: `p ${top.toFixed(2)}`, provenance: "log", parents: [f.id], seq: cause.seq, target: f.target });
    const patch = run.proposed[run.causes.indexOf(cause)];
    if (!patch) continue;
    add({ id: `${f.id}-patch`, kind: "patch", title: "Patch", sub: patch.changes[0]?.param ?? "", provenance: "log", parents: [`${f.id}-cause`], seq: patch.seq, target: f.target });
    patchIds.push(`${f.id}-patch`);
  }
  if (patchIds.length && run.applied.length) {
    add({ id: "apply", kind: "apply", title: `Rev ${run.applied[0].revision_to} built`, sub: `${run.applied.length} patches`, provenance: "log", parents: patchIds, seq: run.applied.at(-1)?.seq });
    if (next) add({ id: "retest", kind: "revision", title: `Rev ${next.revision} retest`, sub: `reward ${next.report.reward.value.toFixed(2)}`, provenance: "log", parents: ["apply"], status: next.report.reward.value > run.report.reward.value ? "passed" : "failed", linkRun: next.id });
  }
  return nodes;
}

export function buildGraph(run: Run, next: Run | undefined, edits: OperatorEdit[]): GraphNode[] {
  return addEdits(logNodes(run, next), run.id, edits);
}

/** Operator edits, drawn onto any run's graph. */
export function addEdits(nodes: GraphNode[], runId: string, edits: OperatorEdit[]): GraphNode[] {
  for (const e of edits) {
    if (e.runId !== runId || e.state === "withdrawn" || !e.nodeId) continue;
    const parent = nodes.find((n) => n.id === e.nodeId);
    if (!parent) continue;
    if (e.action === "prioritize" || e.action === "skip" || e.action === "note") {
      parent.flags.push(`${e.id} ${e.action}`);
      continue;
    }
    nodes.push({
      id: `edit-${e.id}`, kind: "branch", title: `${e.id} ${e.action === "fine_tune" ? "fine-tune" : e.action === "retry" ? "retry" : "new test"}`,
      sub: e.target ?? "", provenance: "edit", parents: [e.nodeId], status: e.state === "rejected" ? "rejected" : "planned",
      target: e.target ?? undefined, reason: e.reason, by: e.by, editId: e.id, flags: [],
    });
  }
  return nodes;
}

/** Longest-path ranks, then lanes: a node stays on its first parent's lane if free, otherwise takes the next free one. */
export function placeNodes(nodes: GraphNode[]): PlacedNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ranks = new Map<string, number>();
  const rankOf = (id: string): number => {
    const known = ranks.get(id);
    if (known !== undefined) return known;
    const node = byId.get(id);
    const parents = node ? node.parents.filter((p) => byId.has(p)) : [];
    const rank = parents.length ? Math.max(...parents.map(rankOf)) + 1 : 0;
    ranks.set(id, rank);
    return rank;
  };
  const taken = new Set<string>();
  const lanes = new Map<string, number>();
  return nodes.map((node) => {
    const rank = rankOf(node.id);
    const parent = node.parents[0];
    let lane = parent !== undefined ? lanes.get(parent) ?? 0 : 0;
    while (taken.has(`${rank}:${lane}`)) lane += 1;
    taken.add(`${rank}:${lane}`);
    lanes.set(node.id, lane);
    return { ...node, rank, lane };
  });
}
