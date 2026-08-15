import { chromium } from "playwright";
import { existsSync, readFileSync, writeFileSync, unlinkSync } from "node:fs";
const S = process.argv[2];
const ctx = await chromium.launchPersistentContext(`${S}/goai-profile`, {
  headless: false,
  viewport: { width: 1600, height: 1000 },
  args: ["--window-position=80,50", "--window-size=1640,1080"],
});
const page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://www.goaihz.com/submission", { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
console.log("窗口已打开并保持;等待指令文件…");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
while (!existsSync(`${S}/goai-quit`)) {
  if (existsSync(`${S}/goai-cmd.json`)) {
    let out = { ok: true };
    try {
      const cmd = JSON.parse(readFileSync(`${S}/goai-cmd.json`, "utf-8"));
      unlinkSync(`${S}/goai-cmd.json`);
      if (cmd.action === "goto") await page.goto(cmd.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      if (cmd.action === "dump") {
        await sleep(1500);
        out.text = (await page.evaluate(() => document.body.innerText)).slice(0, 5000);
        out.fields = await page.evaluate(() =>
          [...document.querySelectorAll("input, textarea, select, button, a[href]")].map((el, i) => ({
            i, tag: el.tagName, type: el.type || null, name: el.name || null,
            placeholder: el.placeholder || null, text: (el.innerText || el.value || "").slice(0, 50) || null,
            href: el.href ? el.href.slice(0, 80) : null,
          })).filter((f) => f.text || f.placeholder || f.type === "file").slice(0, 120)
        );
      }
      if (cmd.action === "click") await page.click(cmd.selector, { timeout: 8000 });
      if (cmd.action === "clicktext") await page.getByText(cmd.text, { exact: cmd.exact ?? false }).first().click({ timeout: 8000 });
      if (cmd.action === "fill") await page.fill(cmd.selector, cmd.value, { timeout: 8000 });
      if (cmd.action === "type") { await page.click(cmd.selector); await page.keyboard.type(cmd.value); }
      if (cmd.action === "upload") await page.setInputFiles(cmd.selector, cmd.file, { timeout: 20000 });
      if (cmd.action === "eval") out.result = await page.evaluate(cmd.js);
      await sleep(800);
      await page.screenshot({ path: `${S}/goai-shot.png` });
    } catch (e) { out = { ok: false, error: String(e).slice(0, 300) }; try { await page.screenshot({ path: `${S}/goai-shot.png` }); } catch {} }
    writeFileSync(`${S}/goai-result.json`, JSON.stringify(out));
  }
  await sleep(1500);
}
await ctx.close();
console.log("quit");
