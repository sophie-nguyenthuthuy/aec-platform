// Plays through every sidebar tab of the AEC platform demo and records
// the session as WebM. Convert to MP4 after via:
//
//   ffmpeg -i <input>.webm -c:v libx264 -preset slow -crf 22 \
//          -pix_fmt yuv420p -movflags +faststart <output>.mp4
//
// The ffmpeg conversion is in the runner script (record-and-convert.sh)
// — this script only handles the browser walkthrough.

import { existsSync, mkdirSync, readdirSync, renameSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const HTML_PATH = path.resolve(__dirname, "aec-platform-demo.html");
const OUT_DIR = path.resolve(__dirname, "recordings");

// `demo/` is a stand-alone folder with no `node_modules`. Resolve
// `@playwright/test` via its actual install path under `apps/web/`.
const playwrightEntry = path.resolve(
  __dirname,
  "..",
  "apps",
  "web",
  "node_modules",
  "@playwright",
  "test",
  "index.mjs",
);
const { chromium } = await import(pathToFileURL(playwrightEntry).href);

if (!existsSync(HTML_PATH)) {
  console.error("Demo HTML not found:", HTML_PATH);
  process.exit(1);
}
mkdirSync(OUT_DIR, { recursive: true });

// Order matches the sidebar's visual top-to-bottom — gives the recording
// a natural flow across project phase (overview → design → bidding →
// construction → handover → settings).
const TABS = [
  "inbox", "pulse", "activity",
  "codeguard", "drawbridge",
  "bidradar", "winwork", "costpulse",
  "siteeye", "schedule", "submittals", "dailylog", "changeorder",
  "handover", "punchlist",
  "members", "notifications",
];

// 1500ms per tab as requested. The first tab gets a 2.5s preamble so the
// viewer can register the layout before things start moving.
const PER_TAB_MS = 1500;
const FIRST_TAB_PREAMBLE_MS = 2500;
const FINAL_TAIL_MS = 1500;

const VIEWPORT = { width: 1440, height: 900 };

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: VIEWPORT,
  recordVideo: { dir: OUT_DIR, size: VIEWPORT },
  deviceScaleFactor: 1,
});
const page = await context.newPage();

await page.goto(`file://${HTML_PATH}`, { waitUntil: "load" });
// Give web fonts + Tabler icon font a moment to settle so the first
// frame isn't a flash-of-unstyled-text.
await page.waitForTimeout(800);

for (let i = 0; i < TABS.length; i++) {
  const tab = TABS[i];
  const selector = `.nav-item[data-view="${tab}"]`;

  // The first tab ("inbox") is already active when the page loads, so we
  // skip the click on iteration 0 and just hold the camera on it. After
  // that, every iteration clicks and waits.
  if (i === 0) {
    await page.waitForTimeout(FIRST_TAB_PREAMBLE_MS);
    continue;
  }

  // Scroll the sidebar so the target item is in view (it's a long list
  // and items below "schedule" may be below the fold).
  await page.locator(selector).scrollIntoViewIfNeeded();
  // Brief pause after scroll so the click visibly lands on the item.
  await page.waitForTimeout(120);
  await page.click(selector);
  await page.waitForTimeout(PER_TAB_MS);
}

// Hold on the last view briefly so the video doesn't cut mid-thought.
await page.waitForTimeout(FINAL_TAIL_MS);

await context.close();
await browser.close();

// Playwright names the file <random>.webm. Rename to walkthrough.webm
// so the converter script can find it predictably.
const produced = readdirSync(OUT_DIR).filter((f) => f.endsWith(".webm"));
if (produced.length === 0) {
  console.error("No webm produced");
  process.exit(2);
}
// Most recently produced one (mtime) — handles repeat runs.
const latest = produced
  .map((f) => ({ f, t: existsSync(path.join(OUT_DIR, f)) ? Date.now() : 0 }))
  .sort((a, b) => b.t - a.t)[0].f;
const target = path.join(OUT_DIR, "walkthrough.webm");
if (existsSync(target)) {
  const stamped = path.join(OUT_DIR, `walkthrough-${Date.now()}.webm`);
  renameSync(target, stamped);
}
renameSync(path.join(OUT_DIR, latest), target);

console.log("WEBM_PATH=" + target);
