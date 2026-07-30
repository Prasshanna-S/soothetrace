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
    path.join(
      os.homedir(),
      "web-design-repository",
      "node_modules",
      "playwright"
    ),
    "/opt/homebrew/lib/node_modules/@playwright/mcp/node_modules/playwright",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      if (error && error.code !== "MODULE_NOT_FOUND") throw error;
    }
  }
  throw new Error(
    "Playwright is required. Install it locally or set PLAYWRIGHT_MODULE_PATH."
  );
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function participant(state, supportCount) {
  return {
    id: 31,
    profile_id: 41,
    display_name: "Person A",
    state,
    support_count: supportCount,
    created_at: "2026-07-30T00:00:00+00:00",
    established_at:
      state === "established" ? "2026-07-30T00:01:00+00:00" : null,
  };
}

function observation(sequence, status, currentParticipant) {
  return {
    id: 50 + sequence,
    sequence,
    created_at: `2026-07-30T00:0${sequence}:00+00:00`,
    source_type: "upload",
    status,
    participant_id: currentParticipant.id,
    closest_participant_id: currentParticipant.id,
    participant: currentParticipant,
    closest_participant: currentParticipant,
    reinforced: status === "participant",
    reason_codes:
      status === "participant" ? ["participant_reinforced"] : ["new_participant"],
    playback_url: `/api/audio/live-observations/${50 + sequence}`,
  };
}

function liveResponse(observationCount) {
  const established = observationCount >= 2;
  const currentParticipant = participant(
    established ? "established" : "provisional",
    observationCount
  );
  const observations = [];
  for (let sequence = 1; sequence <= observationCount; sequence += 1) {
    observations.push(
      observation(
        sequence,
        sequence === 1 ? "provisional_created" : "participant",
        currentParticipant
      )
    );
  }
  return {
    session: {
      id: 77,
      kind: "human_imitation",
      status: "open",
      created_at: "2026-07-30T00:00:00+00:00",
      completed_at: null,
      participants: [currentParticipant],
      observations,
    },
    observation: observations.at(-1),
    classification: {
      status: established ? "participant" : "provisional_created",
      participant: currentParticipant,
      reinforced: established,
      reason_codes: [
        established ? "participant_reinforced" : "new_participant",
      ],
    },
  };
}

async function installRoutes(page, requests) {
  const assets = {
    "/": ["text/html", fs.readFileSync(path.join(repoRoot, "web", "index.html"))],
    "/app.css": [
      "text/css",
      fs.readFileSync(path.join(repoRoot, "web", "app.css")),
    ],
    "/app.js": [
      "text/javascript",
      fs.readFileSync(path.join(repoRoot, "web", "app.js")),
    ],
    "/manifest.webmanifest": [
      "application/manifest+json",
      fs.readFileSync(path.join(repoRoot, "web", "manifest.webmanifest")),
    ],
  };

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (assets[url.pathname]) {
      const [contentType, body] = assets[url.pathname];
      await route.fulfill({ status: 200, contentType, body });
      return;
    }
    if (url.pathname === "/api/health") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          ffmpeg: true,
          database: true,
          encoders: { infant: true, human_imitation: true },
          population_baseline: true,
        }),
      });
      return;
    }
    if (url.pathname === "/api/profiles" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ profiles: [] }),
      });
      return;
    }
    if (url.pathname === "/api/live-sessions" && request.method() === "POST") {
      requests.created.push(request.postDataJSON());
      const planned = Array.isArray(requests.createQueue)
        ? requests.createQueue.shift()
        : "success";
      if (planned === "network") {
        await route.abort("failed");
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session: {
            id: 77,
            kind: "human_imitation",
            status: "open",
            created_at: "2026-07-30T00:00:00+00:00",
            completed_at: null,
            participants: [],
            observations: [],
          },
        }),
      });
      return;
    }
    if (
      url.pathname === "/api/live-sessions/77/observations" &&
      request.method() === "POST"
    ) {
      const requestBody = request.postDataBuffer();
      requests.observed.push({
        source: request.headers()["x-capture-source"],
        contentType: request.headers()["content-type"],
        bodyHex: requestBody ? requestBody.toString("hex") : "",
      });
      const planned = Array.isArray(requests.queue)
        ? requests.queue.shift()
        : "success";
      if (planned === "network") {
        await route.abort("failed");
        return;
      }
      if (planned === "invalid") {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            session: {
              id: 77,
              kind: "human_imitation",
              status: "open",
              created_at: "2026-07-30T00:00:00+00:00",
              completed_at: null,
              participants: [],
              observations: [],
            },
            observation: null,
            classification: {
              status: "invalid",
              participant: null,
              reinforced: false,
              reason_codes: ["decode_failed"],
            },
          }),
        });
        return;
      }
      if (planned === "completed") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            session: {
              id: 77,
              kind: "human_imitation",
              status: "completed",
              created_at: "2026-07-30T00:00:00+00:00",
              completed_at: "2026-07-30T00:10:00+00:00",
              participants: [],
              observations: [],
            },
            observation: null,
            classification: {
              status: "session_completed",
              participant: null,
              reinforced: false,
              reason_codes: ["session_completed"],
            },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(liveResponse(requests.observed.length)),
      });
      return;
    }
    if (url.pathname.startsWith("/api/audio/live-observations/")) {
      await route.fulfill({
        status: 200,
        contentType: "audio/wav",
        body: Buffer.from("RIFF browser fixture"),
      });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });
}

async function exerciseViewport(browser, viewport) {
  const page = await browser.newPage({ viewport });
  const requests = { created: [], observed: [] };
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await installRoutes(page, requests);
  await page.goto("http://live.test/", { waitUntil: "domcontentloaded" });
  assert(
    await page.locator("#not-in-this-build").isHidden(),
    `${viewport.width}: roadmap was visible on the initial mode screen`
  );
  await page.click("#btn-kind-imitation");

  assert(
    await page.locator("#live-session-console").isVisible(),
    `${viewport.width}: live console is not visible`
  );
  assert(
    await page.locator("#legacy-workflow").isHidden(),
    `${viewport.width}: legacy human workflow remained visible`
  );
  assert(
    await page.locator("#not-in-this-build").isHidden(),
    `${viewport.width}: roadmap remained visible in human mode`
  );
  assert(
    await page.locator("#live-file-input").isDisabled(),
    `${viewport.width}: capture started without an explicit session`
  );
  assert(
    requests.created.length === 0,
    `${viewport.width}: entering human mode created a session`
  );

  await page.click("#btn-new-live-session");
  await page.waitForFunction(
    () => !document.querySelector("#live-file-input").disabled
  );
  assert(
    requests.created.length === 1 &&
      requests.created[0].kind === "human_imitation",
    `${viewport.width}: New session did not create exactly one imitation session`
  );

  const input = page.locator("#live-file-input");
  await input.setInputFiles({
    name: "first.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("RIFF first independent recording"),
  });
  await page.waitForSelector(
    '#live-participants-list .live-participant[data-state="provisional"]'
  );
  const provisionalBorder = await page
    .locator("#live-participants-list .live-participant")
    .evaluate((node) => getComputedStyle(node).borderStyle);
  assert(
    provisionalBorder === "dotted",
    `${viewport.width}: provisional participant border was ${provisionalBorder}`
  );
  assert(
    (await page.locator("#live-result-status").textContent()) === "New pattern",
    `${viewport.width}: first result was not provisional`
  );

  await input.setInputFiles({
    name: "second.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("RIFF second independent recording"),
  });
  await page.waitForSelector(
    '#live-participants-list .live-participant[data-state="established"]'
  );
  const establishedBorder = await page
    .locator("#live-participants-list .live-participant")
    .evaluate((node) => getComputedStyle(node).borderStyle);
  assert(
    establishedBorder === "solid",
    `${viewport.width}: established participant border was ${establishedBorder}`
  );
  assert(
    (await page.locator("#live-result-status").textContent()) ===
      "Repeated pattern",
    `${viewport.width}: second result was not established`
  );
  assert(
    (await page.locator("#live-timeline-list > li").count()) === 2,
    `${viewport.width}: timeline does not contain two observations`
  );
  assert(
    (await page.locator("#live-timeline-list audio").count()) === 2,
    `${viewport.width}: timeline playback is missing`
  );
  assert(
    requests.observed.length === 2 &&
      requests.observed.every(
        (request) =>
          request.source === "upload" &&
          request.contentType.startsWith("audio/wav")
      ),
    `${viewport.width}: file selection did not submit exactly one upload each`
  );
  assert(
    requests.observed[0].bodyHex ===
      Buffer.from("RIFF first independent recording").toString("hex") &&
      requests.observed[1].bodyHex ===
        Buffer.from("RIFF second independent recording").toString("hex") &&
      requests.observed[0].bodyHex !== requests.observed[1].bodyHex,
    `${viewport.width}: the two observation requests did not carry distinct recordings`
  );

  const geometry = await page.evaluate(() => {
    const rect = (selector) => {
      const value = document.querySelector(selector).getBoundingClientRect();
      return {
        x: Math.round(value.x),
        y: Math.round(value.y),
        width: Math.round(value.width),
        height: Math.round(value.height),
      };
    };
    return {
      innerWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      capture: rect("#live-capture-panel"),
      result: rect("#live-result-panel"),
      timeline: rect("#live-session-timeline"),
      participants: rect("#live-participant-strip"),
    };
  });
  assert(
    geometry.documentWidth <= geometry.innerWidth &&
      geometry.bodyWidth <= geometry.innerWidth,
    `${viewport.width}: horizontal overflow ${JSON.stringify(geometry)}`
  );
  if (viewport.width >= 900) {
    assert(
      geometry.result.x > geometry.capture.x &&
        Math.abs(geometry.result.y - geometry.capture.y) <= 2,
      `${viewport.width}: desktop cards are not paired in columns`
    );
    assert(
      geometry.timeline.x === geometry.capture.x &&
        geometry.timeline.width > geometry.capture.width,
      `${viewport.width}: timeline does not span the desktop workspace`
    );
  } else {
    assert(
      geometry.result.y > geometry.capture.y &&
        geometry.result.x === geometry.capture.x,
      `${viewport.width}: phone cards did not collapse to one column`
    );
  }
  assert(
    pageErrors.length === 0,
    `${viewport.width}: browser errors: ${pageErrors.join("; ")}`
  );
  if (process.env.LIVE_SESSION_SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.LIVE_SESSION_SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({
      path: path.join(
        process.env.LIVE_SESSION_SCREENSHOT_DIR,
        `live-session-${viewport.width}x${viewport.height}.png`
      ),
      fullPage: true,
    });
  }

  requests.createQueue = ["network"];
  await page.click("#btn-new-live-session");
  await page.waitForFunction(() =>
    document
      .querySelector("#live-submit-status")
      .textContent.includes("could not be created")
  );
  assert(
    (await page.locator("#live-timeline-list > li").count()) === 2 &&
      (await page
        .locator(
          '#live-participants-list .live-participant[data-state="established"]'
        )
        .count()) === 1,
    `${viewport.width}: failed New session erased the current server-backed session`
  );

  await input.setInputFiles({
    name: "third.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("RIFF third independent recording"),
  });
  await page.waitForSelector("#live-timeline-list > li:nth-child(3)");
  assert(
    (await page.locator(".live-participant-support").textContent()) ===
      "3 supporting recordings",
    `${viewport.width}: support count above two was not shown exactly`
  );
  assert(
    requests.observed.length === 3,
    `${viewport.width}: exact support count check made an unexpected submission`
  );
  await page.close();
  return geometry;
}

async function exerciseFailureStates(browser) {
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
  const requests = {
    created: [],
    observed: [],
    queue: ["network", "invalid", "completed"],
  };
  await installRoutes(page, requests);
  await page.goto("http://live.test/", { waitUntil: "domcontentloaded" });
  await page.click("#btn-kind-imitation");
  await page.click("#btn-new-live-session");
  await page.waitForFunction(
    () => !document.querySelector("#live-file-input").disabled
  );

  const input = page.locator("#live-file-input");
  await input.setInputFiles({
    name: "network-failure.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("RIFF retained recording"),
  });
  await page.waitForSelector("#btn-live-retry:visible");
  assert(
    !(await page.locator("#btn-live-retry").isDisabled()),
    "network failure did not leave the retained clip available"
  );
  assert(
    (await input.inputValue()).endsWith("network-failure.wav"),
    "network failure cleared the selected file"
  );

  await page.click("#btn-live-retry");
  await page.waitForFunction(
    () => document.querySelector("#live-result-panel").dataset.status === "invalid"
  );
  assert(
    (await page.locator("#live-result-explanation").textContent()) ===
      "This recording could not be used. Move closer and try again.",
    "invalid response did not render the capture correction"
  );
  assert(
    (await page.locator("#live-timeline-list > li").count()) === 0,
    "client invented an invalid timeline row absent from server state"
  );
  assert(
    (await input.inputValue()) === "",
    "accepted invalid response did not clear the unusable clip"
  );
  assert(
    requests.observed.length === 2,
    "retained clip retry did not make exactly one follow-up request"
  );

  await input.setInputFiles({
    name: "completed-session.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("RIFF recording rejected by completed session"),
  });
  await page.waitForFunction(
    () =>
      document.querySelector("#live-result-panel").dataset.status ===
      "session_completed"
  );
  assert(
    (await page.locator("#live-submit-status").textContent()).includes(
      "was not added"
    ),
    "completed-session response claimed that the recording was accepted"
  );
  assert(
    (await input.inputValue()).endsWith("completed-session.wav"),
    "completed-session response discarded the unaccepted recording"
  );
  assert(
    await input.isDisabled(),
    "completed session left capture enabled"
  );
  assert(
    requests.observed.length === 3,
    "completed-session check made an unexpected observation request"
  );
  await page.click("#btn-new-live-session");
  await page.waitForSelector("#btn-live-retry:visible");
  assert(
    !(await page.locator("#btn-live-retry").isDisabled()) &&
      (await input.inputValue()).endsWith("completed-session.wav") &&
      requests.observed.length === 3,
    "starting a replacement session did not keep the rejected recording available"
  );
  await page.close();
}

async function exerciseMicrophoneStop(browser) {
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
  const requests = { created: [], observed: [] };
  await page.addInitScript(() => {
    window.__captureOrder = [];
    const pause = HTMLMediaElement.prototype.pause;
    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value(...args) {
        window.__captureOrder.push("pause");
        return pause.apply(this, args);
      },
    });
    const track = {
      addEventListener() {},
      getSettings() {
        return {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        };
      },
      stop() {},
    };
    const stream = {
      getAudioTracks() {
        return [track];
      },
      getTracks() {
        return [track];
      },
    };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        async getUserMedia() {
          return stream;
        },
      },
    });
    class FakeMediaRecorder {
      static isTypeSupported(type) {
        return type.startsWith("audio/webm");
      }

      constructor(_stream, options = {}) {
        this.mimeType = options.mimeType || "audio/webm";
        this.state = "inactive";
        this.listeners = new Map();
      }

      addEventListener(name, callback) {
        const listeners = this.listeners.get(name) || [];
        listeners.push(callback);
        this.listeners.set(name, listeners);
      }

      dispatch(name, event = {}) {
        for (const callback of this.listeners.get(name) || []) callback(event);
      }

      start() {
        window.__captureOrder.push("start");
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
        this.dispatch("dataavailable", {
          data: new Blob(["independent microphone recording"], {
            type: this.mimeType,
          }),
        });
        this.dispatch("stop");
      }
    }
    Object.defineProperty(window, "MediaRecorder", {
      configurable: true,
      value: FakeMediaRecorder,
    });
  });
  await installRoutes(page, requests);
  await page.goto("http://localhost/", { waitUntil: "domcontentloaded" });
  await page.click("#btn-kind-imitation");
  await page.click("#btn-new-live-session");
  await page.waitForFunction(
    () => !document.querySelector("#btn-live-record-start").disabled
  );
  await page.evaluate(() => {
    const audio = document.createElement("audio");
    audio.id = "playback-order-probe";
    document.body.appendChild(audio);
  });
  await page.click("#btn-live-record-start");
  await page.waitForFunction(() => document.body.dataset.recording === "true");
  const captureOrder = await page.evaluate(() => window.__captureOrder);
  assert(
    captureOrder.indexOf("pause") > -1 &&
      captureOrder.indexOf("pause") < captureOrder.indexOf("start"),
    `playback was not paused before capture started: ${captureOrder.join(", ")}`
  );
  await page.click("#btn-live-record-stop");
  await page.waitForSelector(
    '#live-participants-list .live-participant[data-state="provisional"]'
  );
  assert(
    requests.observed.length === 1 &&
      requests.observed[0].source === "microphone",
    "microphone stop did not submit exactly one microphone observation"
  );
  await page.close();
}

async function exerciseBabyMode(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const requests = { created: [], observed: [] };
  await installRoutes(page, requests);
  await page.goto("http://live.test/", { waitUntil: "domcontentloaded" });
  assert(
    await page.locator("#not-in-this-build").isHidden(),
    "roadmap was visible on the initial mode screen"
  );
  await page.click("#btn-kind-infant");
  assert(
    await page.locator("#live-session-console").isHidden(),
    "baby mode displayed the live human console"
  );
  assert(
    await page.locator("#legacy-workflow").isVisible(),
    "baby mode lost the legacy care workflow"
  );
  for (const selector of [
    "#panel-capture",
    "#panel-profiles",
    "#panel-enroll",
    "#panel-query",
    "#manual-profile-create",
  ]) {
    assert(
      await page.locator(selector).isVisible(),
      `baby mode hid ${selector}`
    );
  }
  assert(
    await page.locator("#not-in-this-build").isHidden(),
    "baby mode displayed the roadmap"
  );
  assert(
    await page.locator("#file-input").isEnabled(),
    "baby file capture is no longer available"
  );
  const shellWidth = await page
    .locator("#app-shell")
    .evaluate((node) => Math.round(node.getBoundingClientRect().width));
  assert(shellWidth === 760, `baby reading column changed to ${shellWidth}`);
  assert(
    requests.created.length === 0 && requests.observed.length === 0,
    "baby mode called the live-session API"
  );
  await page.close();
}

const { chromium } = loadPlaywright();
const chromeCandidates = [
  path.join(
    os.homedir(),
    "Library",
    "Caches",
    "ms-playwright",
    "chromium_headless_shell-1208",
    "chrome-headless-shell-mac-arm64",
    "chrome-headless-shell"
  ),
  chromium.executablePath(),
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const executablePath = chromeCandidates.find((candidate) => fs.existsSync(candidate));
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});
try {
  const evidence = [];
  for (const viewport of [
    { width: 430, height: 932 },
    { width: 900, height: 900 },
    { width: 1440, height: 900 },
  ]) {
    evidence.push(await exerciseViewport(browser, viewport));
  }
  await exerciseFailureStates(browser);
  await exerciseMicrophoneStop(browser);
  await exerciseBabyMode(browser);
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
  process.stdout.write("Live session browser checks passed.\n");
} finally {
  await browser.close();
}
