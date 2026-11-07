import { useRef, useState, type MouseEvent } from "react";
import { Field, type Grabber } from "../components/Field";
import { ENVIRONMENTS, enter, type EnvName } from "../lib/session";

const ZOOM_MS = 620;

export function Login() {
  const [env, setEnv] = useState<EnvName>("demo");
  const [zoom, setZoom] = useState<string | null>(null);
  const [held, setHeld] = useState(false);
  const busy = useRef(false);
  const grabber = useRef<Grabber | null>(null);

  // The arm grabs the button, then everything scales up around it and the app arrives.
  const go = (e: MouseEvent<HTMLButtonElement>) => {
    if (busy.current) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !grabber.current) return enter(env);
    busy.current = true;
    const button = e.currentTarget;
    grabber.current(button, {
      closed: () => setHeld(true),
      done: () => {
        const box = button.getBoundingClientRect();
        setZoom(`${box.left + box.width / 2}px ${box.top + box.height / 2}px`);
        document.documentElement.dataset.entering = "";
        window.setTimeout(() => enter(env), ZOOM_MS - 60);
        window.setTimeout(() => delete document.documentElement.dataset.entering, ZOOM_MS + 520);
      },
    });
  };

  return (
    <div className={`login screen ${zoom ? "zoom" : ""}`} style={zoom ? { transformOrigin: zoom } : undefined}>
      <Field grabber={grabber} />
      <div className="gobox rise">
        <div className="wordmark">RAAV CONSOLE</div>
        <div className="envpick" role="radiogroup" aria-label="Environment">
          {Object.values(ENVIRONMENTS).map((x) => (
            <button key={x.name} type="button" role="radio" aria-checked={env === x.name} onClick={() => setEnv(x.name)}>
              <b>{x.label}</b><span>{x.detail}</span>
            </button>
          ))}
        </div>
        <button className={`gobtn ${held ? "held" : ""}`} type="button" onClick={go}>GO</button>
      </div>
    </div>
  );
}
