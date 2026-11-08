import { useState } from "react";
import { Pill, downloadText } from "../components/ui";
import { useAppSession } from "../lib/context";
import { ACTION_LABEL, decideEdit, resetEdits, useEdits } from "../lib/edits";

export function EditLog() {
  const { env, operator } = useAppSession();
  const edits = useEdits(env);
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="page">
      <div className="row">
        <div className="stack" style={{ marginRight: "auto" }}>
          <h1 className="title">Revision History</h1>
        </div>
        <button className="btn ghost" type="button" disabled={!edits.length} onClick={() => downloadText(`edits-${env}.jsonl`, edits.map((e) => JSON.stringify(e)).join("\n") + "\n")}>Export JSONL</button>
        {!confirming && <button className="btn ghost" type="button" disabled={!edits.length} onClick={() => setConfirming(true)}>Clear test edits</button>}
        {confirming && <>
          <button className="btn danger" type="button" onClick={() => { resetEdits(env); setConfirming(false); }}>Clear all in {env}</button>
          <button className="btn ghost" type="button" onClick={() => setConfirming(false)}>Keep them</button>
        </>}
      </div>
      {!edits.length
        ? <div className="empty rise"><h2>No edits yet</h2></div>
        : <div className="panel rise"><div className="scrollx"><table>
            <thead><tr><th>Edit</th><th>When</th><th>By</th><th>Type</th><th>Target</th><th>Reason</th><th>State</th><th /></tr></thead>
            <tbody>{edits.map((e) => (
              <tr key={e.id}>
                <td className="n">{e.id}</td>
                <td className="n">{new Date(e.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</td>
                <td className="n">{e.by}</td>
                <td className="n">{ACTION_LABEL[e.action]}</td>
                <td className="n">{e.target ?? "–"}</td>
                <td>{e.reason}</td>
                <td><Pill status={e.state}>{e.state}</Pill></td>
                <td>{e.state !== "withdrawn" && <button className="linkbtn" type="button" onClick={() => decideEdit(env, e.id, "withdrawn", operator.name)}>Withdraw</button>}</td>
              </tr>
            ))}</tbody>
          </table></div></div>}
    </div>
  );
}
