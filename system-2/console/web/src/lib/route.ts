// Hash routes, so the app needs no server rewrites. Every route change goes through a view transition.
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

export interface Route {
  parts: string[];
  query: URLSearchParams;
}

function parse(): Route {
  const [path, search] = location.hash.replace(/^#\/?/, "").split("?");
  return { parts: path ? path.split("/") : [], query: new URLSearchParams(search ?? "") };
}

export function withTransition(update: () => void) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!document.startViewTransition || reduced) {
    update();
    return;
  }
  const transition = document.startViewTransition(() => flushSync(update));
  // A newer navigation can interrupt this one. The update still runs, so that isn't an error.
  transition.ready.catch(() => {});
  transition.finished.catch(() => {});
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const onChange = () => withTransition(() => setRoute(parse()));
    addEventListener("hashchange", onChange);
    return () => removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const go = (path: string) => {
  location.hash = `#/${path}`;
};
