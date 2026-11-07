import { createContext, useContext, useEffect, useSyncExternalStore } from "react";
import { fixtureRuns, parseEvents, toRun, type Run } from "./runs";
import { ENVIRONMENTS, type EnvName, type Session } from "./session";

const FIXTURES = fixtureRuns();

export const runsFor = (env: EnvName): Run[] => (ENVIRONMENTS[env].sampleRuns ? FIXTURES : []);

// Runs recorded by the live sim, newest first, from the dev server. Fixtures still work without any of this.
let recorded: Run[] = [];
let loaded = false;
const watchers = new Set<() => void>();

export async function refreshRecorded() {
  try {
    const res = await fetch("/api/runs");
    const list = res.ok ? await res.json() : [];
    recorded = list.map((r: { id: string; events: string; report: Run["report"]; timeline: NonNullable<Run["recording"]>["timeline"]; video?: string; base?: string }) => ({
      ...toRun(parseEvents(r.events), r.report),
      recording: { video: r.video, timeline: r.timeline, assets: r.base ? (path: string) => r.base + path : undefined },
    }));
  } catch {
    recorded = [];
  }
  loaded = true;
  watchers.forEach((fn) => fn());
}

/** Every run this environment can show. `ready` is false until recorded runs have been asked for. */
export function useRuns(env: EnvName) {
  useEffect(() => { void refreshRecorded(); }, []);
  const list = useSyncExternalStore((fn) => { watchers.add(fn); return () => watchers.delete(fn); }, () => recorded);
  return { runs: ENVIRONMENTS[env].runner === "sim" ? [...list, ...FIXTURES] : [], ready: loaded };
}

export const SessionContext = createContext<Session>(null as unknown as Session);
export const useAppSession = () => useContext(SessionContext);
