// The product's mechanisms, drawn. Colors come from the theme's tokens through app.css, so these work in both themes.
const Arrow = () => (
  <defs><marker id="dg-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8 Z" fill="currentColor" /></marker></defs>
);

function Box({ x, y, w, h, title, sub, gate, center }: { x: number; y: number; w: number; h: number; title: string; sub?: string; gate?: boolean; center?: boolean }) {
  const tx = center ? x + w / 2 : x + 12, anchor = center ? "middle" : "start";
  return (
    <g>
      <rect className={gate ? "gate" : "box"} x={x} y={y} width={w} height={h} rx="1" />
      <text className="t" x={tx} y={y + (sub ? h / 2 - 3 : h / 2 + 4)} textAnchor={anchor}>{title}</text>
      {sub && <text className="sub" x={tx} y={y + h / 2 + 14} textAnchor={anchor}>{sub}</text>}
    </g>
  );
}

export function Figure({ caption, label, width, children }: { caption: string; label: string; width: number; children: React.ReactNode }) {
  return (
    <figure className="dgfig">
      <div className="dgscroll">
        <svg className="dg" style={{ minWidth: Math.min(width, 560) }} viewBox={`0 0 ${width} ${(children as React.ReactElement<{ "data-h": number }>).props["data-h"]}`} role="img" aria-label={label}>
          <Arrow />
          {children}
        </svg>
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/** Who may write to what. The missing arrow is the point. */
export function TrustLoop() {
  return (
    <Figure width={820} label="The model proposes a plan or patch. Code moves the arm. Sensors produce verdicts. Code computes the score, which goes back to the model. The model has no path to write verdicts." caption="The loop is closed, and one write path doesn't exist: nothing the model produces can reach a verdict.">
      <g data-h={250}>
        <Box x={10} y={40} w={200} h={70} title="The model thinks" sub="proposes plans and patches" />
        <Box x={310} y={40} w={200} h={70} title="Code moves" sub="routines with hard limits" />
        <Box x={610} y={40} w={200} h={70} title="Sensors decide" sub="force, travel, readout" gate />
        <Box x={310} y={170} w={200} h={60} title="Score" sub="recomputable from the log" />
        <line className="a" x1="210" y1="75" x2="308" y2="75" markerEnd="url(#dg-arrow)" /><text className="lab" x="259" y="66" textAnchor="middle">a plan</text>
        <line className="a" x1="510" y1="75" x2="608" y2="75" markerEnd="url(#dg-arrow)" /><text className="lab" x="559" y="66" textAnchor="middle">contact</text>
        <path className="a" d="M710 110 V200 H512" markerEnd="url(#dg-arrow)" /><text className="lab" x="610" y="192" textAnchor="middle">verdicts</text>
        <path className="a" d="M310 200 H110 V112" markerEnd="url(#dg-arrow)" /><text className="lab" x="210" y="192" textAnchor="middle">evidence</text>
        <path className="no" d="M170 40 C 320 -8, 500 -8, 650 40" /><text className="nolab" x="410" y="10" textAnchor="middle">no write path</text>
      </g>
    </Figure>
  );
}

/** Time runs down. Only arrows across the dashed line reach the robot. */
export function RunFlow() {
  const Stage = ({ y, h, n, title, sub, gate }: { y: number; h: number; n: number; title: string; sub: string; gate?: boolean }) => <Box x={360} y={y} w={300} h={h} title={`${n}  ${title}`} sub={sub} gate={gate} />;
  const Down = ({ from, to }: { from: number; to: number }) => <line className="a" x1="510" y1={from} x2="510" y2={to - 2} markerEnd="url(#dg-arrow)" />;
  return (
    <Figure width={720} label="A run moves down six stages in the harness. Explore and test cross to the robot through tools. Test repeats at every stop. Approve and the fix loop wait for sign-off. The fix loop returns to explore on the new revision." caption="Time runs down the page. Only arrows crossing the dashed line reach the robot. Amber boxes wait for sign-off.">
      <g data-h={590}>
        <text className="head" x="110" y="18" textAnchor="middle">THE ROBOT</text>
        <text className="head" x="510" y="18" textAnchor="middle">THE HARNESS</text>
        <line className="line" x1="280" y1="28" x2="280" y2="585" />
        <Box x={20} y={36} w={180} h={64} title="explore" sub="finds the controls" center />
        <Stage y={36} h={64} n={1} title="Explore" sub="takes back controls and a fallback plan" />
        <line className="a" x1="360" y1="56" x2="202" y2="56" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="280" y="50" textAnchor="middle">start</text>
        <line className="a" x1="200" y1="84" x2="358" y2="84" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="280" y="78" textAnchor="middle">scene</text>
        <Down from={100} to={124} />
        <Stage y={124} h={56} n={2} title="Plan" sub="ordered steps from a closed skill list" />
        <Down from={180} to={204} />
        <Stage y={204} h={56} n={3} title="Approve" sub="sign-off before any test" gate />
        <Down from={260} to={284} />
        <Box x={20} y={284} w={180} h={150} title="run the plan" sub="moves, retries, rules on verdicts" center />
        <rect className="box" x="360" y="284" width="300" height="150" rx="1" />
        <text className="t" x="372" y="304">4  Test</text>
        <rect className="in" x="372" y="316" width="226" height="42" /><text className="sub" x="384" y="342">log the stop, save the evidence</text>
        <rect className="in" x="372" y="382" width="226" height="42" /><text className="sub" x="384" y="408">decide: amend, skip or resume</text>
        <line className="a" x1="485" y1="358" x2="485" y2="380" markerEnd="url(#dg-arrow)" />
        <path className="a" d="M598 403 H620 V337 H600" markerEnd="url(#dg-arrow)" /><text className="sub" transform="translate(636 370) rotate(-90)" textAnchor="middle">next stop</text>
        <line className="a" x1="360" y1="302" x2="202" y2="302" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="280" y="296" textAnchor="middle">the plan</text>
        <line className="a" x1="200" y1="337" x2="370" y2="337" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="280" y="331" textAnchor="middle">a stop</text>
        <line className="a" x1="372" y1="403" x2="202" y2="403" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="280" y="397" textAnchor="middle">the answer</text>
        <Down from={434} to={458} />
        <Stage y={458} h={50} n={5} title="Report" sub="coverage from the verdicts alone" />
        <Down from={508} to={528} />
        <Stage y={528} h={54} n={6} title="Fix loop" sub="patch, code checks, sign-off" gate />
        <path className="a" d="M660 555 H692 V68 H662" markerEnd="url(#dg-arrow)" /><text className="sub" transform="translate(708 310) rotate(-90)" textAnchor="middle">retest the new revision</text>
      </g>
    </Figure>
  );
}

/** Heights from two photos: nearer things shift further between them. */
export function Parallax() {
  return (
    <Figure width={620} label="The wrist camera takes two photos 15 millimetres apart. A raised button shifts further between them than the panel behind it, and that difference gives its height." caption="A camera with no depth sensor still gets depth: what's nearer shifts further between two photos. Depth = focal length × baseline ÷ shift.">
      <g data-h={270}>
        <rect className="box" x="160" y="14" width="46" height="26" /><text className="sub" x="150" y="32" textAnchor="end">photo 1</text>
        <rect className="box" x="410" y="14" width="46" height="26" /><text className="sub" x="466" y="32">photo 2</text>
        <line className="a" x1="210" y1="27" x2="404" y2="27" markerEnd="url(#dg-arrow)" /><text className="lab" x="308" y="20" textAnchor="middle">15 mm</text>
        <line className="ray" x1="183" y1="40" x2="300" y2="190" /><line className="ray" x1="433" y1="40" x2="300" y2="190" />
        <line className="ray far" x1="183" y1="40" x2="350" y2="232" /><line className="ray far" x1="433" y1="40" x2="350" y2="232" />
        <rect className="surface" x="60" y="232" width="500" height="20" /><text className="sub" x="72" y="226">panel</text>
        <rect className="gate" x="272" y="190" width="56" height="42" /><text className="sub" x="372" y="212">raised button</text>
      </g>
    </Figure>
  );
}

/** What each verdict looks like in force against travel. Shapes, not a recording. */
export function ForceShapes() {
  const Plot = ({ x, name, d, note, stroke }: { x: number; name: string; d: string; note: string; stroke: string }) => (
    <g transform={`translate(${x} 0)`}>
      <text className="t" x="0" y="18">{name}</text>
      <line className="axis" x1="0" y1="32" x2="0" y2="170" /><line className="axis" x1="0" y1="170" x2="210" y2="170" />
      <line className="cap" x1="0" y1="58" x2="210" y2="58" /><text className="sub" x="210" y="52" textAnchor="end">force cap</text>
      <path className={stroke} d={d} />
      <text className="sub" x="0" y="190">{note}</text>
    </g>
  );
  return (
    <Figure width={760} label="Three force against travel shapes. A pass rises to a click and travels its full distance. A fail hits the force cap almost at once with barely any travel. A miss shows no force at all." caption="Shapes for illustration, not a recording. Force rises up the page and travel runs across. The readout confirms a pass: a control that clicks but changes nothing still fails.">
      <g data-h={200}>
        <Plot x={20} name="PASS" stroke="curve pass" d="M0 170 C 25 165, 45 112, 62 104 L 78 138 C 110 136, 150 134, 190 132" note="clicks at about 3 N, full travel" />
        <Plot x={275} name="FAIL" stroke="curve fail" d="M0 170 C 8 150, 14 80, 20 58" note="binds: 0.3 mm of travel, at the cap" />
        <Plot x={530} name="MISSED" stroke="curve muted" d="M0 168 L 190 167" note="no contact: not the device's fault" />
      </g>
    </Figure>
  );
}

/** The narrow channel between the systems. */
export function Boundary() {
  const left = ["Detection, depth, IK, control", "Skills, sensors, verdict rules", "Safety and local retries", "50 Hz, needs no network"];
  const right = ["Frontier model and slash commands", "Plans and long-term memory", "Reports and the CAD fix loop", "Seconds per turn, between steps"];
  const Side = ({ x, title, rows }: { x: number; title: string; rows: string[] }) => (
    <g>
      <rect className="box" x={x} y="10" width="260" height="190" />
      <text className="t" x={x + 14} y="36">{title}</text>
      {rows.map((r, i) => <text key={r} className="sub" x={x + 14} y={68 + i * 30}>{r}</text>)}
    </g>
  );
  return (
    <Figure width={780} label="System 1, the robot, and System 2, the harness. Routines go to the robot, stops come back, and raw telemetry goes only to the screen, never to the model." caption="Two systems that can run on different laptops. A model turn takes seconds and the control loop runs at 50 Hz, so no prompt can ever drive a joint.">
      <g data-h={210}>
        <Side x={10} title="SYSTEM 1: THE ROBOT" rows={left} />
        <Side x={510} title="SYSTEM 2: THE HARNESS" rows={right} />
        <line className="line" x1="390" y1="10" x2="390" y2="200" />
        <line className="a" x1="510" y1="60" x2="272" y2="60" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="390" y="54" textAnchor="middle">routines, plans</text>
        <line className="a" x1="270" y1="110" x2="508" y2="110" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="390" y="104" textAnchor="middle">stops, with numbers</text>
        <line className="a dim" x1="270" y1="160" x2="508" y2="160" markerEnd="url(#dg-arrow)" /><text className="lab halo" x="390" y="154" textAnchor="middle">telemetry: to the screen only</text>
      </g>
    </Figure>
  );
}
