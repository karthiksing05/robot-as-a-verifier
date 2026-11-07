import { useState, type FormEvent } from "react";
import { addEdit, ACTION_LABEL, toCommand, type EditAction } from "../lib/edits";
import { useAppSession } from "../lib/context";

const ACTIONS: EditAction[] = ["retry", "fine_tune", "add_test", "prioritize", "skip", "note"];
const HARD_CAP_N = 15; // docs/decisions.md D21

interface Props {
  runId: string;
  nodeId: string;
  target: string | null;
  skill?: string;
  onAdded?: (id: string) => void;
}

/** Changes the exploration. A reason is required, because it travels with the edit into bug reports and the report. */
export function EditForm({ runId, nodeId, target, skill = "press", onAdded }: Props) {
  const { env, operator } = useAppSession();
  const [action, setAction] = useState<EditAction>("retry");
  const [reason, setReason] = useState("");
  const [forceLimit, setForceLimit] = useState("6");
  const [points, setPoints] = useState("3");
  const [error, setError] = useState("");

  const params: Record<string, string | number> = action === "fine_tune" ? { skill, force_limit: Number(forceLimit), press_points: Number(points) } : { skill };
  const command = toCommand({ action, target, params, reason, by: operator.name, nodeId });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) return setError("Add a reason. It's stored with this edit and shown on the bug report.");
    if (action === "fine_tune" && !(Number(forceLimit) > 0 && Number(forceLimit) <= HARD_CAP_N)) return setError(`Force limit must be above 0 and at most the ${HARD_CAP_N} N hard cap.`);
    setError("");
    const edit = addEdit(env, { runId, nodeId, target, action, reason: reason.trim(), params, by: operator.name });
    setReason("");
    onAdded?.(edit.id);
  };

  return (
    <form className="stack" onSubmit={submit}>
      <span className="label">Change the exploration</span>
      <div className="seg" role="group" aria-label="Edit type">
        {ACTIONS.map((a) => <button type="button" key={a} aria-pressed={a === action} onClick={() => setAction(a)}>{ACTION_LABEL[a]}</button>)}
      </div>
      {action === "fine_tune" && (
        <div className="row">
          <div className="field" style={{ width: 110 }}><label className="label" htmlFor="ef-force">Force limit, N</label><input id="ef-force" className="tech" type="number" min="0.5" max={HARD_CAP_N} step="0.5" value={forceLimit} onChange={(e) => setForceLimit(e.target.value)} /></div>
          <div className="field" style={{ width: 110 }}><label className="label" htmlFor="ef-points">Press points</label><input id="ef-points" className="tech" type="number" min="1" max="9" value={points} onChange={(e) => setPoints(e.target.value)} /></div>
        </div>
      )}
      <div className="field">
        <label className="label" htmlFor="ef-reason">Reason</label>
        <textarea id="ef-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Find which side of the cap rubs." />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="row"><button className="btn accent" type="submit">Add to exploration</button></div>
      {command && <details><summary className="note" style={{ cursor: "pointer" }}>Command this would send</summary><pre className="code">{JSON.stringify(command, null, 2)}</pre></details>}
    </form>
  );
}
