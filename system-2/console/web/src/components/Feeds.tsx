import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { LIVE_URL } from "../lib/live";
import { LiveSource } from "../lib/simsource";
import type { SimFocus } from "./Sim3D";

const Sim3D = lazy(() => import("./Sim3D"));

/** The rig has no global camera any more, only the wrist one: the sim's desk and phone cameras stay out of the Console. */
const GLOBAL = /\b(i?phone|desk view|film camera)\b/i;

/** Each camera keeps its own element, so promoting one never drops its stream. url: where the streams are. real: the real
 * arm, whose wrist camera (System 1's live window, overlays and all) starts as the big view, untagged: a tag would cover
 * the window's own status line. Its 3D view is the arm from its joint readings and the last scan's parts, reloaded each
 * time it's made big, as a scan changes the parts. */
export function Feeds({ runId, url = LIVE_URL, feeds, stage, computing, focus, real = false }: { runId: string | null; url?: string; feeds: string[]; stage?: string; computing: boolean; focus: SimFocus; real?: boolean }) {
  const [big, setBig] = useState(real ? "wrist" : "main");
  const [no3D, setNo3D] = useState(false);
  const unavailable = useCallback(() => setNo3D(true), []);
  const source = useMemo(() => new LiveSource(real ? null : runId, url), [real, runId, url]); // the real System 1 has its own run id
  const all = feeds.map((title, i) => ({ id: url === LIVE_URL ? `panel${i}` : title, title: title === "wrist" ? "Wrist camera" : title })) // the bridge numbers its streams, System 1 names them
    .filter((f) => !GLOBAL.test(f.title));
  if (no3D) all.unshift({ id: "main", title: "Scene" });
  const large = big === "main" || all.some((f) => f.id === big) ? big : "main";
  return (
    <section className="feeds" aria-label="Cameras" data-stage={stage}>
      {real && !all.length && <div className="feedcell agentnosim">No wrist camera from System 1 yet</div>}
      {!no3D && (
        <div className={`feedcell simcell ${large === "main" ? "big" : ""}`} style={real ? { order: large === "main" ? -1 : 1 } : undefined}>
          <Suspense fallback={<div className="simloading"><div className="sweep" /></div>}><Sim3D key={real ? large : undefined} source={source} focus={focus} onUnavailable={unavailable} /></Suspense>
          {large !== "main" && <button type="button" className="simcover" aria-label="Show the 3D view large" onClick={() => setBig("main")} />}
        </div>
      )}
      {all.map((f) => (
        <button key={f.id} type="button" className={`feedcell ${f.id === large ? "big" : ""}`} aria-pressed={f.id === large} aria-label={`Show ${f.title} large`} onClick={() => setBig(f.id)}>
          <img src={`${url}/feed/${f.id}`} alt={f.title} />
          {!real && <span className="feedtag">{f.title}</span>}
        </button>
      ))}
      {computing && <div className="computing" role="status"><div className="sweep" /><span>Perception computing</span></div>}
    </section>
  );
}
