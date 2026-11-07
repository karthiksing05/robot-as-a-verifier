import { TrustLoop } from "../components/Diagrams";

const LADDER = [
  ["Mathematics", "Formal proofs", "A proof kernel", "Whether the formal statement says what was meant"],
  ["Software", "Code", "Tests, review, formal specs", "Whether the tests and specs capture what users need"],
  ["Hardware", "CAD and designs", "A person with a checklist", "Whether the product works once someone touches it"],
] as const;

const PAIRS = [
  ["AI prover", "Frontier model"],
  ["Formal statement", "Manual and spec"],
  ["Proof kernel", "Sensor rules"],
  ["Checked proof", "Run log"],
  ["Statement audit", "A person approves the plan"],
] as const;

export function Motivation() {
  return (
    <div className="essay">
      <header className="rise">
        <span className="label">Motivation</span>
        <h1 className="essaytitle">AI can propose designs faster than anyone can check them.</h1>
        <p className="wikilede">The scarce step is shifting from making things to knowing they're right. Mathematics and software are building machines for that. Physical products mostly still rely on a person pressing buttons and taking notes.</p>
      </header>

      <section>
        <h2>The same gap, three times</h2>
        <div className="scrollx wikitable">
          <table className="ladder">
            <thead><tr><th>Field</th><th>AI now produces</th><th>What checks it</th><th>What stays open</th></tr></thead>
            <tbody>{LADDER.map((row) => <tr key={row[0]} className={row[0] === "Hardware" ? "here" : undefined}>{row.map((cell, i) => <td key={cell} className={i === 0 ? "n" : undefined}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>Why now</h2>
        <div className="evidencegrid">
          <article className="panel">
            <span className="bignum">13M</span>
            <p>Lines of Lean generated in 11 days, in the autoformalization of Fermat's Last Theorem announced by Anthropic on September 4, as <a href="https://terrytao.wordpress.com/2026/10/09/what-mathematicians-should-know-about-the-lean-theorem-proverquestions-of-reliability-and-ai/">Thomas Hales reports</a> in a guest post on Terence Tao's blog. Autoformalization is "the formalization of mathematics by AI."</p>
          </article>
          <article className="panel">
            <span className="bignum">96%</span>
            <p>Of developers "don't fully trust that AI-generated code is functionally correct," and only 48% always check it before committing, in <a href="https://www.sonarsource.com/blog/ai-coding-trust-gap/">Sonar's developer survey</a>. Sonar sells verification tools, so read this as direction rather than measurement.</p>
          </article>
          <article className="panel">
            <span className="bignum">Vericoding</span>
            <p>Formally verified program synthesis, or vericoding, now has <a href="https://arxiv.org/abs/2509.22908">its own benchmark</a>. Verification is becoming something AI is expected to do, and to be measured on.</p>
          </article>
        </div>
        <blockquote>"Is the verified theorem what we think it is?"<cite>Thomas Hales, on why a checked Lean proof still needs a human audit</cite></blockquote>
        <p>Even a perfect proof checker only answers the question it was given. A physical product has the same problem in a harder form: its CAD can be flawless and the door can still need a pinch to open.</p>
      </section>

      <section>
        <h2>The problem, stated precisely</h2>
        <p>Take a design <i>d</i> and an intent <i>I</i>: its manual and its rules. A proposer writes <i>d</i>, and we want evidence that <i>d</i> meets <i>I</i> in the physical world. A proof kernel is a program that can decide its question. A physical product has no kernel, so the only way to ask is an experiment.</p>
        <pre className="formal">{`for each control c found on the device:
  test(c)      an action within hard limits
  V(c)    ∈    { passed, failed, observed, skipped, inconclusive }
               decided by sensor rules, never by the proposer`}</pre>
        <div className="propgrid">
          <div><b>Separation</b><span>The proposer can't write to V.</span></div>
          <div><b>Accountable coverage</b><span>Every control found has a verdict, or a reason it doesn't.</span></div>
          <div><b>Recomputable</b><span>Anyone can rebuild the result from the log.</span></div>
        </div>
        <p><strong>This isn't a proof.</strong> A test can show that a fault exists, and "passed" only means passed what we tried. That's why the report has to show what wasn't tried. What we offer is honest evidence with stated limits, which is what physical products have been missing.</p>
      </section>

      <section>
        <h2>The same shape as a proof assistant</h2>
        <div className="pairs">
          <div className="pairhead"><span>Autoformalization</span><span /><span>Our verifier</span></div>
          {PAIRS.map(([a, b]) => <div key={a} className="pair"><span>{a}</span><i aria-hidden="true">→</i><b>{b}</b></div>)}
        </div>
      </section>

      <section>
        <h2>What we built</h2>
        <p>A low-cost robot arm explores a product, tests every control it finds, and reports what it measured. The design closes the loop from there: start from the manual, propose a CAD patch for each fault, and test the next revision the same way.</p>
        <TrustLoop />
      </section>

      <section>
        <h2>Why it matters</h2>
        <p>An AI that designs hardware can only improve against something it can't argue with. A physical verifier gives it that signal. It also gives people what they need to trust the result: evidence they can inspect, tied to the exact moment each fault appeared.</p>
      </section>

      <section>
        <h2>Where we are</h2>
        <ul className="plainlist spaced">
          <li><b>In simulation:</b> 119 of 122 attempted tests passed across 16 devices, on an earlier sim model. None of those devices had a broken control.</li>
          <li><b>A planted fault:</b> a jammed button is caught as stuck in the sim. There's only one such fault so far.</li>
          <li><b>Not done yet:</b> the full pipeline on the real arm, the frontier model driving a run, reading the manual, and a real fix-and-retest cycle.</li>
        </ul>
        <a className="btn accent" href="#/projects">See the projects</a>
      </section>
    </div>
  );
}
