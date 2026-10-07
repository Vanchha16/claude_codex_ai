// Project-local asset step for the dashboard (run by `npm run build` / `gold.cmd build-ui`).
// 1) renders app/static/index.html from src/index.template.html with pinned TailAdmin icons and table headers,
// 2) copies Alpine.js, Lightweight Charts and the Inter Tight / Outfit fonts into app/static/dist, 3) writes the third-party notices.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.resolve(here, "../app/static");
const dist = path.join(staticDir, "dist");
mkdirSync(path.join(dist, "fonts"), { recursive: true });

const icons = JSON.parse(readFileSync(path.join(here, "src/tailadmin/icons.json"), "utf8"));
const th = (labels) => labels.split("|").map((label) =>
  `<th scope="col">${label}</th>`).join("");

let html = readFileSync(path.join(here, "src/index.template.html"), "utf8");
html = html.replace(/\{\{ICON:(\w+)\}\}/g, (_, key) => {
  if (!icons[key]) throw new Error(`unknown TailAdmin icon ${key}`);
  return icons[key].replace("<svg", '<svg aria-hidden="true"');
});
html = html.replace(/\{\{TH:([^}]+)\}\}/g, (_, labels) => th(labels));
if (/\{\{/.test(html)) throw new Error("unresolved template placeholder");
writeFileSync(path.join(staticDir, "index.html"), html);

const nm = path.join(here, "node_modules");
copyFileSync(path.join(nm, "alpinejs/dist/cdn.min.js"), path.join(dist, "alpine.min.js"));
copyFileSync(path.join(nm, "lightweight-charts/dist/lightweight-charts.standalone.production.js"),
  path.join(dist, "lightweight-charts.standalone.production.js"));
copyFileSync(path.join(nm, "lightweight-charts/LICENSE"), path.join(dist, "LICENSE-lightweight-charts.txt"));
copyFileSync(path.join(nm, "@fontsource-variable/outfit/files/outfit-latin-wght-normal.woff2"),
  path.join(dist, "fonts/outfit-latin-wght-normal.woff2"));
copyFileSync(path.join(nm, "@fontsource-variable/inter-tight/files/inter-tight-latin-wght-normal.woff2"),
  path.join(dist, "fonts/inter-tight-latin-wght-normal.woff2"));

const version = (pkg) => JSON.parse(readFileSync(path.join(nm, pkg, "package.json"), "utf8")).version;
const notices = [
  "Third-party components bundled in app/static (dashboard UI)",
  "==============================================================",
  "",
  "TailAdmin free - Tailwind CSS admin dashboard template (HTML edition)",
  "  https://github.com/TailAdmin/tailadmin-free-tailwind-dashboard-template",
  "  Upstream commit 1bd2dc42a8467ae0281cf00bd0050da4c9c4be07 (package version 2.4.0, 2026-09-15)",
  "  Used: design tokens and utilities (src/css/style.css, lightly modified), sidebar/menu-item, header,",
  "  hamburger + overlay drawer, dark-mode toggler, metric cards, table card, badges, alerts, form controls, icons.",
  "",
  readFileSync(path.join(here, "src/tailadmin/LICENSE"), "utf8").trim(),
  "",
  "--------------------------------------------------------------",
  `Alpine.js ${version("alpinejs")} - https://alpinejs.dev - MIT License, Copyright (c) 2019-present Caleb Porzio and contributors`,
  `Tailwind CSS ${version("tailwindcss")} (generated CSS) - https://tailwindcss.com - MIT License, Copyright (c) Tailwind Labs, Inc.`,
  `@tailwindcss/forms ${version("@tailwindcss/forms")} - MIT License, Copyright (c) Tailwind Labs, Inc.`,
  "",
  "--------------------------------------------------------------",
  `TradingView Lightweight Charts ${version("lightweight-charts")} - https://github.com/tradingview/lightweight-charts`,
  "  Licensed under the Apache License, Version 2.0 (full text: /static/dist/LICENSE-lightweight-charts.txt). Bundled unmodified:",
  "  lightweight-charts.standalone.production.js. Attribution NOTICE (from the upstream NOTICE file):",
  "",
  "TradingView Lightweight Charts™",
  "Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/",
  "",
  "  The chart also shows TradingView's attribution logo and the page links to https://www.tradingview.com/.",
  "  Data shown in the chart comes from the user's own MetaTrader 5 terminal (or VC Signal's fictional demo fixture),",
  "  not from TradingView.",
  "",
  "--------------------------------------------------------------",
  `Outfit variable font (@fontsource-variable/outfit ${version("@fontsource-variable/outfit")})`,
  readFileSync(path.join(nm, "@fontsource-variable/outfit/LICENSE"), "utf8").trim(),
  "",
  "--------------------------------------------------------------",
  `Inter Tight variable font (@fontsource-variable/inter-tight ${version("@fontsource-variable/inter-tight")}), primary UI font`,
  readFileSync(path.join(nm, "@fontsource-variable/inter-tight/LICENSE"), "utf8").trim(),
  "",
];
writeFileSync(path.join(dist, "THIRD_PARTY_NOTICES.txt"), notices.join("\n"));
console.log("dashboard assets written to app/static (index.html) and app/static/dist");
