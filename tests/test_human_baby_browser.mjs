import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const testDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.dirname(testDir);

function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE_PATH,
    "playwright",
    path.join(repoRoot, "node_modules", "playwright"),
    path.join(os.homedir(), "web-design-repository", "node_modules", "playwright"),
    "/opt/homebrew/lib/node_modules/@playwright/mcp/node_modules/playwright",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      if (error && error.code !== "MODULE_NOT_FOUND") throw error;
    }
  }
  throw new Error("Playwright is required. Set PLAYWRIGHT_MODULE_PATH if needed.");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const assets = {
  "/": ["text/html", "index.html"],
  "/app.css": ["text/css", "app.css"],
  "/app.js": ["text/javascript", "app.js"],
  "/manifest.webmanifest": ["application/manifest+json", "manifest.webmanifest"],
};

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    reducedMotion: "reduce",
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (assets[url.pathname]) {
      const [contentType, name] = assets[url.pathname];
      await route.fulfill({
        status: 200,
        contentType,
        body: fs.readFileSync(path.join(repoRoot, "web", name)),
      });
      return;
    }
    if (url.pathname.startsWith("/img/")) {
      await route.fulfill({ status: 404, body: "" });
      return;
    }
    if (url.pathname === "/api/health") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ready", care: { ready: true } }),
      });
      return;
    }
    if (url.pathname === "/api/profiles") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profiles: [
            { id: 1, display_name: "Demo Baby", kind: "infant", status: "ready" },
            { id: 2, display_name: "Regular Baby", kind: "infant", status: "learning" },
          ],
        }),
      });
      return;
    }
    if (url.pathname === "/api/visitor-session" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ visitor_session: { consented: true } }),
      });
      return;
    }
    if (url.pathname === "/api/live-sessions" && request.method() === "POST") {
      assert(
        request.postDataJSON().kind === "human_baby",
        "Human Baby did not request the API alias"
      );
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session: { id: 77, kind: "human_imitation", participants: [], observations: [] },
        }),
      });
      return;
    }
    if (url.pathname === "/api/live-sessions/77/observations") {
      const participant = {
        id: 9,
        profile_id: 12,
        display_name: "Person A",
        state: "provisional",
        support_count: 1,
      };
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session: {
            id: 77,
            kind: "human_imitation",
            participants: [participant],
            observations: [{
              id: 1,
              source_type: "upload",
              created_at: "2026-07-30T20:15:00-04:00",
              status: "provisional_created",
              participant,
              closest_participant: null,
            }],
          },
          classification: {
            status: "provisional_created",
            participant,
            reinforced: false,
            reason_codes: ["first_participant"],
          },
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://human-baby.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => document.querySelector("#profile-picker").options.length === 3
  );
  const options = await page.locator("#profile-picker option").allTextContents();
  assert(
    JSON.stringify(options) ===
      JSON.stringify(["Demo Baby (ready)", "Regular Baby (learning)", "Human Baby"]),
    `Human Baby was not the third profile: ${JSON.stringify(options)}`
  );
  assert(await page.locator("#tab-human").isHidden(), "Human Baby remained a fourth tab");

  await page.selectOption("#profile-picker", "human-baby");
  await page.waitForSelector("#page-human:not([hidden])");
  await page.waitForSelector("#human-workspace .training-card");
  const humanCardStyles = await page.locator("#human-workspace .training-card")
    .evaluateAll((cards) => cards.map((card) => {
      const style = getComputedStyle(card);
      return {
        borderTopWidth: style.borderTopWidth,
        borderRadius: style.borderRadius,
        backgroundColor: style.backgroundColor,
        boxShadow: style.boxShadow,
      };
    }));
  assert(
    humanCardStyles.length === 2 &&
      humanCardStyles.every((style) =>
        style.borderTopWidth === "1px" &&
        style.borderRadius === "18px" &&
        style.backgroundColor === "rgba(255, 255, 255, 0.72)" &&
        style.boxShadow.includes("6px 18px")
      ),
    `record-page card styling leaked into Human Baby: ${JSON.stringify(humanCardStyles)}`
  );
  await page.click("#btn-new-human-session");
  await page.waitForFunction(() => !document.querySelector("#human-file").disabled);
  await page.setInputFiles("#human-file", {
    name: "cry.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("test clip"),
  });
  await page.waitForFunction(
    () => document.querySelector("#human-result").textContent.includes("Person A")
  );
  assert(
    (await page.locator("#human-result").textContent()).includes("Participant: Person A"),
    "classification did not render the server display_name"
  );
  assert(
    (await page.locator("#human-participants").textContent()).includes("Person A · 1 clips"),
    "participant bubble did not render the server display_name"
  );
  assert(
    (await page.locator("#human-timeline").textContent()).includes("Person A"),
    "processed clip timeline did not render its assigned participant"
  );
  console.log("Human Baby browser contract passed");
} finally {
  await browser.close();
}
