import { Field } from "../components/Field";
import { Pill, stagger } from "../components/ui";
import { useAppSession, useRuns } from "../lib/context";
import { ENVIRONMENTS } from "../lib/session";
import { go } from "../lib/route";

export function Runs() {
  const { env } = useAppSession();
  const { runs } = useRuns(env);

  if (!ENVIRONMENTS[env].connected) {
    return (
      <div className="page">
        <h1 className="title">Runs</h1>
        <div className="empty rise">
          <h2>Real arm and real CAD: not connected yet</h2>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <section className="hero rise">
        <Field baseX={0.82} reach={0.5} />
        <h1 className="title">All runs</h1>
        <div className="row"><a className="btn accent" href="#/projects">Projects</a></div>
      </section>
      <div>
        <div className="panel rise" style={stagger(1)}>
          <div className="scrollx">
            <table>
              <thead><tr><th>Run</th><th>Device</th><th>Result</th><th>Passed</th><th>Reward</th></tr></thead>
              <tbody>
                {runs.map((r) => {
                  const failed = r.report.coverage.failed.length;
                  return (
                    <tr key={r.id} className="link" tabIndex={0} onClick={() => go(`run/${r.id}`)} onKeyDown={(e) => { if (e.key === "Enter") go(`run/${r.id}`); }}>
                      <td className="n">{r.id}{r.recording ? " ▶" : ""}</td>
                      <td>{r.product}</td>
                      <td><Pill status={r.status !== "completed" ? "skipped" : failed ? "failed" : "passed"}>{r.status !== "completed" ? r.status : failed ? "Bugs found" : "All passed"}</Pill></td>
                      <td className="n">{r.report.coverage.passed.length} of {r.report.coverage.detected}</td>
                      <td className="n">{r.report.reward.value.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="note">▶ MuJoCo recording. Others: mock data.</p>
        </div>
      </div>
    </div>
  );
}
