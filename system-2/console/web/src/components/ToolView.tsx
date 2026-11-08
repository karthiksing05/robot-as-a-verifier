// A tool call in the timeline: one readable line, a readable body for the calls that carry plans or results, and the
// raw JSON behind its own toggle. Logged args keep only two levels, so deeper values arrive as "dict of 2" or "list of 3".
import type { ReactNode } from "react";
import type { ToolCall } from "../lib/trace";
import { Markdown } from "./Markdown";
import { ErrorText } from "./ModelTrace";
import { Pill } from "./ui";

type Obj = Record<string, unknown>;
const seconds = (ms: number | null | undefined) => (ms == null ? null : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const list = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);
const ELIDED = /^(dict|list) of \d+$/;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A value in a few words: text as it is, a list or record by its size. */
export function brief(v: unknown): string {
  if (v == null) return "none";
  if (typeof v !== "object") return String(v);
  if (Array.isArray(v)) return v.every((x) => x == null || typeof x !== "object") && v.length <= 4 ? v.map(brief).join(", ") : plural(v.length, "item");
  return plural(Object.keys(v).length, "field");
}

const tally = (items: Obj[], key: string) => {
  const n = new Map<string, number>();
  for (const i of items) n.set(String(i[key] ?? "?"), (n.get(String(i[key] ?? "?")) ?? 0) + 1);
  return [...n].map(([k, c]) => `${c} ${k}`).join(", ");
};

/** The call's arguments as one short line. */
export function toolBrief(c: Pick<ToolCall, "tool" | "args">): string {
  const a = c.args;
  switch (c.tool) {
    case "propose_plan": return [plural(list(a.steps).length, "step"), a.restore ? "restore" : null, a.close_with_look ? "then the closing look" : null].filter(Boolean).join(", ");
    case "answer_stop": return [a.kind, Array.isArray(a.targets) && a.targets.length ? a.targets.join(", ") : null, list(a.steps).length ? plural(list(a.steps).length, "step") : null, a.note].filter(Boolean).join(" / ");
    case "finish_run": return list(a.controls).length ? `${plural(list(a.controls).length, "control")}: ${tally(list(a.controls), "status")}` : "";
    case "record_hypothesis": return isObj(a.hypothesis) ? Object.entries(a.hypothesis).filter(([, v]) => Array.isArray(v)).map(([k, v]) => `${(v as unknown[]).length} ${k}`).join(", ") : "";
    case "read_manual": return a.page != null ? `page ${a.page}` : "";
    case "recover": return [a.action, a.note].filter(Boolean).join(" / ");
    case "ask_operator": return String(a.question ?? "");
  }
  return Object.entries(a).map(([k, v]) => `${k} ${brief(v)}`).join(", ");
}

const paramsOf = (p: unknown) => (isObj(p) ? Object.entries(p).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ") : typeof p === "string" && !ELIDED.test(p) ? p : "");
const checkOf = (c: Obj) => [c.metric, c.op, c.value == null ? null : JSON.stringify(c.value)].filter((x) => x != null).join(" ");

/** A plan's steps: what runs, on what, with which settings, and why. */
export function StepsTable({ steps }: { steps: Obj[] }) {
  const params = steps.some((s) => paramsOf(s.params)); // a logged call's params are elided
  return (
    <table className="tltable">
      <thead><tr><th>Step</th><th>Control</th><th>Skill</th>{params && <th>Params</th>}<th>Why</th></tr></thead>
      <tbody>{steps.map((s, i) => (
        <tr key={`${String(s.id)}-${i}`}>
          <td className="mono">{String(s.id ?? "")}</td>
          <td className="mono">{String(s.target ?? "")}</td>
          <td className="mono">{String(s.skill ?? "")}</td>
          {params && <td className="mono muted">{paramsOf(s.params)}</td>}
          <td>
            {String(s.why ?? s.expected ?? "")}
            {typeof s.quote === "string" && <em className="tlquote"> “{s.quote}”</em>}
            {list(s.check).length > 0 && <span className="tlcheck mono">check {list(s.check).map(checkOf).join("; ")}</span>}
          </td>
        </tr>
      ))}</tbody>
    </table>
  );
}

/** finish_run's account of each control. */
function ControlsTable({ controls }: { controls: Obj[] }) {
  return (
    <table className="tltable">
      <tbody>{controls.map((c, i) => (
        <tr key={`${String(c.id)}-${i}`}><td className="mono">{String(c.id ?? "")}</td><td><Pill status={String(c.status ?? "skipped")} /></td><td>{String(c.why ?? "")}</td></tr>
      ))}</tbody>
    </table>
  );
}

/** A result's top level as label and value. */
function Fields({ value }: { value: Obj }) {
  return (
    <dl className="kv tlkv">
      {Object.entries(value).filter(([, v]) => v != null && v !== "").map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{typeof v === "string" ? v : brief(v)}</dd></div>
      ))}
    </dl>
  );
}

function Body({ c }: { c: ToolCall }) {
  const a = c.args, r = c.result ?? {};
  const parts: ReactNode[] = [];
  if (typeof a.why === "string") parts.push(<p key="why" className="tlwhy">{a.why}</p>);
  if (typeof a.note === "string" && c.tool !== "answer_stop" && c.tool !== "recover") parts.push(<p key="note" className="tlwhy">{a.note}</p>);
  if (list(a.steps).length) parts.push(<StepsTable key="steps" steps={list(a.steps)} />);
  if (c.tool === "finish_run" && list(a.controls).length) parts.push(<ControlsTable key="controls" controls={list(a.controls)} />);
  if (c.tool === "read_manual" && typeof r.text === "string") parts.push(<Markdown key="manual" text={r.text} className="md tlmanual" />);
  else if (c.result && Object.keys(c.result).length && c.tool !== "finish_run") parts.push(<Fields key="result" value={c.result} />);
  return <>{parts}</>;
}

export function Tool({ call: c }: { call: ToolCall }) {
  const line = toolBrief(c);
  const open = (c.ok && c.tool === "finish_run" && list(c.args.controls).length > 0) || undefined; // the run's last word
  const json = { ...(Object.keys(c.args).length ? { args: c.args } : {}), ...(c.result ? { result: c.result } : {}) };
  return (
    <details className={`tltool ${c.ok ? "" : "bad"}`} open={open}>
      <summary>
        <b className="mono">{c.tool}</b>{line && <span className="muted tlargs">{line}</span>}<span className="tmeta">{[c.ok ? null : c.error_kind, c.caller === "model" ? null : c.caller, seconds(c.duration_ms)].filter(Boolean).join(" / ")}</span>
        {c.error && <ErrorText text={c.error} />}
      </summary>
      <div className="tlbody">
        <Body c={c} />
        {Object.keys(json).length > 0 && <details className="tljson"><summary>JSON</summary><pre>{JSON.stringify(json, null, 2)}</pre></details>}
      </div>
    </details>
  );
}

/** The harness's checklist: per subject, which properties were tested and how they came out. */
export function Checklist({ checklist }: { checklist: unknown }) {
  const rows = new Map<string, [string, string][]>();
  const add = (key: string, status: string) => {
    const [property, subject = "", ...rest] = key.split(":");
    const name = [subject, ...rest].join(" / ");
    rows.set(name, [...(rows.get(name) ?? []), [property, status]]);
  };
  if (Array.isArray(checklist)) list(checklist).forEach((i) => add(String(i.key), "pending"));
  else if (isObj(checklist)) {
    for (const [k, v] of Object.entries(isObj(checklist.tested) ? checklist.tested : {})) add(k, String(v));
    for (const [k, v] of Object.entries(isObj(checklist.blocked) ? checklist.blocked : {})) add(k, `blocked${typeof v === "string" ? `: ${v}` : ""}`);
    for (const k of Array.isArray(checklist.untested) ? checklist.untested : []) add(String(k), "untested");
  }
  return (
    <table className="tltable">
      <tbody>{[...rows].map(([subject, props]) => (
        <tr key={subject}><td className="mono">{subject}</td><td className="tlprops">{props.map(([p, s]) => <span key={p} className={`tlprop ${s}`} title={s}>{p.replaceAll("_", " ")}{s !== "pending" && <i> {s}</i>}</span>)}</td></tr>
      ))}</tbody>
    </table>
  );
}
