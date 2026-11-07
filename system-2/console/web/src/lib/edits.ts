// The operator edit ledger. Every change to the exploration is recorded here with who, why and when, and bug
// reports, the graph and the report read from it. Edits are withdrawn rather than deleted, so the record stays whole.
// Edits add tests and never change a verdict or the reward, which come only from the event log.
import { useSyncExternalStore } from "react";
import type { CADPatch, SteerCommand } from "./contracts";
import type { EnvName, Operator } from "./session";

export type EditAction = "retry" | "fine_tune" | "add_test" | "prioritize" | "skip" | "note" | "cad_patch";
export type EditState = "planned" | "approved" | "rejected" | "withdrawn";

export interface OperatorEdit {
  id: string;
  runId: string;
  nodeId: string | null;
  target: string | null;
  action: EditAction;
  reason: string;
  params: Record<string, string | number>;
  patch?: CADPatch;
  by: string;
  at: string;
  state: EditState;
  decidedBy?: string;
}

export const ACTION_LABEL: Record<EditAction, string> = {
  retry: "Retry", fine_tune: "Fine-tune", add_test: "Add test", prioritize: "Prioritize", skip: "Skip", note: "Note",
  cad_patch: "CAD patch",
};

export const needsApproval = (action: EditAction) => action === "retry" || action === "fine_tune" || action === "add_test" || action === "cad_patch";

/** A person approves before the arm moves or a patch prints. A CAD patch must be approved by a teammate. */
export function approvalBlock(edit: OperatorEdit, operator: Operator): string | null {
  if (operator.role !== "operator") return "Judges can propose edits. An operator has to approve them.";
  if (edit.action === "cad_patch" && edit.by === operator.name) return "A teammate has to approve your own CAD patch.";
  return null;
}

/** What this edit would send to the harness. `reason` isn't in SteerCommand yet, so it's carried in the Console's ledger. */
export function toCommand(edit: Pick<OperatorEdit, "action" | "target" | "params" | "reason" | "by" | "nodeId">): SteerCommand | null {
  const target = edit.target ?? undefined;
  switch (edit.action) {
    case "prioritize": return { kind: "prioritize", target, by: edit.by };
    case "skip": return { kind: "skip", target, by: edit.by };
    case "note": return { kind: "message", text: edit.reason, by: edit.by };
    case "retry":
    case "fine_tune":
    case "add_test":
      return { kind: "add_step", by: edit.by, step: { id: `${edit.nodeId ?? "new"}-next`, skill: String(edit.params.skill ?? "press"), target, params: edit.action === "fine_tune" ? edit.params : {} } };
    case "cad_patch": return null;
  }
}

const listeners = new Set<() => void>();
const cache = new Map<EnvName, OperatorEdit[]>();
const keyOf = (env: EnvName) => `rav.edits.${env}`;

function load(env: EnvName): OperatorEdit[] {
  const known = cache.get(env);
  if (known) return known;
  let edits: OperatorEdit[] = [];
  try {
    const raw = globalThis.localStorage?.getItem(keyOf(env));
    if (raw) edits = JSON.parse(raw) as OperatorEdit[];
  } catch {
    // no storage available: keep edits in memory until reload
  }
  cache.set(env, edits);
  return edits;
}

function save(env: EnvName, edits: OperatorEdit[]) {
  cache.set(env, edits);
  try {
    localStorage.setItem(keyOf(env), JSON.stringify(edits));
  } catch {
    // no storage available: keep edits in memory until reload
  }
  listeners.forEach((fn) => fn());
}

export function addEdit(env: EnvName, edit: Omit<OperatorEdit, "id" | "at" | "state">): OperatorEdit {
  const edits = load(env);
  const number = edits.reduce((n, e) => Math.max(n, Number(e.id.slice(1)) || 0), 0) + 1;
  const created: OperatorEdit = { ...edit, id: `E${number}`, at: new Date().toISOString(), state: needsApproval(edit.action) ? "planned" : "approved" };
  save(env, [...edits, created]);
  return created;
}

export function decideEdit(env: EnvName, id: string, state: EditState, decidedBy: string) {
  save(env, load(env).map((e) => (e.id === id ? { ...e, state, decidedBy } : e)));
}

export function resetEdits(env: EnvName) {
  save(env, []);
}

export function useEdits(env: EnvName): OperatorEdit[] {
  return useSyncExternalStore((fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, () => load(env));
}

export interface ParsedPrompt {
  action: EditAction;
  target: string | null;
  reason: string;
}

/** Reads a chat prompt such as "retry button_2 because the cap may rub". Anything else is kept as a note. */
export function parsePrompt(text: string, targets: string[]): ParsedPrompt {
  const lower = text.toLowerCase();
  const target = targets.find((t) => lower.includes(t.toLowerCase()) || lower.includes(t.toLowerCase().replace("_", " "))) ?? null;
  const verb: [RegExp, EditAction][] = [[/\bretry\b|\btry .*again\b/, "retry"], [/\bfine.?tune\b|\btune\b/, "fine_tune"], [/\bprioriti[sz]e\b|\bfirst\b/, "prioritize"], [/\bskip\b/, "skip"], [/\badd (a )?(new )?test\b/, "add_test"]];
  const match = verb.find(([pattern]) => pattern.test(lower));
  if (!match || !target) return { action: "note", target, reason: text };
  const because = text.match(/\b(?:because|since|to)\b\s+(.*)$/i);
  return { action: match[1], target, reason: because ? because[1] : text };
}
