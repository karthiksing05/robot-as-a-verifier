import "@fontsource/source-serif-4/400.css";
import "@fontsource/source-serif-4/400-italic.css";
import "@fontsource/source-serif-4/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/michroma/400.css";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/motion.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Reveal once the type is ready, so text never reflows in front of the viewer. Bundled fonts rarely take this long.
const reveal = () => document.documentElement.classList.add("ready");
Promise.race([
  Promise.all([document.fonts.load('400 16px "Source Serif 4"'), document.fonts.load('400 13px "JetBrains Mono"')]),
  new Promise((resolve) => setTimeout(resolve, 450)),
]).then(reveal, reveal);
