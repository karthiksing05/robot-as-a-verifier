import { Pill, stagger } from "../components/ui";
import { useAppSession } from "../lib/context";
import { ACTION_LABEL, approvalBlock, decideEdit, toCommand, useEdits } from "../lib/edits";

export function Approvals() {
  const { env, operator } = useAppSession();
  const edits = useEdits(env);
  const pending = edits.filter((e) => e.state === "planned");
  const decided = edits.filter((e) => e.state === "approved" || e.state === "rejected");

  return (
    <div className="page">
      <div className="stack">
        <h1 className="title">Change Review</h1>
      </div>
      {!pending.length && <div className="empty rise"><h2>Nothing is waiting for approval</h2></div>}
      {pending.map((e, i) => {
        const block = approvalBlock(e, operator);
        const command = toCommand(e);
        return (
          <article className="panel rise" key={e.id} style={stagger(i)}>
            <div className="row">
              <span className="mono">{e.id}</span>
              <Pill status="planned">{ACTION_LABEL[e.action]}</Pill>
              <span className="mono muted">{e.target ?? e.patch?.file}</span>
              <span className="mono muted" style={{ marginLeft: "auto" }}>Proposed by {e.by}</span>
            </div>
            <p>“{e.reason}”</p>
            {e.patch && e.patch.changes.map((c) => <p className="mono" key={c.param}>{c.param}: <span className="old">{String(c.from_value)}</span> → {String(c.to_value)}</p>)}
            <dl className="kv">
              <dt>Cost</dt>
              <dd>{e.action === "cad_patch" ? "A reprint takes about 15 to 40 minutes (docs/product.md)." : "One more guarded step on the arm."}</dd>
            </dl>
            {command && <details><summary className="note" style={{ cursor: "pointer" }}>Command this would send</summary><pre className="code">{JSON.stringify(command, null, 2)}</pre></details>}
            {block && <p className="note">{block}</p>}
            <div className="row">
              <button className="btn accent" type="button" disabled={!!block} onClick={() => decideEdit(env, e.id, "approved", operator.name)}>Approve</button>
              <button className="btn danger" type="button" disabled={!!block} onClick={() => decideEdit(env, e.id, "rejected", operator.name)}>Reject</button>
            </div>
          </article>
        );
      })}
      {decided.length > 0 && (
        <div className="panel rise">
          <h2>Decided</h2>
          <div className="scrollx"><table>
            <thead><tr><th>Edit</th><th>Type</th><th>Reason</th><th>Decision</th><th>By</th></tr></thead>
            <tbody>{decided.map((e) => <tr key={e.id}><td className="n">{e.id}</td><td className="n">{ACTION_LABEL[e.action]}</td><td>{e.reason}</td><td><Pill status={e.state}>{e.state}</Pill></td><td className="n">{e.decidedBy ?? "No approval needed"}</td></tr>)}</tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
