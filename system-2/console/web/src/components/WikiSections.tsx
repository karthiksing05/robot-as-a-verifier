// The wiki's Journey, Models, Device theory and Devices sections. Models and devices read generated data,
// so a new round or a new doc shows up after `uv run python -m rav_harness.results_page`.
import { Fragment, useState } from "react";
import { JOURNEY, type Stage } from "../lib/journey";
import { GALLERY, splitLabel } from "../lib/gallery";
import { demoHref, fmtCredits, fmtRatio, fmtScore, fmtShare, fmtTokens, fmtUsd, loadResults, modelName, pieceName, sections, tiedOnScore, type Round } from "../lib/wikidata";

const data = import.meta.glob("../data/{model-results,wiki-docs}.json", { import: "default", eager: true }) as Record<string, unknown>;
const RESULTS = loadResults(data["../data/model-results.json"]);
const DOCS = (data["../data/wiki-docs.json"] ?? {}) as { theory?: string | null; devices?: string | null };

const STAGE_PILL: Record<Stage, string> = { done: "passed", "in progress": "inconclusive", planned: "planned" };

export function Journey() {
  const [area, setArea] = useState<string>("All");
  const areas = ["All", "Robot", "Model", "Product"];
  const shown = JOURNEY.filter((t) => area === "All" || t.area === area);
  return (
    <>
      <div className="seg" role="group" aria-label="Show turns about">
        {areas.map((a) => <button key={a} type="button" aria-pressed={area === a} onClick={() => setArea(a)}>{a}</button>)}
      </div>
      <ol className="journey">
        {shown.map((t) => (
          <li key={t.title} data-stage={t.stage}>
            <div className="jwhen"><span className="label">{t.when}</span><span className="label">{t.area}</span></div>
            <i className="jdot" aria-hidden="true" />
            <div className="jcard">
              <div className="jhead"><b>{t.title}</b>{t.stage !== "done" && <span className={`pill ${STAGE_PILL[t.stage]}`}>{t.stage}</span>}</div>
              <p><span className="label">Problem</span>{t.problem}</p>
              <p><span className="label">Change</span>{t.change}</p>
              {t.evidence && <p className="jevidence">{t.evidence}</p>}
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}

function RoundTable({ round }: { round: Round }) {
  const maxTokens = Math.max(1, ...round.rows.map((r) => r.tokens));
  const misses = round.rows.filter((r) => r.missed.length);
  return (
    <>
      <div className="tablewrap wikitable">
        <table className="modeltable">
          <thead>
            <tr><th>Model</th><th>Score</th><th>Faults found</th><th>False findings</th><th>Coverage</th><th>Recovered</th><th>Tokens</th><th>Credits</th><th>Dollars*</th><th>Median turn</th><th>Tool errors</th><th>Reasoning</th><th>Runs</th></tr>
          </thead>
          <tbody>
            {round.rows.map((r) => (
              <tr key={r.model} className={r.baseline ? "baseline" : undefined}>
                <td className="mname">{modelName(r.model)}</td>
                <td className="n">{fmtScore(r.score)}</td>
                <td className="n">{fmtRatio(r.faults_found, r.faults_planted)}</td>
                <td className="n">{r.false_findings}</td>
                <td className="n">{fmtShare(r.coverage)}</td>
                <td className="n">{fmtRatio(r.recovered, r.recovery_tries)}</td>
                <td className="n"><span className="tokbar" style={{ "--w": r.tokens / maxTokens } as React.CSSProperties}>{r.baseline ? "–" : fmtTokens(r.tokens)}</span></td>
                <td className="n">{r.baseline ? "–" : fmtCredits(r.credits)}</td>
                <td className="n">{r.baseline ? "–" : fmtUsd(r.usd)}</td>
                <td className="n">{r.median_turn_s === null ? "–" : `${r.median_turn_s.toFixed(1)} s`}</td>
                <td className="n">{r.baseline ? "–" : r.tool_errors}</td>
                <td className="note">{r.baseline ? "–" : r.reasoning_chars > 0 ? "Returned" : r.reasoning ?? "None returned"}</td>
                <td className="n">{r.runs}{r.crashes ? ` (${r.crashes} crashed)` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {round.cost && (
        <p className="note">
          Round total: {fmtTokens(round.cost.tokens)} tokens, {fmtCredits(round.cost.credits)} AI credits, {fmtUsd(round.cost.usd)}.
          {RESULTS.pricing && ` *Dollars assume $${RESULTS.pricing.usd_per_credit.toFixed(2)} per AI credit, an assumption; credits are from ${RESULTS.pricing.source ?? "Snowflake's price table"}.`}
        </p>
      )}
      {round.rows.filter((r) => r.per_run.length && !r.baseline).map((r) => (
        <details key={`cost-${r.model}`} className="misses">
          <summary className="note">{modelName(r.model)}: cost per run ({r.per_run.length})</summary>
          <ul className="plainlist note">{r.per_run.map((x) => <li key={x.run}>{x.run}: {fmtTokens(x.tokens)} tokens, {fmtCredits(x.credits)} credits, {fmtUsd(x.usd)}</li>)}</ul>
        </details>
      ))}
      {misses.map((r) => (
        <details key={r.model} className="misses">
          <summary className="note">What {modelName(r.model)} missed ({r.missed.length})</summary>
          <ul className="plainlist note">{r.missed.map((m) => <li key={m}>{m}</li>)}</ul>
        </details>
      ))}
    </>
  );
}

export function ModelResults() {
  return (
    <div className="rounds">
      {RESULTS.rounds.map((round) => (
        <article key={round.id} className="round" data-status={round.status}>
          <header className="roundhead">
            <span className="wikistep">ROUND {round.id}</span>
            <b>{round.title}</b>
            <span className={`pill ${round.status === "done" ? "passed" : round.status === "running" ? "inconclusive" : "planned"}`}>{round.status}</span>
            {round.date && <span className="note">{round.date}</span>}
          </header>
          <p>{round.test_set}</p>
          {round.rows.length ? (
            <>
              {round.takeaway && <p className={`roundtake${tiedOnScore(round) ? " tied" : ""}`}>{round.takeaway}</p>}
              <RoundTable round={round} />
              {round.spend && <p className="note">{round.spend}</p>}
            </>
          ) : (
            <div className="empty">{round.status === "running" ? "Running now. Results appear here once its runs finish and the page is regenerated." : "Not run yet."}</div>
          )}
        </article>
      ))}
      {RESULTS.route && <p className="note">Every model is reached through {RESULTS.route}, with the same prompts and tools. Updated {RESULTS.generated}.</p>}
    </div>
  );
}

/** Inline markdown: bold, code and links. Enough for the docs these sections carry. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  return <>{parts.map((p, i) => {
    if (/^\*\*.+\*\*$/.test(p)) return <b key={i}>{p.slice(2, -2)}</b>;
    if (/^`.+`$/.test(p)) return <code key={i}>{p.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(p);
    if (link) return /^https?:/.test(link[2]) ? <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : <Fragment key={i}>{link[1]}</Fragment>;
    return <Fragment key={i}>{p.replace(/\*([^*]+)\*/g, "$1")}</Fragment>;
  })}</>;
}

/** Paragraphs, lists, tables and small headings from a doc's lines. */
function Md({ lines }: { lines: string[] }) {
  const blocks: { kind: "p" | "ul" | "table" | "h"; lines: string[] }[] = [];
  for (const line of lines) {
    const kind = /^\s*\|/.test(line) ? "table" : /^\s*([-*]|\d+\.)\s/.test(line) ? "ul" : /^#{3,}\s/.test(line) ? "h" : line.trim() ? "p" : null;
    const last = blocks[blocks.length - 1];
    if (!kind) { blocks.push({ kind: "p", lines: [] }); continue; }
    if (last && last.kind === kind && kind !== "h") last.lines.push(line);
    else blocks.push({ kind, lines: [line] });
  }
  return <>{blocks.filter((b) => b.lines.length).map((b, i) => {
    if (b.kind === "h") return <h3 key={i} className="label">{b.lines[0].replace(/^#+\s*/, "")}</h3>;
    if (b.kind === "ul") return <ul key={i} className="plainlist">{b.lines.map((l, j) => <li key={j}><Inline text={l.replace(/^\s*([-*]|\d+\.)\s+/, "")} /></li>)}</ul>;
    if (b.kind === "table") {
      const rows = b.lines.filter((l) => !/^\s*\|[\s:|-]+\|\s*$/.test(l)).map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
      return <div key={i} className="tablewrap wikitable"><table><thead><tr>{rows[0].map((c, j) => <th key={j}><Inline text={c} /></th>)}</tr></thead><tbody>{rows.slice(1).map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}><Inline text={c} /></td>)}</tr>)}</tbody></table></div>;
    }
    return <p key={i}><Inline text={b.lines.join(" ")} /></p>;
  })}</>;
}

const Waiting = ({ doc }: { doc: string }) => <div className="empty"><p>Not written yet. This fills in from <code>{doc}</code> once it lands and the page is regenerated.</p></div>;

export function DeviceTheory() {
  if (!DOCS.theory) return <Waiting doc="docs/device-theory.md" />;
  const { intro, parts } = sections(DOCS.theory);
  return (
    <>
      <Md lines={intro} />
      <div className="theorygrid">
        {parts.map((s) => (
          <div key={s.title} className="theorycard">
            <b>{s.title}</b>
            {s.fields.length > 0 && <dl className="kv">{s.fields.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd><Inline text={v} /></dd></Fragment>)}</dl>}
            <Md lines={s.body} />
          </div>
        ))}
      </div>
    </>
  );
}

export function Devices() {
  if (!DOCS.devices) return <Waiting doc="docs/devices.md" />;
  const intro = sections(DOCS.devices, 3).intro;
  return (
    <>
      <Md lines={intro} />
      <div className="devicegrid">
        {GALLERY.map((c) => (
          <article key={c.id ?? c.name} className="devicecard" id={c.id ? `device-${c.id}` : undefined}>
            <header><b>{c.name}</b>{c.split && <span className={`pill ${c.heldOut ? "skipped" : "observed"}`}>{splitLabel(c.split)}</span>}</header>
            {c.revisions.length > 0 && <div><span className="label">Revisions</span><div className="chips">{c.revisions.map((r) => <span key={r} className="chip">{r}</span>)}</div></div>}
            <Md lines={c.body} />
            {c.controls.length > 0 && <div><span className="label">Controls</span><div className="chips">{c.controls.map((x) => <span key={x} className="chip">{x}</span>)}</div></div>}
            {c.theory.length > 0 && <div><span className="label">Theory it exercises</span><div className="chips">{c.theory.map((x) => <span key={x} className="chip accent" title={x}>{pieceName(x)}</span>)}</div></div>}
            {c.planted && <details className="planted"><summary className="label">Planted faults</summary><p><Inline text={c.planted} /></p></details>}
            {c.extra.length > 0 && <dl className="kv">{c.extra.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd><Inline text={v} /></dd></Fragment>)}</dl>}
            {c.heldOut && <p className="note">Held out for scoring, so its faults aren't shown.</p>}
            <a className="devicerun" href={demoHref(c)}>Run it in the Demo →</a>
          </article>
        ))}
      </div>
    </>
  );
}
