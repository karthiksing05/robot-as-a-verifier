import { useEffect, useRef, useState } from "react";
import { NAV, isCurrent, type Screen } from "../lib/nav";
import { withTransition } from "../lib/route";
import { ENVIRONMENTS, OPERATORS, canEnter, signOut, switchOperator, type Session } from "../lib/session";

/** The gear at the top right: the pages that explain the project, and the workspace settings, kept out of the top bar. */
export function SettingsMenu({ session, section, theme, onTheme }: { session: Session; section: Screen; theme: string; onTheme: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const here = NAV.some(([, screen, , where]) => where === "more" && isCurrent(screen, section));

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    const away = () => setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    addEventListener("hashchange", away);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
      removeEventListener("hashchange", away);
    };
  }, [open]);

  return (
    <div className="settings" ref={box}>
      <button ref={button} type="button" className={`gear ${here ? "here" : ""}`} aria-label="Settings and more pages" aria-expanded={open} aria-controls="settings-panel" onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8Zm8.2 4.7-1.7 1 .1 2-1.9 1.9-2-.1-1 1.7h-2.6l-1-1.7-2 .1-1.9-1.9.1-2-1.7-1v-2.6l1.7-1-.1-2 1.9-1.9 2 .1 1-1.7h2.6l1 1.7 2-.1 1.9 1.9-.1 2 1.7 1Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div className="settingspanel rise" id="settings-panel" role="dialog" aria-label="Settings and more pages">
          <nav aria-label="More pages">
            {NAV.filter(([, , , where]) => where === "more").map(([path, screen, label]) => (
              <a key={path} href={`#/${path}`} aria-current={isCurrent(screen, section) ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
          <div className="settingsrows">
            <div className="settingsrow"><span className="label">Environment</span><span className="envchip">{ENVIRONMENTS[session.env].label}</span></div>
            <div className="settingsrow">
              <label className="label" htmlFor="pick-op">Acting as</label>
              <select id="pick-op" className="compact" value={session.operator.name} onChange={(e) => switchOperator(e.target.value)}>
                {OPERATORS.filter((o) => canEnter(o, session.env)).map((o) => <option key={o.name} value={o.name}>{o.name}{o.role === "judge" ? " (steer only)" : ""}</option>)}
              </select>
            </div>
            <div className="settingsrow"><span className="label">Theme</span><button className="linkbtn" type="button" onClick={onTheme}>{theme === "dark" ? "Light" : "Dark"}</button></div>
          </div>
          <button className="linkbtn settingsexit" type="button" onClick={() => withTransition(signOut)}>Exit</button>
        </div>
      )}
    </div>
  );
}
