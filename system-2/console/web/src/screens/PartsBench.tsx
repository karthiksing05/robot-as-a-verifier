import { useEffect, useState } from "react";
import { PartsViewer } from "../components/PartsViewer";
import { ProjectBar } from "../components/ProjectBar";
import { stagger } from "../components/ui";
import { faultParams, faultParts, loadCad, paramLabel, type CadModel } from "../lib/cad";
import { useAppSession } from "../lib/context";
import { splitLabel } from "../lib/gallery";
import { useProjects } from "../lib/projects";
import { ENVIRONMENTS } from "../lib/session";

/** An appliance's printed parts, Rev A against Rev B, and what each fix changes. */
export function PartsBench({ project: id, theme }: { project: string; theme: string }) {
  const { env } = useAppSession();
  const project = useProjects().find((p) => p.id === id);
  const [model, setModel] = useState<CadModel | null | undefined>(undefined);
  const [rev, setRev] = useState("A");
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => { void loadCad(id).then(setModel); }, [id]);

  const bar = ENVIRONMENTS[env].connected && project && <ProjectBar project={project} tab="cad" />;
  if (model === undefined) return <div className="page">{bar}<div className="sweep" role="status" aria-label="Loading the CAD" /></div>;
  if (!model) {
    return (
      <div className="page">{bar}
        <div className="empty rise"><h2>No printed CAD for {project?.name ?? id}</h2><a className="btn ghost" href="#/design-analysis">The test appliance</a></div>
      </div>
    );
  }

  const fault = model.faults.find((f) => f.id === picked);
  const marked = fault ? faultParts(fault, rev) : [];

  return (
    <div className="page" style={{ maxWidth: "none" }}>
      {bar}
      <div className="row">
        <div className="stack" style={{ marginRight: "auto" }}>
          <h1 className="title">Design Analysis</h1>
          <span className="label">{model.title} / {splitLabel(model.split)} / appliances/{model.id}</span>
        </div>
        <div className="seg" role="group" aria-label="Revision">
          {["A", "B"].map((r) => (
            <button key={r} type="button" aria-pressed={rev === r} disabled={!model.revs.includes(r)} title={!model.revs.includes(r) ? "Held out for scoring, so Rev B isn't shown" : undefined} onClick={() => setRev(r)}>Rev {r}</button>
          ))}
        </div>
      </div>
      <div className="partsbench">
        <PartsViewer model={model} rev={rev} marked={marked} theme={theme} />
        <div className="panel rise" style={stagger(1)}>
          <h2>{model.heldOut ? "Held out" : "What Rev B fixes"}</h2>
          {model.heldOut && <p className="muted">Held out for scoring, so its faults and its Rev B aren't shown.</p>}
          {!model.heldOut && !model.faults.length && <p className="muted">The device file lists no faults.</p>}
          <ul className="fixlist">
            {model.faults.map((f) => {
              const params = faultParams(f);
              const parts = [...new Set([...faultParts(f, "A"), ...faultParts(f, "B")])];
              return (
                <li key={f.id}>
                  <button type="button" className="fix" aria-pressed={picked === f.id} onClick={() => setPicked(picked === f.id ? null : f.id)}>
                    <span className="fixhead"><b>{f.id}</b><span className="chip">{f.class}</span></span>
                    <span className="fixwhat">{f.what}</span>
                    {params.map((p) => <span key={p.key} className="mono">{paramLabel(p.key)}: <span className="old">{String(p.from)}</span> → {String(p.to)}</span>)}
                    {parts.length > 0 && <span className="note">{parts.length === 1 ? "Part" : "Parts"}: {parts.join(", ")}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          {model.faults.length > 0 && <p className="note">Pick a fix to light up its parts. Switch revisions to compare them.</p>}
          {project && <a className="cardlive" href={`#/live?project=${project.id}`}>Run it live →</a>}
        </div>
      </div>
    </div>
  );
}
