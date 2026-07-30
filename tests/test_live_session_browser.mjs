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
  id: 12,
  display_name: "Demo Baby",
  kind: "infant",
  status: "ready",
  enrollments: 3,
};
const learningProfile = {
  id: 13,
  display_name: "Learning Baby",
  kind: "infant",
  status: "ready",
  enrollments: 3,
};

function publicSession(status, lastSequence, decision = null) {
  return {
    id: 41,
    status,
    profile,
    started_at: "2026-07-30T20:15:00-04:00",
    paused_at: status === "paused" ? "2026-07-30T20:15:05-04:00" : null,
    stopped_at: status === "awaiting_outcome" ? "2026-07-30T20:15:06-04:00" : null,
    completed_at: status === "complete" ? "2026-07-30T20:16:00-04:00" : null,
    last_sequence: lastSequence,
    tags: [],
    decision,
  };
}

const decision = {
  id: 88,
  latched_at: "2026-07-30T20:15:15-04:00",
  profile: { id: 12, display_name: "Baby Test" },
  guidance: {
    status: "grounded",
    headline: "Server headline",
    interpretation: "Server interpretation",
    recommendation: "Server recommendation, exactly",
    evidence_summary: "Server evidence summary",
    support_count: 1,
    incident_ids: [101],
    pattern: "server pattern",
  },
  basis: ["Server basis line"],
  scenarios: [
    {
      episode_id: 101,
      started_at: "2026-07-27T20:04:00-04:00",
      interventions: [{ order: 1, action: "Server action", evidence: "Literal evidence" }],
      outcome: "Server outcome",
      outcome_src: "caregiver",
      worked: true,
      contributions: ["Server basis line"],
      audio_url: "/api/profiles/12/incidents/101/audio",
    },
  ],
};

async function installBrowserFakes(page) {
  await page.addInitScript(() => {
    window.__getUserMediaCalls = 0;
    window.__fakeAnalyserRms = 0.00045;
    window.__audioContextResumeCalls = 0;
    window.__audioActivationOrder = [];
    class FakeTrack extends EventTarget {
      constructor() {
        super();
        this.readyState = "live";
        this.muted = false;
      }
      getSettings() {
        return {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          sampleRate: 48000,
        };
      }
      stop() {
        this.readyState = "ended";
      }
    }
    class FakeStream {
      constructor() {
        this.track = new FakeTrack();
      }
      getAudioTracks() {
        return [this.track];
      }
      getTracks() {
        return [this.track];
      }
    }
    class FakeMediaRecorder extends EventTarget {
      static isTypeSupported() {
        return true;
      }
      constructor(stream, options = {}) {
        super();
        this.stream = stream;
        this.mimeType = options.mimeType || "audio/mp4";
        this.state = "inactive";
      }
      start() {
        this.state = "recording";
      }
      stop() {
        if (this.state === "inactive") return;
        this.state = "inactive";
        this.dispatchEvent(new MessageEvent("dataavailable", {
          data: new Blob(["same finalized segment"], { type: this.mimeType }),
        }));
        this.dispatchEvent(new Event("stop"));
      }
    }
    class FakeAudioContext {
      constructor() {
        window.__audioActivationOrder.push("context");
        this.state = "suspended";
      }
      createMediaStreamSource() {
        return {
          connect() {},
          disconnect() {},
        };
      }
      createAnalyser() {
        return {
          fftSize: 512,
          getFloatTimeDomainData(data) {
            for (let i = 0; i < data.length; i++) {
              data[i] = (i % 2 ? -1 : 1) * window.__fakeAnalyserRms;
            }
          },
          getByteTimeDomainData(data) {
            const offset = Math.round(window.__fakeAnalyserRms * 128);
            for (let i = 0; i < data.length; i++) {
              data[i] = 128 + (i % 2 ? -offset : offset);
            }
          },
        };
      }
      resume() {
        window.__audioActivationOrder.push("resume");
        window.__audioContextResumeCalls += 1;
        this.state = "running";
        return new Promise(() => {});
      }
      async close() {
        this.state = "closed";
      }
    }
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          window.__audioActivationOrder.push("getUserMedia");
          window.__getUserMediaCalls += 1;
          return new FakeStream();
        },
      },
    });
    Object.defineProperty(window, "MediaRecorder", {
      configurable: true,
      value: FakeMediaRecorder,
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: FakeAudioContext,
    });
    Object.defineProperty(window, "webkitAudioContext", {
      configurable: true,
      value: FakeAudioContext,
    });
  });
}

async function installRoutes(page, requests, options = {}) {
  const cssSource = fs.readFileSync(path.join(repoRoot, "web", "app.css"), "utf8");
  const servedCss = options.safeArea
    ? cssSource +
      "\n:root { --sat: 18px; --sab: 16px; --sal: 47px; --sar: 47px; }\n"
    : cssSource;
  const assets = {
    "/": ["text/html", fs.readFileSync(path.join(repoRoot, "web", "index.html"))],
    "/app.css": ["text/css", Buffer.from(servedCss)],
    "/app.js": ["text/javascript", fs.readFileSync(path.join(repoRoot, "web", "app.js"))],
    "/manifest.webmanifest": [
      "application/manifest+json",
      fs.readFileSync(path.join(repoRoot, "web", "manifest.webmanifest")),
    ],
  };
  const chunkMode = options.chunkMode || "guidance";
  let firstChunkAttempt = options.retryFirst !== false;
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (assets[url.pathname]) {
      const [contentType, body] = assets[url.pathname];
      await route.fulfill({
        status: 200,
        contentType,
        headers: {
          "Content-Security-Policy":
            "default-src 'self'; script-src 'self'; connect-src 'self'; " +
            "style-src 'self'; media-src 'self'; img-src 'self' data:; " +
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        },
        body,
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
        body: JSON.stringify({ profiles: [learningProfile, profile] }),
      });
      return;
    }
    if (url.pathname === "/api/care-sessions" && request.method() === "POST") {
      requests.created.push(request.postDataJSON());
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ session: publicSession("listening", 0) }),
      });
      return;
    }
    if (url.pathname === "/api/care-sessions/41/chunks") {
      const body = request.postDataBuffer();
      requests.chunks.push({
        sequence: request.headers()["x-capture-sequence"],
        source: request.headers()["x-capture-source"],
        bodyHex: body ? body.toString("hex") : "",
      });
      if (firstChunkAttempt) {
        firstChunkAttempt = false;
        await route.abort("failed");
        return;
      }
      if (chunkMode === "no_cry") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            session: publicSession("listening", 1),
            chunk: {
              id: 90,
              sequence: 1,
              status: "no_cry_detected",
              reason_codes: ["no_infant_cry_evidence"],
              cry_presence: {
                status: "no_cry_detected",
                label: null,
                reason_codes: ["no_infant_cry_evidence"],
                analyzed_duration_s: 1,
                analysis_view_count: 1,
                model_version: "test",
              },
            },
          }),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          session: publicSession("listening", 1, decision),
          chunk: {
            id: 90,
            sequence: 1,
            status: "guidance_latched",
            reason_codes: [],
            cry_presence: {
              status: "infant_cry_detected",
              label: "Infant-cry-like sound detected",
              reason_codes: ["infant_cry_evidence_strong"],
              analyzed_duration_s: 1,
              analysis_view_count: 1,
              model_version: "test",
            },
          },
        }),
      });
      return;
    }
    if (url.pathname === "/api/care-sessions/41/stop") {
      requests.stopped += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session: publicSession(
            "awaiting_outcome",
            1,
            chunkMode === "guidance" ? decision : null
          ),
        }),
      });
      return;
    }
    if (url.pathname === "/api/care-sessions/41/complete") {
      requests.completed.push(request.postDataJSON());
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session: publicSession("complete", 1, decision),
          incident: { id: 101, detail_url: "/api/profiles/12/incidents/101" },
        }),
      });
      return;
    }
    if (url.pathname === "/api/care-sessions/41" && request.method() === "DELETE") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ session: publicSession("discarded", 1, decision) }),
      });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });
}

async function runLivePath(browser) {
  const page = await browser.newPage({ viewport: { width: 430, height: 932 } });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  const pageErrors = [];
  const cspErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" &&
        /content security policy|refused to apply|refused to execute/i.test(message.text())) {
      cspErrors.push(message.text());
    }
  });
  await installBrowserFakes(page);
  await installRoutes(page, requests);
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  assert(await page.locator(".profile-label").count() === 0,
    "visible Listening for title was not removed");

  const phaseStatus = await page.evaluate(() => {
    window.setAnalysis("Listening", 0);
    window.setAnalysis("Still listening", 0);
    const labels = document.querySelectorAll("#analysis-status:not([hidden])");
    const node = document.querySelector("#analysis-status");
    return {
      visibleLabels: labels.length,
      text: node.textContent,
      opacity: getComputedStyle(node).opacity,
      childElements: node.childElementCount,
    };
  });
  assert(
    phaseStatus.visibleLabels === 1 &&
      phaseStatus.childElements === 0 &&
      phaseStatus.text === "Still listening" &&
      phaseStatus.opacity !== "0",
    `phase status did not replace synchronously: ${JSON.stringify(phaseStatus)}`
  );

  assert(await page.locator("#listen-name").textContent() === "Demo Baby",
    "Demo Baby was not the default active infant");
  await page.selectOption("#profile-picker", "13");
  assert(await page.locator("#listen-name").textContent() === "Learning Baby",
    "active baby selector did not switch to Learning Baby");
  await page.selectOption("#profile-picker", "12");
  assert(await page.locator("#history-limited").isVisible() === false,
    "History content leaked into Listen");

  await page.click("#tab-history");
  assert(await page.locator("#history-limited").isVisible(), "History limit is not visible");
  await page.click("#tab-listen");
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');
  assert(await page.locator("#profile-picker").isDisabled(),
    "active baby remained switchable during an open session");
  assert(await page.evaluate(() => window.__getUserMediaCalls) === 1,
    "Start did not retain one MediaStream");
  await page.waitForTimeout(180);
  const quietEnergy = Number(await page.locator("#orb").getAttribute("data-energy"));
  await page.evaluate(() => { window.__fakeAnalyserRms = 0.01; });
  await page.waitForTimeout(360);
  const cryEnergy = Number(await page.locator("#orb").getAttribute("data-energy"));
  assert(quietEnergy <= 0.1 && cryEnergy >= 0.7,
    `microphone energy was not visually distinct: quiet=${quietEnergy}, cry=${cryEnergy}`);
  assert(await page.evaluate(() => window.__audioContextResumeCalls) === 1,
    "suspended iOS AudioContext was not resumed");
  const activationOrder = await page.evaluate(() => window.__audioActivationOrder);
  assert(
    activationOrder.indexOf("resume") < activationOrder.indexOf("getUserMedia"),
    `AudioContext was not primed during the trusted click: ${activationOrder.join(",")}`
  );
  assert(await page.locator("#analysis-status").textContent() === "Listening",
    "microphone energy changed the server-owned cry status");
  assert(await page.locator("#suggestion-block").isHidden(),
    "microphone energy created client-side guidance");
  assert(requests.created.length === 1 && requests.created[0].profile_id === 12,
    "session was not created for the selected infant");
  await page.evaluate(() => { window.__sameDocumentMarker = "kept"; });
  await page.click("#tab-history");
  await page.click("#tab-listen");
  assert(await page.evaluate(() => window.__sameDocumentMarker) === "kept",
    "page navigation reloaded the document");
  assert(await page.evaluate(() => window.__getUserMediaCalls) === 1,
    "view navigation replaced the retained MediaStream");

  const invalidCopy = await page.evaluate(() => {
    const read = (reason) => {
      renderChunkResult({
        chunk: { status: "invalid", reason_codes: [reason] },
      });
      return document.querySelector("#analysis-status").textContent;
    };
    return {
      uneven: read("unsafe_normalization_headroom"),
      quiet: read("near_silence"),
      decode: read("decode_failed"),
    };
  });
  assert(invalidCopy.uneven === "That segment was too uneven. Still listening",
    `uneven audio was mislabeled: ${JSON.stringify(invalidCopy)}`);
  assert(invalidCopy.quiet === "That segment was too quiet. Still listening",
    `quiet audio was mislabeled: ${JSON.stringify(invalidCopy)}`);
  assert(invalidCopy.decode === "That segment could not be read. Still listening",
    `decode failure was mislabeled: ${JSON.stringify(invalidCopy)}`);

  await page.click("#btn-stop");
  await page.waitForSelector('body[data-session="awaiting_outcome"]', { timeout: 10000 });
  assert(requests.chunks.length === 2, "failed finalized segment was not retried once");
  assert(requests.chunks[0].sequence === "1" && requests.chunks[1].sequence === "1",
    "retry did not preserve capture sequence 1");
  assert(requests.chunks[0].bodyHex === requests.chunks[1].bodyHex,
    "retry did not preserve the exact finalized bytes");
  assert(requests.stopped === 1, "server Stop did not happen exactly once after drain");

  assert(await page.locator("#g-recommendation").textContent() ===
    "Server recommendation, exactly", "server recommendation was rewritten");
  assert(await page.locator("#g-evidence-summary").textContent() ===
    "Server evidence summary", "server evidence summary was rewritten");

  await page.fill("#outcome-action", "Held upright");
  await page.click('#settled-seg button[data-settled="true"]');
  await page.click("#btn-save-outcome");
  await page.waitForSelector('body[data-session="saved"]');
  assert(requests.completed.length === 1, "structured outcome was not saved once");
  assert(requests.completed[0].action === "Held upright", "typed action changed");
  assert(requests.completed[0].settled === true, "settled value changed");

  const hasOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  assert(!hasOverflow, "portrait has horizontal overflow");
  assert(pageErrors.length === 0, `page errors: ${pageErrors.join("; ")}`);
  assert(cspErrors.length === 0, `CSP errors: ${cspErrors.join("; ")}`);
  await page.close();
}

async function checkResponsiveShell(browser, viewport) {
  const page = await browser.newPage({ viewport });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests);
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  assert(!overflow, `${viewport.width}x${viewport.height} has horizontal overflow`);
  if (viewport.width >= 900) {
    const shellWidth = await page.locator("#app-shell").evaluate((node) =>
      node.getBoundingClientRect().width
    );
    assert(shellWidth >= 850, `desktop shell remained a phone column at ${shellWidth}px`);
  }
  await page.close();
}

async function runNoCryPath(browser) {
  const page = await browser.newPage({ viewport: { width: 430, height: 932 } });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, { chunkMode: "no_cry", retryFirst: false });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');
  await page.click("#btn-stop");
  await page.waitForSelector('body[data-session="awaiting_outcome"]');
  assert(await page.locator("#suggestion-block").isHidden(),
    "no_cry_detected created a suggestion");
  assert(await page.locator("#incident-list li").count() === 0,
    "no_cry_detected created supporting history");
  await page.close();
}

async function runSequentialOutcomePath(browser) {
  const page = await browser.newPage({ viewport: { width: 932, height: 430 } });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, {
    chunkMode: "no_cry",
    retryFirst: false,
    safeArea: true,
  });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);

  for (let index = 1; index <= 3; index++) {
    await page.click("#btn-start");
    await page.waitForSelector('body[data-session="listening"]');
    const runDecision = {
      ...decision,
      id: 100 + index,
      guidance: {
        ...decision.guidance,
        recommendation: `Session ${index} recommendation`,
      },
    };
    await page.evaluate((value) => window.latchDecision(value), runDecision);
    await page.click("#btn-stop");
    await page.waitForSelector('body[data-session="awaiting_outcome"]');
    await page.waitForTimeout(500);

    const outcome = await page.evaluate(() => {
      const pageNode = document.querySelector("#page-listen");
      const suggestion = document.querySelector("#suggestion-block");
      const card = document.querySelector("#suggestion-card").getBoundingClientRect();
      const form = document.querySelector("#outcome-form").getBoundingClientRect();
      const pageRect = pageNode.getBoundingClientRect();
      return {
        suggestionVisible: !suggestion.hidden,
        recommendation: document.querySelector("#g-recommendation").textContent,
        pageWidth: Math.round(pageRect.width),
        cardWidth: Math.round(card.width),
        cardHeight: Math.round(card.height),
        formWidth: Math.round(form.width),
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        formPageBottom: Math.round(form.bottom - pageRect.top),
        pageScrollHeight: pageNode.scrollHeight,
      };
    });
    assert(outcome.suggestionVisible,
      `session ${index} hid the latched result after Stop`);
    assert(outcome.recommendation === `Session ${index} recommendation`,
      `session ${index} reused stale guidance: ${JSON.stringify(outcome)}`);
    assert(
      outcome.cardWidth >= outcome.pageWidth - 2 &&
        outcome.cardWidth / outcome.cardHeight >= 2.4,
      `session ${index} result was not a horizontal full-width summary: ` +
        JSON.stringify(outcome)
    );
    assert(outcome.formWidth >= outcome.pageWidth - 2,
      `session ${index} follow-up form was clipped: ${JSON.stringify(outcome)}`);
    assert(outcome.documentWidth <= outcome.viewportWidth + 1,
      `session ${index} outcome has horizontal overflow: ${JSON.stringify(outcome)}`);
    assert(outcome.formPageBottom <= outcome.pageScrollHeight + 1,
      `session ${index} outcome is vertically clipped: ${JSON.stringify(outcome)}`);

    await page.click("#btn-discard");
    await page.waitForSelector('body[data-session="idle"]');
    const reset = await page.evaluate(() => ({
      decision: document.querySelector("#page-listen").dataset.decision,
      suggestionHidden: document.querySelector("#suggestion-block").hidden,
      recommendation: document.querySelector("#g-recommendation").textContent,
    }));
    assert(
      reset.decision === "none" &&
        reset.suggestionHidden &&
        reset.recommendation === "",
      `session ${index} did not clear before the next recording: ${JSON.stringify(reset)}`
    );
  }
  await page.close();
}

async function landscapeMetrics(page) {
  return page.evaluate(() => {
    const pageNode = document.querySelector("#page-listen");
    const pageRect = pageNode.getBoundingClientRect();
    const controls = document.querySelector("#ctl-capsule").getBoundingClientRect();
    const profile = document.querySelector("#profile-control").getBoundingClientRect();
    const recorder = document.querySelector("#rec-chip").getBoundingClientRect();
    const orb = document.querySelector("#orb-wrap").getBoundingClientRect();
    const offenders = Array.from(document.querySelectorAll("body *"))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          id: node.id || node.className || node.tagName,
          top: Math.round(rect.top),
          bottom: Math.round(rect.bottom),
          height: Math.round(rect.height),
        };
      })
      .filter((item) => item.bottom > innerHeight + 1)
      .sort((a, b) => b.bottom - a.bottom)
      .slice(0, 8);
    return {
      innerHeight,
      documentClientHeight: document.documentElement.clientHeight,
      documentScrollHeight: document.documentElement.scrollHeight,
      bodyScrollHeight: document.body.scrollHeight,
      pageClientHeight: pageNode.clientHeight,
      pageScrollHeight: pageNode.scrollHeight,
      pageTop: Math.round(pageRect.top),
      pageBottom: Math.round(pageRect.bottom),
      pageChildren: Array.from(pageNode.children).map((node) => {
        const rect = node.getBoundingClientRect();
        return {
          id: node.id || node.className || node.tagName,
          top: Math.round(rect.top),
          bottom: Math.round(rect.bottom),
          height: Math.round(rect.height),
        };
      }),
      pageOverflowers: Array.from(pageNode.querySelectorAll("*"))
        .map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            id: node.id || node.className || node.tagName,
            top: Math.round(rect.top),
            bottom: Math.round(rect.bottom),
            height: Math.round(rect.height),
          };
        })
        .filter((item) => item.bottom > pageRect.bottom + 1)
        .sort((a, b) => b.bottom - a.bottom)
        .slice(0, 12),
      controlsTop: Math.round(controls.top),
      controlsBottom: Math.round(controls.bottom),
      profileCenter: Math.round(profile.top + profile.height / 2),
      recorderCenter: Math.round(recorder.top + recorder.height / 2),
      orbWidth: Math.round(orb.width),
      offenders,
    };
  });
}

async function runLandscapeListeningFit(browser) {
  const page = await browser.newPage({ viewport: { width: 932, height: 430 } });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, { retryFirst: false, safeArea: true });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');
  await page.waitForTimeout(700);

  const plain = await landscapeMetrics(page);
  assert(
    plain.documentScrollHeight <= plain.innerHeight + 1 &&
      plain.bodyScrollHeight <= plain.innerHeight + 1 &&
      plain.pageScrollHeight <= plain.pageClientHeight + 1,
    `landscape listening scrolls: ${JSON.stringify(plain)}`
  );
  assert(
    plain.controlsTop >= 0 && plain.controlsBottom <= plain.innerHeight,
    `landscape controls are clipped: ${JSON.stringify(plain)}`
  );
  assert(
    Math.abs(plain.profileCenter - plain.recorderCenter) <= 4,
    `landscape timer is not aligned with the baby profile: ${JSON.stringify(plain)}`
  );
  assert(
    plain.orbWidth >= 220,
    `landscape listening orb remained too small: ${JSON.stringify(plain)}`
  );

  await page.evaluate((serverDecision) => {
    window.latchDecision(serverDecision);
  }, decision);
  const latched = await landscapeMetrics(page);
  assert(
    latched.documentScrollHeight <= latched.innerHeight + 1 &&
      latched.bodyScrollHeight <= latched.innerHeight + 1 &&
      latched.pageScrollHeight <= latched.pageClientHeight + 1,
    `landscape suggestion scrolls: ${JSON.stringify(latched)}`
  );
  assert(
    latched.controlsTop >= 0 && latched.controlsBottom <= latched.innerHeight,
    `landscape suggestion controls are clipped: ${JSON.stringify(latched)}`
  );
  await page.close();
}

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  await runLivePath(browser);
  await runNoCryPath(browser);
  await runSequentialOutcomePath(browser);
  await runLandscapeListeningFit(browser);
  await checkResponsiveShell(browser, { width: 932, height: 430 });
  await checkResponsiveShell(browser, { width: 1440, height: 900 });
  console.log("continuous care browser checks passed");
} finally {
  await browser.close();
}
