import { chromium } from "playwright";
const SCRATCH = process.argv[2];
const ctx = await chromium.launchPersistentContext(`${SCRATCH}/goai-profile`, {
  headless: false,
  viewport: { width: 1600, height: 1000 },
  args: ["--window-position=100,60", "--window-size=1640,1080"],
});
const page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://www.goaihz.com/submission", { waitUntil: "domcontentloaded", timeout: 60000 });
console.log("窗口已打开,等待登录…(最长 10 分钟)");
// 轮询:登录完成的标志 = 页面不再出现「登录 GOAI」弹层且出现提交相关内容
await page.waitForFunction(
  () => {
    const t = document.body.innerText;
    return !/登录 GOAI/.test(t) && !/立即报名/.test(t) === false ? /作品提交/.test(t) && !/没有账号/.test(t) : false;
  },
  null, { timeout: 600000, polling: 2000 }
).catch(() => console.log("等待超时"));
await page.waitForTimeout(2000);
const text = await page.evaluate(() => document.body.innerText);
const fields = await page.evaluate(() =>
  [...document.querySelectorAll("input, textarea, select, button, [role=button]")].map((el) => ({
    tag: el.tagName, type: el.type || null, name: el.name || null, id: el.id || null,
    placeholder: el.placeholder || null, text: (el.innerText || "").slice(0, 40) || null,
    accept: el.accept || null,
  })).filter((f) => f.text || f.name || f.placeholder || f.type === "file")
);
console.log("=== PAGE TEXT ===");
console.log(text.slice(0, 3000));
console.log("=== FIELDS ===");
console.log(JSON.stringify(fields, null, 1).slice(0, 3000));
await page.screenshot({ path: `${SCRATCH}/goai-after-login.png` });
await ctx.close();
