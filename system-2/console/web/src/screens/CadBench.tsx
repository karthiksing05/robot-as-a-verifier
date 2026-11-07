import rawParams from "@repo/subjects/appliance/cad/params.rev_a.json";
import { useEffect, useMemo, useState } from "react";
import { ProjectBar } from "../components/ProjectBar";
import { Viewer3D, type ApplianceParams } from "../components/Viewer3D";
import { Pill, stagger } from "../components/ui";
import type { CADPatch, ParamChange } from "../lib/contracts";
import { runsFor, useAppSession } from "../lib/context";
import { ENVIRONMENTS } from "../lib/session";
import { addEdit } from "../lib/edits";
import { useProjects } from "../lib/projects";

const REV_A = rawParams as ApplianceParams;

const FIELDS: { key: string; label: string; unit: string; step: number }[] = [
  { key: "button_clearance[0]", label: "Clearance, button 1", unit: "mm", step: 0.05 },
  { key: "button_clearance[1]", label: "Clearance, button 2", unit: "mm", step: 0.05 },
  { key: "button_clearance[2]", label: "Clearance, button 3", unit: "mm", step: 0.05 },
  { key: "dome_preload[0]", label: "Dome preload, 1", unit: "mm", step: 0.05 },
  { key: "dome_preload[1]", label: "Dome preload, 2", unit: "mm", step: 0.05 },
  { key: "dome_preload[2]", label: "Dome preload, 3", unit: "mm", step: 0.05 },
  { key: "latch_overlap", label: "Latch overlap", unit: "mm", step: 0.1 },
  { key: "lcd_tilt", label: "LCD tilt", unit: "°", step: 1 },
];

function read(params: ApplianceParams, key: string): number | string {
  const m = key.match(/^(\w+)\[(\d+)\]$/);
  const record = params as unknown as Record<string, unknown>;
  return (m ? (record[m[1]] as number[])[Number(m[2])] : record[key]) as number | string;
}

function write(params: ApplianceParams, key: string, value: unknown): ApplianceParams {
  const m = key.match(/^(\w+)\[(\d+)\]$/);
  const next = structuredClone(params) as unknown as Record<string, unknown>;
  if (m) (next[m[1]] as unknown[])[Number(m[2])] = value;
  else next[key] = value;
  return next as unknown as ApplianceParams;
}

const applyChanges = (base: ApplianceParams, changes: ParamChange[]) => changes.reduce((p, c) => write(p, c.param, c.to_value), base);

interface FeedItem {
  id: string;
  kind: "log";
  title: string;
  detail: string;
  changes: ParamChange[];
}

/** The agent's edit as a sequence. Items come from events.jsonl. */
function useFeed(env: ReturnType<typeof useAppSession>["env"]) {
  return useMemo<FeedItem[]>(() => {
    const run = runsFor(env).find((r) => r.applied.length);
    if (!run) return [];
    const items: FeedItem[] = [];
    run.causes.forEach((cause, i) => {
      const patch = run.proposed[i];
      items.push({ id: `c${cause.seq}`, kind: "log", title: `Root cause for ${cause.finding}`, detail: cause.root_cause, changes: [] });
      if (patch) items.push({ id: `p${patch.seq}`, kind: "log", title: "Propose patch", detail: patch.changes.map((c) => `${c.param}: ${c.from_value} → ${c.to_value}${c.unit ? ` ${c.unit}` : ""}. Predicted: ${c.predicted}`).join("; "), changes: patch.changes });
    });
    run.applied.forEach((patch) => items.push({ id: `a${patch.seq}`, kind: "log", title: `Patch applied, Rev ${patch.revision_to}`, detail: `${patch.changes[0]?.param}, approved by ${run.approvals.find((a) => a.seq < patch.seq && a.kind === "patch")?.by ?? "no one"}`, changes: [] }));
    return items;
  }, [env]);
}

export function CadBench({ theme }: { theme: string }) {
  const { env, operator } = useAppSession();
  const project = useProjects().find((p) => p.cad);
  const feed = useFeed(env);
  const revB = useMemo(() => applyChanges(REV_A, feed.flatMap((f) => f.changes)), [feed]);
  const [base, setBase] = useState<"A" | "B">("A");
  const baseParams = base === "A" ? REV_A : revB;
  const [params, setParams] = useState<ApplianceParams>(REV_A);
  const [cursor, setCursor] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const changedKeys = [...FIELDS.map((f) => f.key), "handle_style"].filter((k) => read(params, k) !== read(baseParams, k));
  const changes: ParamChange[] = changedKeys.map((k) => ({ param: k, from_value: read(baseParams, k), to_value: read(params, k), unit: FIELDS.find((f) => f.key === k)?.unit ?? null, predicted: null }));

  useEffect(() => {
    if (!playing) return;
    if (cursor >= feed.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      const next = cursor + 1;
      setCursor(next);
      if (feed[next].changes.length) setParams((p) => applyChanges(p, feed[next].changes));
    }, cursor < 0 ? 200 : 1100);
    return () => window.clearTimeout(timer);
  }, [playing, cursor, feed]);

  const replay = () => {
    setBase("A");
    setParams(REV_A);
    setCursor(-1);
    setPlaying(true);
    setNotice("");
  };

  const choose = (rev: "A" | "B") => {
    setPlaying(false);
    setCursor(-1);
    setBase(rev);
    setParams(rev === "A" ? REV_A : revB);
  };

  const submit = () => {
    if (!changes.length) return;
    if (!reason.trim()) return setError("Add a reason for this patch.");
    setError("");
    const patch: CADPatch = { file: "subjects/appliance/cad/params.rev_a.json", revision_from: base, revision_to: base === "A" ? "B" : "C", changes, constraints_checked: [], approved_by: null, verify_with: [], backend: "onshape" };
    const edit = addEdit(env, { runId: "cad", nodeId: null, target: changes[0].param, action: "cad_patch", reason: reason.trim(), params: {}, patch, by: operator.name });
    setReason("");
    setNotice(`${edit.id} is waiting for a teammate on the Approvals screen.`);
  };

  return (
    <div className="page" style={{ maxWidth: "none" }}>
      {ENVIRONMENTS[env].connected && project && <ProjectBar project={project} tab="cad" />}
      <div className="row">
        <div className="stack" style={{ marginRight: "auto" }}>
          <h1 className="title">CAD bench</h1>
          <span className="label">Appliance / {params.handle_style} handle / subjects/appliance/cad</span>
        </div>
        <Pill status="pending">Onshape not connected</Pill>
        <div className="seg" role="group" aria-label="Revision">
          <button type="button" aria-pressed={base === "A"} onClick={() => choose("A")}>Rev A</button>
          <button type="button" aria-pressed={base === "B"} disabled={!feed.length} onClick={() => choose("B")}>Rev B</button>
        </div>
      </div>
      <div className="bench">
        <div className="panel rise">
          <h2>Parameters</h2>
          <table className="params"><tbody>
            {FIELDS.map((f) => (
              <tr key={f.key}>
                <td><label htmlFor={`p-${f.key}`} style={{ fontSize: 14.5 }}>{f.label}</label></td>
                <td><input id={`p-${f.key}`} className={changedKeys.includes(f.key) ? "changed" : ""} type="number" step={f.step} value={read(params, f.key)} onChange={(e) => setParams(write(params, f.key, Number(e.target.value)))} /></td>
                <td className="note">{f.unit}</td>
              </tr>
            ))}
            <tr>
              <td><label htmlFor="p-handle" style={{ fontSize: 14.5 }}>Door handle</label></td>
              <td colSpan={2}><select id="p-handle" className={changedKeys.includes("handle_style") ? "changed" : ""} value={params.handle_style} onChange={(e) => setParams(write(params, "handle_style", e.target.value))}><option value="tab">tab</option><option value="push_latch">push_latch</option></select></td>
            </tr>
          </tbody></table>
          <h3>Patch diff</h3>
          {!changes.length && null}
          {changes.map((c) => <p className="mono" key={c.param}>{c.param}: <span className="old">{String(c.from_value)}</span> → {String(c.to_value)}</p>)}
          <div className="field"><label className="label" htmlFor="p-reason">Reason</label><textarea id="p-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="row"><button className="btn accent" type="button" disabled={!changes.length || !ENVIRONMENTS[env].connected} onClick={submit}>Send for approval</button></div>
          {notice && <p className="note" role="status">{notice}</p>}
        </div>
        <Viewer3D params={params} highlight={changedKeys} theme={theme} />
        <div className="panel rise" style={stagger(1)}>
          <div className="row"><h2 style={{ marginRight: "auto" }}>Agent activity</h2><button className="btn ghost" type="button" disabled={!feed.length || playing} onClick={replay}>{playing ? "Replaying" : "Replay the edit"}</button></div>
          {!feed.length && <p className="muted">No agent edits yet, because the arm hasn't produced a run.</p>}
          <ol className="feed">
            {feed.map((f, i) => (
              <li key={f.id} className={cursor >= 0 && i > cursor ? "pending" : i === cursor ? "now" : ""}>
                <span className="label">From the run log</span>
                <b style={{ fontWeight: 600 }}>{f.title}</b>
                <span className="muted">{f.detail}</span>
              </li>
            ))}
          </ol>
          <p className="note">Replay of logged actions on the placeholder model. The analyst in the sample log is scripted.</p>
        </div>
      </div>
    </div>
  );
}
