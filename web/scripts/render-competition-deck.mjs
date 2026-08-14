#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const source = resolve(process.argv[2] ?? join(root, "docs/competition/AgentRig-GOAI-2026-初赛方案.pptx"));
const output = resolve(process.argv[3] ?? join(root, "docs/competition/AgentRig-GOAI-2026-初赛方案.pdf"));

if (!existsSync(source)) {
  throw new Error(`PPTX not found: ${source}`);
}

function findPreview(directory) {
  for (const name of readdirSync(directory)) {
    const candidate = join(directory, name);
    if (statSync(candidate).isDirectory()) {
      const nested = findPreview(candidate);
      if (nested) return nested;
    } else if (name === "Preview.html") {
      return candidate;
    }
  }
  return undefined;
}

const scratch = mkdtempSync(join(tmpdir(), "agentrig-deck-render-"));
let browser;
try {
  // Quick Look performs the native PowerPoint layout. Chromium then prints the
  // generated HTML at the deck's exact 16:9 page size instead of Letter/A4.
  execFileSync("/usr/bin/qlmanage", ["-p", "-o", scratch, source], {
    stdio: "ignore",
  });
  const preview = findPreview(scratch);
  if (!preview) throw new Error("Quick Look did not produce Preview.html");

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto(pathToFileURL(preview).href, { waitUntil: "load" });
  // Quick Look emits 959×540 slides. Chromium otherwise preserves its default
  // 96-DPI interpretation while printing to a 13.333×7.5-inch page, leaving a
  // 25% blank margin. Stretch each slide to the print page's CSS-pixel extent.
  await page.addStyleTag({
    content: `
      @page { size: 13.333in 7.5in; margin: 0; }
      html, body { margin: 0 !important; padding: 0 !important; }
      div.slide {
        width: 959px !important;
        height: 540px !important;
        transform: scale(1.33469, 1.333333);
        transform-origin: top left;
        margin: 0 !important;
        page-break-after: always;
      }
      div.slide:last-of-type { page-break-after: auto; }
    `,
  });
  await page.pdf({
    path: output,
    width: "13.333in",
    height: "7.5in",
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
    printBackground: true,
    preferCSSPageSize: false,
  });
  process.stdout.write(`${output}\n`);
} finally {
  if (browser) await browser.close();
  rmSync(scratch, { recursive: true, force: true });
}
