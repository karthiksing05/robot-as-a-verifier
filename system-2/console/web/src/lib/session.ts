// Local testing only. There's no login: Go opens the app, and the top bar says who you're acting as. That name goes on
// approvals and edits, and the roles are a courtesy in the browser. Real accounts belong on a server before this
// leaves localhost.
import { useSyncExternalStore } from "react";

export type EnvName = "demo" | "prod";
export type Role = "operator" | "judge";

export interface Operator {
  name: string;
  role: Role;
}

export const OPERATORS: Operator[] = [
  { name: "Karthik", role: "operator" },
  { name: "Joseph", role: "operator" },
  { name: "Max", role: "operator" },
  { name: "Bayan", role: "operator" },
  { name: "Judge", role: "judge" },
];

/** What each environment connects to. Screens ask this, and never check an environment's name. */
export interface Environment {
  name: EnvName;
  label: string;
  detail: string;
  runner: "sim" | "real arm";
  cad: "placeholder" | "real CAD";
  sampleRuns: boolean;
  connected: boolean; // false until the real interfaces exist
}

export const ENVIRONMENTS: Record<EnvName, Environment> = {
  demo: { name: "demo", label: "Demo", detail: "MuJoCo sim", runner: "sim", cad: "placeholder", sampleRuns: true, connected: true },
  prod: { name: "prod", label: "Prod", detail: "Real arm and CAD", runner: "real arm", cad: "real CAD", sampleRuns: false, connected: false },
};

export interface Session {
  operator: Operator;
  env: EnvName;
}

const KEY = "rav.session";
const listeners = new Set<() => void>();
let cached: Session | null = read();

function read(): Session | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(KEY);
    const session = raw ? (JSON.parse(raw) as Session) : null;
    return session && session.env in ENVIRONMENTS ? session : null;
  } catch {
    return null;
  }
}

function write(session: Session | null) {
  cached = session;
  try {
    if (session) sessionStorage.setItem(KEY, JSON.stringify(session));
    else sessionStorage.removeItem(KEY);
  } catch {
    // private windows can refuse storage; the session then lasts until reload
  }
  listeners.forEach((fn) => fn());
}

export function canEnter(operator: Operator, env: EnvName): boolean {
  return !(operator.role === "judge" && env === "prod");
}

export function enter(env: EnvName) {
  write({ operator: OPERATORS[0], env });
}

export function switchOperator(name: string) {
  const operator = OPERATORS.find((o) => o.name === name);
  if (cached && operator) write({ operator, env: canEnter(operator, cached.env) ? cached.env : "demo" });
}

export function signOut() {
  write(null);
}

export function useSession(): Session | null {
  return useSyncExternalStore((fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, () => cached);
}
