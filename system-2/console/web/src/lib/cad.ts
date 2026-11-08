// The appliances' printed CAD, per revision, from the dev server's /api/cad. A built Console with no dev server has none.
import { useEffect, useSyncExternalStore } from "react";

export interface CadPart { file: string; rgba?: number[]; min: number[]; max: number[]; volume?: number }
export interface CadFault {
  id: string;
  what: string;
  class: string;
  A: { parts?: Record<string, string>; params?: Record<string, unknown> } | null;
  B: { parts?: Record<string, string>; params?: Record<string, unknown> } | null;
}
export interface CadEntry { id: string; project: string; title: string; split: string }
export interface CadModel extends CadEntry { heldOut: boolean; revs: string[]; parts: Record<string, Record<string, CadPart>>; faults: CadFault[] }

let list: CadEntry[] = [];
let asked = false;
const watchers = new Set<() => void>();

function load() {
  if (asked) return;
  asked = true;
  fetch("/api/cad")
    .then((r) => (r.ok ? r.json() : []))
    .then((rows: CadEntry[]) => { list = rows; watchers.forEach((w) => w()); })
    .catch(() => undefined);
}

/** Which projects have printed CAD. Empty until the dev server answers. */
export function useCadList(): CadEntry[] {
  useEffect(load, []);
  return useSyncExternalStore((w) => { watchers.add(w); return () => watchers.delete(w); }, () => list);
}

const models = new Map<string, Promise<CadModel | null>>();
export function loadCad(project: string): Promise<CadModel | null> {
  if (!models.has(project)) {
    models.set(project, fetch(`/api/cad/${encodeURIComponent(project)}`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  }
  return models.get(project)!;
}

export const partUrl = (model: CadModel, rev: string, file: string) => `/api/cad/${encodeURIComponent(model.id)}/${rev}/${encodeURIComponent(file)}`;

/** The parts a fault swaps in a revision, as manifest names. */
export const faultParts = (fault: CadFault, rev: string): string[] => Object.values((rev === "B" ? fault.B : fault.A)?.parts ?? {});

/** A fault's parameter changes, Rev A to Rev B. */
export const faultParams = (fault: CadFault): { key: string; from: unknown; to: unknown }[] =>
  Object.keys({ ...fault.A?.params, ...fault.B?.params })
    .map((key) => ({ key, from: fault.A?.params?.[key], to: fault.B?.params?.[key] }))
    .filter((p) => String(p.from) !== String(p.to));

/** "well_a_id" reads as "well a id"; units are left as the device file gives them. */
export const paramLabel = (key: string) => key.replace(/_/g, " ");
