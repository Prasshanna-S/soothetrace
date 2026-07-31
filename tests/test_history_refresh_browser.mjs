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

function incident(id, action, startedAt) {
  return {
    id,
    started_at: startedAt,
    actions: [{ action }],
    outcome: { text: `${action} helped`, settled: true },
    context: { tags: ["at home"] },
    audio: { status: "unavailable" },
  };
}

const profiles = [
  { id: 1, display_name: "Baby One", kind: "infant", status: "ready" },
  { id: 2, display_name: "Baby Two", kind: "infant", status: "ready" },
];
const histories = new Map([
  [1, [incident(101, "Older Baby One memory", "2026-07-29T20:00:00-04:00")]],
  [2, [incident(201, "Baby Two memory", "2026-07-30T19:00:00-04:00")]],
]);
const historyRequests = new Map([[1, 0], [2, 0]]);
let delayNextBabyOneHistory = false;
let delayedBabyOneStarted;
let releaseDelayedBabyOne;

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
    if (url.pathname === "/api/profiles" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ profiles }),
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

    const historyMatch = url.pathname.match(/^\/api\/profiles\/(\d+)\/incidents$/);
    if (historyMatch && request.method() === "GET") {
      const profileId = Number(historyMatch[1]);
      historyRequests.set(profileId, (historyRequests.get(profileId) || 0) + 1);
      if (profileId === 1 && delayNextBabyOneHistory) {
        delayNextBabyOneHistory = false;
        if (delayedBabyOneStarted) delayedBabyOneStarted();
        await new Promise((resolve) => { releaseDelayedBabyOne = resolve; });
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profile: profiles.find((profile) => profile.id === profileId),
          incidents: histories.get(profileId) || [],
          next_cursor: null,
        }),
      });
      return;
    }

    if (url.pathname === "/api/care-sessions/77/complete" &&
        request.method() === "POST") {
      histories.get(1).unshift(
        incident(103, "Newest saved memory", "2026-07-30T20:30:00-04:00")
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session: {
            id: 77,
            status: "completed",
            profile: profiles[0],
            last_sequence: 1,
            decision: null,
          },
          incident: { id: 103, detail_url: "/api/profiles/1/incidents/103" },
        }),
      });
      return;
    }

    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://history-refresh.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => document.querySelector("#profile-picker").options.length === 3
  );

  await page.click("#tab-history");
  await page.waitForSelector("#history-list .record-card");
  assert(
    await page.locator("#history-list .record-card").count() === 1,
    "initial History did not render one clean Baby One list"
  );

  await page.click("#tab-listen");
  histories.get(1).unshift(
    incident(102, "Newer Baby One memory", "2026-07-30T20:00:00-04:00")
  );
  await page.click("#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#history-list").textContent.includes("Newer Baby One memory")
  );
  let cards = await page.locator("#history-list .record-card").allTextContents();
  assert(
    cards.length === 2 &&
      cards[0].includes("Newer Baby One memory") &&
      cards[1].includes("Older Baby One memory"),
    `History navigation did not replace with a newest-first clean list: ${JSON.stringify(cards)}`
  );

  await page.click("#tab-listen");
  await page.selectOption("#profile-picker", "2");
  await page.click("#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#history-list").textContent.includes("Baby Two memory")
  );
  cards = await page.locator("#history-list .record-card").allTextContents();
  assert(
    cards.length === 1 &&
      cards[0].includes("Baby Two memory") &&
      !cards[0].includes("Baby One"),
    `inactive profile change leaked the previous baby's History: ${JSON.stringify(cards)}`
  );

  let markDelayedBabyOneStarted;
  const delayedBabyOneRequest = new Promise((resolve) => {
    markDelayedBabyOneStarted = resolve;
  });
  delayedBabyOneStarted = markDelayedBabyOneStarted;
  delayNextBabyOneHistory = true;
  await page.click("#tab-listen");
  await page.selectOption("#profile-picker", "1");
  await page.click("#tab-history");
  await delayedBabyOneRequest;
  await page.click("#tab-listen");
  await page.selectOption("#profile-picker", "2");
  await page.click("#tab-history");
  await new Promise((resolve) => setTimeout(resolve, 50));
  if (releaseDelayedBabyOne) releaseDelayedBabyOne();
  await page.waitForFunction(
    () => document.querySelector("#history-status").textContent !== "Loading recorded moments."
  );
  await new Promise((resolve) => setTimeout(resolve, 50));
  cards = await page.locator("#history-list .record-card").allTextContents();
  assert(
    cards.length === 1 &&
      cards[0].includes("Baby Two memory") &&
      !cards[0].includes("Baby One"),
    `an older Baby One request overwrote selected Baby Two: ${JSON.stringify(cards)}`
  );

  await page.click("#tab-listen");
  await page.selectOption("#profile-picker", "1");
  await page.click("#tab-history");
  await page.waitForFunction(
    () => document.querySelectorAll("#history-list .record-card").length === 2
  );
  await page.click("#tab-listen");

  const requestsBeforeSave = historyRequests.get(1);
  await page.evaluate(() => {
    state.sessionId = 77;
    state.serverSession = {
      id: 77,
      status: "stopped",
      profile: state.selectedProfile,
      last_sequence: 1,
      decision: null,
    };
    setSessionState("awaiting_outcome");
  });
  await page.fill("#outcome-action", "Newest saved memory");
  await page.click('#settled-seg button[data-settled="true"]');
  await page.click("#btn-save-outcome");
  await page.waitForSelector('body[data-session="saved"]');

  await page.click("#btn-saved-done");
  await page.click("#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#history-list").textContent.includes("Newest saved memory")
  );
  cards = await page.locator("#history-list .record-card").allTextContents();
  assert(
    historyRequests.get(1) > requestsBeforeSave,
    "opening History after Save did not request the current server record"
  );
  assert(
    cards.length === 3 &&
      cards[0].includes("Newest saved memory") &&
      cards[1].includes("Newer Baby One memory") &&
      cards[2].includes("Older Baby One memory"),
    `saved History was stale, duplicated, or not newest first: ${JSON.stringify(cards)}`
  );

  const requestsBeforeRepeat = historyRequests.get(1);
  await page.click("#tab-listen");
  await page.click("#tab-history");
  while (historyRequests.get(1) === requestsBeforeRepeat) {
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  await page.waitForFunction(
    () => document.querySelector("#history-status").textContent.startsWith("Showing ") &&
      document.querySelectorAll("#history-list .record-card").length === 3
  );
  cards = await page.locator("#history-list .record-card").allTextContents();
  assert(
    cards.length === 3,
    `repeated History navigation duplicated recorded moments: ${JSON.stringify(cards)}`
  );

  console.log("History refresh browser contract passed");
} finally {
  await browser.close();
}
