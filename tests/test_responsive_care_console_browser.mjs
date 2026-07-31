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

const profile = {
  id: 21,
  display_name: "Demo Baby",
  kind: "infant",
  status: "ready",
  enrollments: 3,
};

const incidents = [
  {
    id: 301,
    started_at: "2026-07-30T20:16:00-04:00",
    duration_s: 12,
    actions: [{ action: "Offered bottle" }],
    outcome: "The baby settled.",
    outcome_source: "caregiver",
    worked: true,
    context: { tags: ["evening"] },
  },
  {
    id: 302,
    started_at: "2026-07-29T03:04:00-04:00",
    duration_s: 9,
    actions: [{ action: "Held baby upright" }],
    outcome: "Whether the baby settled was not recorded.",
    outcome_source: "seed",
    worked: null,
    context: { tags: ["overnight"] },
  },
];

const assets = {
  "/": ["text/html", "index.html"],
  "/app.css": ["text/css", "app.css"],
  "/app.js": ["text/javascript", "app.js"],
  "/manifest.webmanifest": ["application/manifest+json", "manifest.webmanifest"],
};

async function dispatchSwipe(page, selector, startX, endX, y) {
  await page.locator(selector).evaluate((node, points) => {
    const common = {
      bubbles: true,
      cancelable: true,
      pointerId: 7,
      pointerType: "touch",
      isPrimary: true,
      clientY: points.y,
    };
    node.dispatchEvent(new PointerEvent("pointerdown", {
      ...common,
      clientX: points.startX,
      buttons: 1,
    }));
    node.dispatchEvent(new PointerEvent("pointerup", {
      ...common,
      clientX: points.endX,
      buttons: 0,
    }));
  }, { startX, endX, y });
}

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    reducedMotion: "no-preference",
  });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message || String(error)));

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
      const local = path.join(repoRoot, "web", url.pathname);
      if (fs.existsSync(local)) {
        await route.fulfill({ status: 200, body: fs.readFileSync(local) });
      } else {
        await route.fulfill({ status: 404, body: "" });
      }
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
        body: JSON.stringify({ profiles: [profile] }),
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
    if (url.pathname === "/api/profiles/21/incidents" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ profile, incidents, next_cursor: null }),
      });
      return;
    }
    if (url.pathname === "/api/profiles/21/incidents/301" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...incidents[0],
          transcript: "I have the bottle ready.",
          speech: { segments: [] },
        }),
      });
      return;
    }
    if (url.pathname === "/api/profiles/21" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          profile: {
            ...profile,
            memory_count: 2,
            available_context: ["acoustic_pattern", "time_of_day"],
          },
          training_clips: [],
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://responsive-care.test/", { waitUntil: "domcontentloaded" });
  assert(
    await page.locator("#launch-screen").count() === 1,
    "fresh app load has no SootheTrace launch screen"
  );
  await page.waitForFunction(() =>
    document.body.dataset.launched === "true" &&
    document.querySelector("#launch-screen")?.hidden
  );
  await page.waitForFunction(() =>
    document.querySelector("#profile-picker")?.value === "21" &&
    document.querySelector("#health-text")?.textContent === "Ready"
  );

  const portrait = await page.evaluate(() => {
    const rect = (selector) => {
      const value = document.querySelector(selector).getBoundingClientRect();
      return {
        left: value.left,
        right: value.right,
        top: value.top,
        bottom: value.bottom,
        width: value.width,
      };
    };
    const stickerStyles = Array.from(document.querySelectorAll(".ambient-sticker"))
      .map((node) => {
        const style = getComputedStyle(node);
        return {
          opacity: Number(style.opacity),
          animationName: style.animationName,
          animationDuration: style.animationDuration,
        };
      });
    return {
      header: rect("#page-listen > .page-head"),
      profile: rect("#profile-control"),
      health: rect("#health-pill"),
      stickerStyles,
    };
  });
  assert(
    Math.abs(portrait.profile.left - portrait.header.left) <= 1 &&
      Math.abs(portrait.profile.right - portrait.header.right) <= 1,
    `portrait profile is not full width: ${JSON.stringify(portrait)}`
  );
  assert(
    portrait.health.top >= portrait.profile.bottom + 6,
    `Ready is not below the profile: ${JSON.stringify(portrait)}`
  );
  assert(
    portrait.stickerStyles.length === 4 &&
      portrait.stickerStyles.every((item) =>
        item.opacity <= 0.1 && item.animationName !== "none"
      ) &&
      new Set(portrait.stickerStyles.map((item) => item.animationDuration)).size > 1,
    `ambient stickers are not quiet and independently moving: ${JSON.stringify(portrait)}`
  );

  await page.evaluate(() => {
    state.session = "listening";
    setSessionState("listening");
  });
  const recording = await page.evaluate(() => {
    const profileRect = document.querySelector("#profile-control").getBoundingClientRect();
    const timerRect = document.querySelector("#rec-chip").getBoundingClientRect();
    const orbRect = document.querySelector("#orb-wrap").getBoundingClientRect();
    return {
      profileBottom: profileRect.bottom,
      timerTop: timerRect.top,
      timerBottom: timerRect.bottom,
      orbTop: orbRect.top,
      ambientHidden: getComputedStyle(document.querySelector("#ambient")).visibility,
    };
  });
  assert(
    recording.timerTop >= recording.profileBottom + 6 &&
      recording.orbTop >= recording.timerBottom + 4 &&
      recording.ambientHidden === "hidden",
    `recording state overlaps the profile or orb: ${JSON.stringify(recording)}`
  );
  await page.evaluate(() => {
    state.session = "idle";
    setSessionState("idle");
  });

  await dispatchSwipe(page, "#orb-stage", 330, 55, 410);
  await page.waitForFunction(() => location.hash === "#history");
  assert(
    await page.locator("#tab-history").getAttribute("aria-current") === "page",
    "left swipe did not select History"
  );
  await dispatchSwipe(page, "#history-status", 55, 330, 120);
  await page.waitForFunction(() => location.hash === "#listen");
  assert(
    await page.locator("#tab-listen").getAttribute("aria-current") === "page",
    "right swipe did not return to Listen"
  );

  await page.setViewportSize({ width: 844, height: 390 });
  await page.evaluate(() => { location.hash = "history"; });
  await page.waitForFunction(() =>
    document.querySelectorAll("#history-list .record-card").length === 2
  );
  const history = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll("#history-list .record-card"))
      .map((node) => node.getBoundingClientRect())
      .map((rect) => ({
        left: rect.left,
        right: rect.right,
        width: rect.width,
        height: rect.height,
      }));
    return {
      cards,
      dayHeadings: document.querySelectorAll("#history-list .hist-day").length,
      settledWords: document.querySelectorAll("#history-list .settle-word").length,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: innerHeight,
    };
  });
  assert(
    history.dayHeadings === 2 && history.settledWords === 2,
    `History is missing day groups or outcome words: ${JSON.stringify(history)}`
  );
  assert(
    history.cards.every((card) => card.width >= 700 && card.height >= 72) &&
      Math.abs(history.cards[0].left - history.cards[1].left) <= 1 &&
      history.scrollHeight <= history.viewportHeight + 1,
    `short landscape History is cramped or page-scrolling: ${JSON.stringify(history)}`
  );

  await page.locator("#history-list .record-open").first().click();
  await page.waitForFunction(() => !document.querySelector("#history-detail").hidden);
  const detail = await page.evaluate(() => {
    const rect = document.querySelector("#history-detail").getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
      width: rect.width,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: innerHeight,
    };
  });
  assert(
    detail.left >= 20 && detail.right <= 824 && detail.width >= 780 &&
      detail.top >= 12 && detail.bottom <= detail.viewportHeight &&
      detail.scrollHeight <= detail.viewportHeight + 1,
    `History detail does not own the short landscape canvas: ${JSON.stringify(detail)}`
  );
  await dispatchSwipe(page, "#history-detail-tabs", 700, 120, 90);
  assert(
    await page.evaluate(() => location.hash) === "#history",
    "swiping the History tabs incorrectly changed the app section"
  );

  assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`);
  console.log("responsive care console browser acceptance passed");
} finally {
  await browser.close();
}
