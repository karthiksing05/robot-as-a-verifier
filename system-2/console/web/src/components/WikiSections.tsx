// The wiki's Journey, Models, Device theory and Devices sections. Models and devices read generated data,
// so a new round or a new doc shows up after `uv run python -m rav_harness.results_page`.
import { Fragment, useState } from "react";
import { JOURNEY, type Stage } from "../lib/journey";
import { GALLERY, splitLabel } from "../lib/gallery";
import { chartPanels, demoHref, fmtCredits, fmtRatio, fmtScore, fmtShare, fmtTokens, fmtUsd, loadResults, modelName, logDomain, pieceName, sections, tiedOnScore, type Round } from "../lib/wikidata";

const data = import.meta.glob("../data/{model-results,wiki-docs}.json", { import: "default", eager: true }) as Record<string, unknown>;
export const RESULTS = loadResults(data["../data/model-results.json"]);
const DOCS = (data["../data/wiki-docs.json"] ?? {}) as { theory?: string | null; devices?: string | null };

const STAGE_PILL: Record<Stage, string> = { done: "passed", "in progress": "inconclusive", planned: "planned" };

const LANES = ["Robot", "Model", "Product"] as const;

/** The design's turns as a timeline: one lane per area, one column per date. Pick a turn to read it. */
export function Journey() {
  const dates = [...new Set(JOURNEY.map((t) => t.when))];
  const [picked, setPicked] = useState(0);
  const turn = JOURNEY[picked];
  return (
    <figure className="mfig" aria-label="Timeline of the design's turns, by date and by area: robot, model and product.">
      <div className="tl3" style={{ "--cols": dates.length } as React.CSSProperties}>
        <span className="label tl3corner">Nov</span>
        {dates.map((d) => <span key={d} className="label tl3date">{d.replace(/^Nov\s*/, "")}</span>)}
        {LANES.map((lane) => (
          <Fragment key={lane}>
            <span className="label tl3lane">{lane}</span>
            {dates.map((d) => (
              <div key={d} className="tl3cell">
                {JOURNEY.map((t, i) => t.area === lane && t.when === d && (
                  <button key={t.title} type="button" className="tl3dot" data-stage={t.stage} aria-pressed={picked === i} aria-label={`${i + 1}. ${t.title}, ${t.when}, ${t.stage}`} title={t.title} onClick={() => setPicked(i)}>{i + 1}</button>
                ))}
              </div>
            ))}
          </Fragment>
        ))}
      </div>
      <div className="jcard tl3card" data-stage={turn.stage} aria-live="polite">
        <div className="jhead"><span className="wikistep">{picked + 1}</span><b>{turn.title}</b><span className="label">{turn.when} · {turn.area}</span>{turn.stage !== "done" && <span className={`pill ${STAGE_PILL[turn.stage]}`}>{turn.stage}</span>}</div>
        <p><span className="label">Problem</span>{turn.problem}</p>
        <p><span className="label">Change</span>{turn.change}</p>
        {turn.evidence && <p className="jevidence">{turn.evidence}</p>}
      </div>
    </figure>
  );
}

const SHAPES = ["circle", "square", "triangle", "diamond"] as const;
const slotOf = (model: string) => Math.max(0, RESULTS.models.indexOf(model)) % SHAPES.length;

function Mark({ x, y, slot, size = 5 }: { x: number; y: number; slot: number; size?: number }) {
  const shape = SHAPES[slot];
  const cls = `mk m${slot + 1}`;
  if (shape === "circle") return <circle className={cls} cx={x} cy={y} r={size} />;
  if (shape === "square") return <rect className={cls} x={x - size + 0.5} y={y - size + 0.5} width={2 * size - 1} height={2 * size - 1} />;
  if (shape === "triangle") return <path className={cls} d={`M${x} ${y - size - 1} L${x + size + 0.5} ${y + size - 0.5} L${x - size - 0.5} ${y + size - 0.5} Z`} />;
  return <path className={cls} d={`M${x} ${y - size - 1} L${x + size + 1} ${y} L${x} ${y + size + 1} L${x - size - 1} ${y} Z`} />;
}

/** Moves a mark that would sit on top of an earlier one sideways by a mark's width, so every model stays visible. */
function dodge<T extends { cx: number; cy: number }>(marks: T[]): T[] {
  const placed: T[] = [];
  for (const m of marks) {
    let cx = m.cx;
    while (placed.some((o) => Math.abs(o.cx - cx) < 9 && Math.abs(o.cy - m.cy) < 9)) cx += 10;
    placed.push({ ...m, cx });
  }
  return placed;
}

/** Faults found against dollars per device, one small chart per scored round. */
export function ModelChart() {
  const panels = chartPanels(RESULTS);
  const [lo, hi] = logDomain(panels.flatMap((p) => p.points.map((x) => x.perDevice)));
  const [hover, setHover] = useState<string | null>(null);
  if (!panels.length) return null;
  const W = 280, H = 170, L = 38, R = 12, T = 12, B = 34;
  const x = (v: number) => L + ((Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * (W - L - R);
  const y = (share: number) => T + (1 - share) * (H - T - B);
  const ticks: number[] = [];
  for (let v = lo; v <= hi * 1.001; v *= 10) ticks.push(v);
  const money = (v: number) => (v >= 1 ? `$${v.toFixed(0)}` : `$${v.toPrecision(1).replace(/^0/, "")}`);
  return (
    <figure className="mfig" aria-label="Small multiples, one per scored round: each model's share of planted faults found against its dollars per device, on a log scale, with the rule baseline as a dashed line.">
      <div className="mlegend" aria-hidden="true">
        {RESULTS.models.map((m) => <span key={m}><svg width="14" height="14" viewBox="0 0 14 14"><Mark x={7} y={7} slot={slotOf(m)} size={4.5} /></svg>{modelName(m)}</span>)}
        <span><svg width="22" height="14" viewBox="0 0 22 14"><line className="basel" x1="0" y1="7" x2="22" y2="7" /></svg>Rules baseline</span>
      </div>
      <div className="mpanels">
        {panels.map((p) => {
          const shown = p.points.find((q) => `${p.id}:${q.model}` === hover);
          return (
            <div key={p.id} className="mpanel">
              <div className="mpanelhead"><span className="wikistep">ROUND {p.id}</span><span className="note">{p.title}</span></div>
              <svg className="mdg" viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`mc-${p.id}`}>
                <title id={`mc-${p.id}`}>{`Round ${p.id}: ${p.points.map((q) => `${modelName(q.model)} found ${q.found} of ${q.planted} at ${fmtUsd(q.perDevice)} per device`).join("; ")}${p.baseline !== null ? `; rules baseline found ${Math.round(p.baseline * 100)}%` : ""}`}</title>
                {[0, 0.5, 1].map((s) => <g key={s}><line className="grid" x1={L} x2={W - R} y1={y(s)} y2={y(s)} /><text className="lab" x={L - 6} y={y(s) + 4} textAnchor="end">{s * 100}%</text></g>)}
                {ticks.map((v) => <text key={v} className="lab" x={x(v)} y={H - B + 16} textAnchor="middle">{money(v)}</text>)}
                <text className="lab dim" x={W - R} y={H - 3} textAnchor="end">per device, log scale</text>
                {p.baseline !== null && <line className="basel" x1={L} x2={W - R} y1={y(p.baseline)} y2={y(p.baseline)} />}
                {dodge(p.points.map((q) => ({ q, cx: x(q.perDevice), cy: y(q.share) }))).map(({ q, cx, cy }) => (
                  <g key={q.model} tabIndex={0} className="mpt" onMouseEnter={() => setHover(`${p.id}:${q.model}`)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(`${p.id}:${q.model}`)} onBlur={() => setHover(null)}>
                    <circle className="hit" cx={cx} cy={cy} r="12" />
                    <Mark x={cx} y={cy} slot={slotOf(q.model)} />
                  </g>
                ))}
              </svg>
              <p className="note mreadout">{shown ? `${modelName(shown.model)}: ${shown.found} of ${shown.planted} faults, ${fmtUsd(shown.perDevice)} per device` : " "}</p>
            </div>
          );
        })}
      </div>
    </figure>
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
