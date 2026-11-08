import { useEffect, useRef, useState, type FormEvent } from "react";
import { addEdit, ACTION_LABEL, parsePrompt } from "../lib/edits";
import { runsFor, useAppSession } from "../lib/context";

interface Line {
  role: string;
  text: string;
}

const sessions = new Map<string, Line[]>();

/** Steering by prompt. A recognized prompt becomes an edit on the graph. No model is connected yet, and it says so. */
export function ChatDock({ runId }: { runId: string | null }) {
  const { env, operator } = useAppSession();
  const [open, setOpen] = useState(false); // one click away, so the page gets the room
  const [text, setText] = useState("");
  const [, refresh] = useState(0);
  const lines = sessions.get(env) ?? [];
  const log = useRef<HTMLDivElement>(null);
  const runs = runsFor(env);
  const run = runs.find((r) => r.id === runId) ?? runs[0];
  const history = run ? run.messages.map((m) => ({ role: m.role, text: m.text })) : [];

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [lines.length, open]);

  const send = (e: FormEvent) => {
    e.preventDefault();
    const value = text.trim();
    if (!value || !run) return;
    const parsed = parsePrompt(value, run.scene.controls.map((c) => c.id));
    const step = run.steps.find((s) => s.step.target === parsed.target);
    const edit = addEdit(env, { runId: run.id, nodeId: step?.step.id ?? null, target: parsed.target, action: parsed.action, reason: parsed.reason, params: { skill: step?.step.skill ?? "press" }, by: operator.name });
    const reply = parsed.action === "note"
      ? `Saved as note ${edit.id}. No model is connected in this build, so nothing will answer yet. Try "retry button_2 because the cap may rub".`
      : `${edit.id} added: ${ACTION_LABEL[parsed.action]} on ${parsed.target}. It's on the graph and in the revision history.`;
    sessions.set(env, [...lines, { role: operator.name, text: value }, { role: "console", text: reply }]);
    refresh((n) => n + 1);
    setText("");
  };

  return (
    <aside className={`chat ${open ? "" : "closed"}`} aria-label="Chat and steering">
      <div className="chat-head">
        {open && <span className="label" style={{ marginRight: "auto" }}>Chat and steering</span>}
        <button className="linkbtn" type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? "Close chat" : "Open chat"}>{open ? "Close" : <><span aria-hidden="true">◂</span><span className="chattab">Chat and steering</span></>}</button>
      </div>
      {open && (
        <>
          <div className="chat-log" ref={log} aria-live="polite">
            {!run && <p className="muted">No run to steer.</p>}
            {[...history, ...lines].map((m, i) => (
              <div key={i} className={`msg ${m.role === operator.name ? "user" : ""}`}>
                <span className="label">{m.role}</span>
                <span>{m.text}</span>
              </div>
            ))}
          </div>
          <form onSubmit={send}>
            <div className="field">
              <label className="label" htmlFor="chat-input">Ask or steer</label>
              <textarea id="chat-input" rows={2} value={text} disabled={!run} placeholder="Retry button_2 because the cap may rub" onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }} />
            </div>
          </form>
        </>
      )}
    </aside>
  );
}
