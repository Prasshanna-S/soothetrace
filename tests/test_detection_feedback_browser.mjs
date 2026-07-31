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
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://detection-feedback.test/", { waitUntil: "domcontentloaded" });
  const localChecking = await page.evaluate(() => {
    state.session = "listening";
    setSessionState("listening");
    updateActivityFeedback(0.8);
    updateActivityFeedback(0.8);
    const beforeSustained = {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
    updateActivityFeedback(0.8);
    return {
      beforeSustained,
      afterSustained: {
        text: document.querySelector("#analysis-status").textContent,
        orb: document.querySelector("#orb").dataset.visualState,
        suggestionHidden: document.querySelector("#suggestion-block").hidden,
        visibleStatusLines:
          document.querySelectorAll("#analysis-status:not([hidden])").length,
      },
    };
  });
  assert(
    localChecking.beforeSustained.text === "" ||
      localChecking.beforeSustained.text === "Listening",
    `activity was not debounced: ${JSON.stringify(localChecking)}`
  );
  assert(
    localChecking.afterSustained.text === "Checking for infant cry" &&
      localChecking.afterSustained.orb === "checking" &&
      localChecking.afterSustained.suggestionHidden &&
      localChecking.afterSustained.visibleStatusLines === 1,
    `sustained activity did not enter honest checking feedback: ` +
      JSON.stringify(localChecking)
  );
  assert(
    !localChecking.afterSustained.text.toLowerCase().includes("detected"),
    "local energy claimed a cry detection"
  );

  const released = await page.evaluate(() => {
    for (let index = 0; index < 5; index += 1) updateActivityFeedback(0);
    return {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
  });
  assert(
    released.text === "Listening" && released.orb === "listening",
    `quiet input did not release the checking state: ${JSON.stringify(released)}`
  );

  const serverConfirmation = await page.evaluate(() => {
    for (let index = 0; index < 3; index += 1) updateActivityFeedback(0.8);
    renderCryStatus("infant_cry_detected");
    const realNow = Date.now;
    Date.now = () => realNow() + 60_000;
    for (let index = 0; index < 8; index += 1) updateActivityFeedback(0.8);
    const afterActivity = {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
    for (let index = 0; index < 8; index += 1) updateActivityFeedback(0);
    const afterQuiet = {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
    Date.now = realNow;
    return {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
      suggestionHidden: document.querySelector("#suggestion-block").hidden,
      afterActivity,
      afterQuiet,
    };
  });
  assert(
    serverConfirmation.afterActivity.text === "Infant-cry-like sound detected" &&
      serverConfirmation.afterActivity.orb === "detected" &&
      serverConfirmation.afterQuiet.text === "Infant-cry-like sound detected" &&
      serverConfirmation.afterQuiet.orb === "detected" &&
      serverConfirmation.text === "Infant-cry-like sound detected" &&
      serverConfirmation.orb === "detected" &&
      serverConfirmation.suggestionHidden,
    `server confirmation did not remain authoritative: ` +
      JSON.stringify(serverConfirmation)
  );

  const firstPositive = {
    chunk: {
      status: "matched_no_guidance",
      decision_progress: {
        label: "Infant cry detected. Match held. Confirming 1 of 3",
      },
      cry_presence: { status: "infant_cry_detected" },
    },
  };
  const secondPositive = {
    chunk: {
      status: "matched_no_guidance",
      decision_progress: {
        label: "Infant cry detected. Match held. Confirming 2 of 3",
      },
      cry_presence: { status: "infant_cry_detected" },
    },
  };
  const consecutivePositive = await page.evaluate(({ first, second }) => {
    renderChunkResult(first);
    const realNow = Date.now;
    Date.now = () => realNow() + 60_000;
    for (let index = 0; index < 6; index += 1) updateActivityFeedback(0.8);
    const betweenSegments = {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
    Date.now = realNow;
    renderChunkResult(second);
    return {
      betweenSegments,
      afterSecondResult: {
        text: document.querySelector("#analysis-status").textContent,
        orb: document.querySelector("#orb").dataset.visualState,
      },
    };
  }, { first: firstPositive, second: secondPositive });
  assert(
    consecutivePositive.betweenSegments.text ===
      "Infant-cry-like sound detected" &&
      consecutivePositive.betweenSegments.orb === "detected" &&
      consecutivePositive.afterSecondResult.text ===
        "Infant-cry-like sound detected" &&
      consecutivePositive.afterSecondResult.orb === "detected",
    `consecutive server-positive segments flashed local feedback: ` +
      JSON.stringify(consecutivePositive)
  );

  await page.waitForTimeout(950);
  const heldProgress = await page.evaluate(() => {
    const beforeActivity =
      document.querySelector("#analysis-status").textContent;
    const realNow = Date.now;
    Date.now = () => realNow() + 60_000;
    for (let index = 0; index < 6; index += 1) updateActivityFeedback(0.8);
    const afterActivity =
      document.querySelector("#analysis-status").textContent;
    Date.now = realNow;
    return {
      beforeActivity,
      afterActivity,
      orb: document.querySelector("#orb").dataset.visualState,
    };
  });
  assert(
    heldProgress.beforeActivity ===
      "Infant cry detected. Match held. Confirming 2 of 3" &&
      heldProgress.afterActivity ===
        "Infant cry detected. Match held. Confirming 2 of 3" &&
      heldProgress.orb === "detected",
    `server progress did not remain authoritative: ${JSON.stringify(heldProgress)}`
  );

  const explicitNoCry = await page.evaluate(() => {
    renderChunkResult({
      chunk: {
        status: "no_cry_detected",
        cry_presence: { status: "no_cry_detected" },
      },
    });
    const releasedText =
      document.querySelector("#analysis-status").textContent;
    const realNow = Date.now;
    Date.now = () => realNow() + 60_000;
    for (let index = 0; index < 6; index += 1) updateActivityFeedback(0.8);
    Date.now = realNow;
    return {
      releasedText,
      afterLocalActivity:
        document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
  });
  assert(
    explicitNoCry.releasedText ===
      "No infant cry detected in this segment" &&
      explicitNoCry.afterLocalActivity === "Checking for infant cry" &&
      explicitNoCry.orb === "checking",
    `a later no-cry segment did not release confirmed cry: ` +
      JSON.stringify(explicitNoCry)
  );

  const invalidSegment = await page.evaluate(() => {
    renderCryStatus("infant_cry_detected");
    renderChunkResult({
      chunk: {
        status: "invalid",
        reason_codes: ["near_silence"],
      },
    });
    return {
      text: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
    };
  });
  assert(
    invalidSegment.text === "That segment was too quiet. Still listening" &&
      invalidSegment.orb === "listening",
    `invalid audio did not release confirmed cry: ${JSON.stringify(invalidSegment)}`
  );

  const staleProgressPayload = {
    chunk: {
      status: "matched_no_guidance",
      decision_progress: {
        label: "STALE progress must not render",
      },
      cry_presence: { status: "infant_cry_detected" },
    },
  };
  await page.evaluate((payload) => {
    renderChunkResult(payload);
    renderChunkResult({
      chunk: {
        status: "no_cry_detected",
        cry_presence: { status: "no_cry_detected" },
      },
    });
  }, staleProgressPayload);
  await page.waitForTimeout(950);
  const afterStaleTimer = await page.locator("#analysis-status").textContent();
  assert(
    afterStaleTimer === "No infant cry detected in this segment",
    `a delayed progress timer overwrote newer server state: ${afterStaleTimer}`
  );

  console.log("detection feedback browser contract passed");
} finally {
  await browser.close();
}
