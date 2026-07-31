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

async function ambientMetrics(page) {
  return page.evaluate(() => {
    const ambient = document.querySelector("#ambient");
    const style = getComputedStyle(ambient);
    return {
      opacity: style.opacity,
      visibility: style.visibility,
      lineArtCount: document.querySelectorAll("#ambient .am").length,
      stickers: Array.from(document.querySelectorAll("#ambient .ambient-sticker"))
        .map((node) => {
          const stickerStyle = getComputedStyle(node);
          return {
            source: node.getAttribute("src"),
            opacity: Number(stickerStyle.opacity),
            animationName: stickerStyle.animationName,
            animationDuration: stickerStyle.animationDuration,
            animationPlayState: stickerStyle.animationPlayState,
          };
        }),
    };
  });
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
      caregiver_evidence: {
        text: 'I said <img src=x onerror="window.__evidenceInjected=true"> held upright',
        source: "captured_transcript",
      },
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
  for (const imageName of [
    "action-cuddle.png",
    "action-feeding.png",
    "action-sleeping.png",
    "action-walk.png",
  ]) {
    assets[`/img/${imageName}`] = [
      "image/png",
      fs.readFileSync(path.join(repoRoot, "web", "img", imageName)),
    ];
  }
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
    if (url.pathname === "/api/visitor-session" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ session: { consented: false } }) });
      return;
    }
    if (url.pathname === "/api/visitor-session/consent" && request.method() === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ session: { consented: true } }) });
      return;
    }
    if (url.pathname === "/api/profiles/12" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        profile: { ...profile, memory_count: 1 }, training_clips: [], recent_care_events: [],
      }) });
      return;
    }
    if (url.pathname === "/api/profiles/12/incidents" && request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        profile, incidents: [{ id: 101, started_at: "2026-07-30T20:15:00-04:00",
          actions: [{ action: "Server action" }], outcome: { text: "Server outcome" },
          context: { tags: ["evening"] }, audio: { status: "unavailable" } }], next_cursor: null,
      }) });
      return;
    }
    if (url.pathname === "/api/live-sessions" && request.method() === "POST") {
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        session: { id: 77, participants: [], observations: [] },
      }) });
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
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    reducedMotion: "reduce",
  });
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
  const idleAmbient = await ambientMetrics(page);
  assert(
    idleAmbient.opacity === "1" &&
      idleAmbient.visibility === "visible" &&
      idleAmbient.lineArtCount === 0 &&
      idleAmbient.stickers.length === 4 &&
      idleAmbient.stickers.every((sticker) =>
        sticker.source.includes("/img/action-") &&
        sticker.opacity <= 0.1 &&
        sticker.animationName === "none"
      ),
    `reduced-motion idle ambient was not visible and static: ${JSON.stringify(idleAmbient)}`
  );
  const inactiveAmbients = await page.evaluate(() => {
    const result = {};
    for (const name of ["requesting", "paused"]) {
      setSessionState(name);
      const style = getComputedStyle(document.querySelector("#ambient"));
      result[name] = { opacity: style.opacity, visibility: style.visibility };
    }
    setSessionState("idle");
    return result;
  });
  assert(
    Object.values(inactiveAmbients).every((value) =>
      value.opacity === "0" && value.visibility === "hidden"
    ),
    `an inactive recording state left ambient art visible: ${JSON.stringify(inactiveAmbients)}`
  );
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
  assert(await page.locator("#history-list").isVisible() === false,
    "History content leaked into Listen");

  await page.click("#tab-history");
  await page.waitForSelector("#history-list .record-card");
  assert(await page.locator("#history-list .record-card").count() === 1,
    "History did not render the returned recorded moment");
  await page.click("#tab-baby");
  await page.waitForSelector("#baby-summary");
  assert((await page.locator("#baby-summary").textContent()).includes("Memories: 1"),
    "Baby did not render the returned memory summary");
  await page.evaluate(() => navigate("human"));
  assert(await page.locator("#human-consent").isVisible(), "Human Baby consent is not visible");
  await page.click("#btn-human-consent");
  await page.click("#btn-new-human-session");
  await page.waitForFunction(() => !document.querySelector("#btn-human-record").disabled);
  await page.click("#tab-listen");
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');
  await page.evaluate(() => {
    clearInterval(state.rotateTimer);
    state.rotateTimer = null;
  });
  const listeningAmbient = await ambientMetrics(page);
  assert(
    listeningAmbient.opacity === "0" &&
      listeningAmbient.visibility === "hidden",
    `listening left the ambient layer visible: ${JSON.stringify(listeningAmbient)}`
  );
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
  assert(await page.locator("#analysis-status").textContent() === "Checking for infant cry",
    "sustained microphone activity did not enter the neutral checking state");
  assert(await page.locator("#orb").getAttribute("data-visual-state") === "checking",
    "the orb did not react while the server was checking the active sound");
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

  const detectionOrder = await page.evaluate((payload) => {
    const progress = [];
    for (let sequence = 1; sequence <= 3; sequence += 1) {
      state.activeUpload = { sequence };
      acceptUploadedSegment({ sequence }, {
        session: {
          ...payload.session,
          last_sequence: sequence,
          decision: null,
        },
        chunk: {
          ...payload.chunk,
          id: 89 + sequence,
          sequence,
          status: "matched_no_guidance",
          decision_progress: {
            consistent_grounded_segments: sequence,
            required_consistent_grounded_segments: 4,
            additional_confirmations: sequence - 1,
            required_additional_confirmations: 3,
            decision_eligible: false,
            label: `Infant cry detected. Match held. Confirming ${sequence - 1} of 3`,
          },
        },
      });
      progress.push({
        status: document.querySelector("#analysis-status").textContent,
        orb: document.querySelector("#orb").dataset.visualState,
        suggestionHidden: document.querySelector("#suggestion-block").hidden,
        decision: document.querySelector("#page-listen").dataset.decision,
        acceptedSequence: state.acceptedSequence,
      });
    }
    return progress;
  }, {
    session: publicSession("listening", 4, decision),
    chunk: {
      id: 93,
      sequence: 4,
      status: "guidance_latched",
      reason_codes: [],
      decision_progress: {
        consistent_grounded_segments: 4,
        required_consistent_grounded_segments: 4,
        additional_confirmations: 3,
        required_additional_confirmations: 3,
        decision_eligible: true,
        label: "Infant cry detected. Match confirmed 3 of 3",
      },
      cry_presence: {
        status: "infant_cry_detected",
        label: "Infant-cry-like sound detected",
        reason_codes: ["infant_cry_evidence_strong"],
        analyzed_duration_s: 6,
        analysis_view_count: 1,
        model_version: "test",
      },
    },
  });
  assert(
    detectionOrder.length === 3 &&
      detectionOrder.every((step, index) =>
        step.status === "Infant-cry-like sound detected" &&
        step.orb === "detected" &&
        step.suggestionHidden &&
        step.decision === "none" &&
        step.acceptedSequence === index + 1
      ),
    `detection was not visible before guidance: ${JSON.stringify(detectionOrder)}`
  );

  await page.waitForFunction(() =>
    document.querySelector("#analysis-status").textContent ===
      "Infant cry detected. Match held. Confirming 2 of 3"
  );

  const immediate = await page.evaluate((payload) => {
    state.activeUpload = { sequence: 4 };
    acceptUploadedSegment({ sequence: 4 }, payload);
    return {
      status: document.querySelector("#analysis-status").textContent,
      orb: document.querySelector("#orb").dataset.visualState,
      suggestionHidden: document.querySelector("#suggestion-block").hidden,
      decision: document.querySelector("#page-listen").dataset.decision,
      recommendation: document.querySelector("#g-recommendation").textContent,
      acceptedSequence: state.acceptedSequence,
      uploadCleared: state.activeUpload === null,
    };
  }, {
    session: publicSession("listening", 4, decision),
    chunk: {
      id: 93,
      sequence: 4,
      status: "guidance_latched",
      reason_codes: [],
      decision_progress: {
        consistent_grounded_segments: 4,
        required_consistent_grounded_segments: 4,
        additional_confirmations: 3,
        required_additional_confirmations: 3,
        decision_eligible: true,
        label: "Infant cry detected. Match confirmed 3 of 3",
      },
      cry_presence: {
        status: "infant_cry_detected",
        label: "Infant-cry-like sound detected",
        reason_codes: ["infant_cry_evidence_strong"],
        analyzed_duration_s: 6,
        analysis_view_count: 1,
        model_version: "test",
      },
    },
  });
  assert(
    immediate.status === "Infant-cry-like sound detected" &&
      immediate.orb === "detected" &&
      immediate.suggestionHidden &&
      immediate.decision === "none",
    `guidance hid the immediate cry response: ${JSON.stringify(immediate)}`
  );
  assert(
    immediate.acceptedSequence === 4 &&
      immediate.uploadCleared,
    `detection-first reveal blocked upload progress: ${JSON.stringify(immediate)}`
  );

  await page.waitForFunction(() =>
    document.querySelector("#orb").dataset.visualState === "grounded" &&
      !document.querySelector("#suggestion-block").hidden &&
      document.querySelector("#page-listen").dataset.decision === "latched" &&
      document.querySelector("#g-recommendation").textContent ===
        "Server recommendation, exactly"
  );
  const revealed = await page.evaluate(() => {
    const result = {
      orb: document.querySelector("#orb").dataset.visualState,
      suggestionHidden: document.querySelector("#suggestion-block").hidden,
      decision: document.querySelector("#page-listen").dataset.decision,
      recommendation: document.querySelector("#g-recommendation").textContent,
      caregiverEvidence: document.querySelector("#incident-list .quote").textContent,
      caregiverEvidenceHtml: document.querySelector("#incident-list .quote").innerHTML,
      injectedImages: document.querySelectorAll("#incident-list .quote img").length,
      injectionRan: window.__evidenceInjected === true,
    };
    state.acceptedSequence = 0;
    return result;
  });
  assert(
    revealed.orb === "grounded" &&
      !revealed.suggestionHidden &&
      revealed.decision === "latched" &&
      revealed.recommendation === "Server recommendation, exactly",
    `grounded guidance did not follow detection: ${JSON.stringify(revealed)}`
  );
  assert(
    revealed.caregiverEvidence ===
      'Caregiver said: “I said <img src=x onerror="window.__evidenceInjected=true"> held upright”' &&
      revealed.caregiverEvidenceHtml.includes("&lt;img") &&
      revealed.injectedImages === 0 &&
      !revealed.injectionRan,
    `literal caregiver evidence was not rendered safely: ${JSON.stringify(revealed)}`
  );

  const evidenceLabels = await page.evaluate(() => {
    const base = {
      episode_id: 150,
      started_at: "2026-07-27T20:04:00-04:00",
      interventions: [{ order: 1, action: "Held upright", evidence: "" }],
      outcome: "The baby settled.",
      outcome_src: "caregiver",
      worked: true,
      contributions: [],
      audio_url: "/api/profiles/12/incidents/150/audio",
    };
    const quote = (scenario) => renderIncident(scenario).querySelector(".quote").textContent;
    return {
      typed: quote({
        ...base,
        caregiver_evidence: {
          text: "Held baby upright",
          source: "typed_follow_up",
        },
      }),
      synthetic: quote({
        ...base,
        outcome_src: "seed",
        caregiver_evidence: {
          text: "offered a bottle",
          source: "synthetic_demo",
        },
      }),
      neutral: quote({
        ...base,
        caregiver_evidence: {
          text: "held the baby close",
          source: "caregiver_record",
        },
      }),
      absent: quote(base),
    };
  });
  assert(
    evidenceLabels.typed === 'Caregiver typed: “Held baby upright”' &&
      evidenceLabels.synthetic === 'Synthetic demo evidence: “offered a bottle”' &&
      evidenceLabels.neutral === 'Caregiver note: “held the baby close”' &&
      evidenceLabels.absent === "No caregiver speech recorded",
    `caregiver evidence provenance was mislabeled: ${JSON.stringify(evidenceLabels)}`
  );

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
  assert(
    await page.locator("#suggestion-block").isVisible(),
    "portrait Stop hid the retained suggestion"
  );
  const outcomeAmbient = await ambientMetrics(page);
  assert(
    outcomeAmbient.opacity === "1" &&
      outcomeAmbient.visibility === "visible",
    `Stop did not restore the ambient layer: ${JSON.stringify(outcomeAmbient)}`
  );
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
  const savedAmbient = await ambientMetrics(page);
  assert(
    savedAmbient.opacity === "1" &&
      savedAmbient.visibility === "visible",
    `saved state hid the ambient layer: ${JSON.stringify(savedAmbient)}`
  );
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

async function runAmbientMotionPreference(browser) {
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    reducedMotion: "no-preference",
  });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests);
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  const ambient = await ambientMetrics(page);
  assert(
    ambient.opacity === "1" &&
      ambient.visibility === "visible" &&
      ambient.lineArtCount === 0 &&
      ambient.stickers.length === 4 &&
      ambient.stickers.every((sticker) =>
        sticker.source.includes("/img/action-") &&
        sticker.opacity <= 0.1 &&
        sticker.animationName !== "none" &&
        sticker.animationPlayState === "running"
      ) &&
      new Set(ambient.stickers.map((sticker) => sticker.animationDuration)).size > 1,
    `idle ambient did not float when motion was allowed: ${JSON.stringify(ambient)}`
  );
  await page.evaluate(() => setSessionState("listening"));
  await page.waitForFunction(() => {
    const style = getComputedStyle(document.querySelector("#ambient"));
    return Number(style.opacity) <= 0.01 && style.visibility === "hidden";
  });
  const active = await ambientMetrics(page);
  assert(
    Number(active.opacity) <= 0.01 &&
      active.visibility === "hidden" &&
      active.stickers.every((sticker) => sticker.animationPlayState === "paused"),
    `active recording did not hide and pause ambient motion: ${JSON.stringify(active)}`
  );
  await page.close();
}

async function measureNavbarGeometry(browser, viewport, landscape) {
  const page = await browser.newPage({
    viewport,
    reducedMotion: "reduce",
  });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, { safeArea: true });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  if (landscape) {
    await page.evaluate(() => {
      document.body.dataset.navpeek = "true";
    });
  }
  await page.waitForTimeout(80);
  const metrics = await page.evaluate(() => {
    const rect = (node) => {
      const value = node.getBoundingClientRect();
      return {
        left: +value.left.toFixed(2),
        top: +value.top.toFixed(2),
        right: +value.right.toFixed(2),
        bottom: +value.bottom.toFixed(2),
        width: +value.width.toFixed(2),
        height: +value.height.toFixed(2),
        centerX: +(value.left + value.width / 2).toFixed(2),
        centerY: +(value.top + value.height / 2).toFixed(2),
      };
    };
    const rootStyle = getComputedStyle(document.documentElement);
    const nav = document.querySelector("#tabbar");
    const active = nav.querySelector('[aria-current="page"]');
    const icon = active.querySelector("svg");
    const label = active.querySelector("span");
    const navRect = rect(nav);
    const iconRect = rect(icon);
    const labelRect = rect(label);
    return {
      viewport: { width: innerWidth, height: innerHeight },
      safe: {
        left: parseFloat(rootStyle.getPropertyValue("--sal")) || 0,
        right: parseFloat(rootStyle.getPropertyValue("--sar")) || 0,
        bottom: parseFloat(rootStyle.getPropertyValue("--sab")) || 0,
      },
      nav: navRect,
      transform: getComputedStyle(nav).transform,
      centerError: +(navRect.centerX - innerWidth / 2).toFixed(2),
      icon: iconRect,
      label: labelRect,
      iconCenterOffset: +(iconRect.centerY - labelRect.centerY).toFixed(2),
      links: Array.from(nav.querySelectorAll("a:not([hidden])")).map(rect),
    };
  });
  await page.close();
  return metrics;
}

async function checkResponsiveShell(browser, viewport) {
  const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
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
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    reducedMotion: "reduce",
  });
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
  const page = await browser.newPage({
    viewport: { width: 932, height: 430 },
    reducedMotion: "reduce",
  });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, {
    chunkMode: "no_cry",
    retryFirst: false,
    safeArea: true,
  });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);

  const resetCleanup = await page.evaluate((serverDecision) => {
    latchDecision(serverDecision);
    resetToIdle();
    const result = {
      decisionAfter: state.decision,
      suggestionHidden: document.querySelector("#suggestion-block").hidden,
    };
    return result;
  }, decision);
  assert(
    resetCleanup.decisionAfter === null &&
      resetCleanup.suggestionHidden,
    `reset did not clear the immediate decision: ${JSON.stringify(resetCleanup)}`
  );

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
      const rail = document.querySelector("#suggestion-rail");
      const card = document.querySelector("#suggestion-card").getBoundingClientRect();
      const suggestionRect = suggestion.getBoundingClientRect();
      const railRect = rail.getBoundingClientRect();
      const form = document.querySelector("#outcome-form").getBoundingClientRect();
      const pageRect = pageNode.getBoundingClientRect();
      return {
        suggestionVisible: !suggestion.hidden,
        recommendation: document.querySelector("#g-recommendation").textContent,
        pageWidth: Math.round(pageRect.width),
        suggestionWidth: Math.round(suggestionRect.width),
        railWidth: Math.round(railRect.width),
        cardWidth: Math.round(card.width),
        cardHeight: Math.round(card.height),
        formWidth: Math.round(form.width),
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
        formPageBottom: Math.round(form.bottom - pageRect.top),
        pageScrollHeight: pageNode.scrollHeight,
        railDisplay: getComputedStyle(rail).display,
        cardFlex: getComputedStyle(document.querySelector("#suggestion-card")).flex,
        cardWidthStyle: getComputedStyle(document.querySelector("#suggestion-card")).width,
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

async function portraitRecordingMetrics(page) {
  return page.evaluate(() => {
    const rect = (selector) => {
      const box = document.querySelector(selector).getBoundingClientRect();
      return {
        left: +box.left.toFixed(1),
        top: +box.top.toFixed(1),
        right: +box.right.toFixed(1),
        bottom: +box.bottom.toFixed(1),
        width: +box.width.toFixed(1),
        height: +box.height.toFixed(1),
      };
    };
    const intersects = (left, right) => !(
      left.right <= right.left ||
      left.left >= right.right ||
      left.bottom <= right.top ||
      left.top >= right.bottom
    );
    const page = rect("#page-listen");
    const header = rect("#page-listen .page-head");
    const profile = rect("#profile-control");
    const timer = rect("#rec-chip");
    const orb = rect("#orb-wrap");
    const status = rect("#analysis-status");
    const controls = rect("#ctl-capsule");
    const buttons = Array.from(
      document.querySelectorAll("#ctl-capsule button:not([hidden])")
    ).map((button) => {
      const box = button.getBoundingClientRect();
      return {
        id: button.id,
        width: +box.width.toFixed(1),
        height: +box.height.toFixed(1),
      };
    });
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentScrollHeight: document.documentElement.scrollHeight,
      bodyScrollHeight: document.body.scrollHeight,
      page,
      header,
      profile,
      timer,
      orb,
      status,
      controls,
      buttons,
      timerCenterError: +(
        timer.left + timer.width / 2 - innerWidth / 2
      ).toFixed(1),
      headerTimerOverlap: intersects(header, timer),
      profileTimerOverlap: intersects(profile, timer),
      timerOrbOverlap: intersects(timer, orb),
      timerStatusOverlap: intersects(timer, status),
      orbControlsOverlap: intersects(orb, controls),
      statusControlsOverlap: intersects(status, controls),
    };
  });
}

function assertPortraitRecordingMetrics(metrics, expectedOrbWidth, label) {
  assert(
    metrics.documentScrollHeight <= metrics.viewport.height + 1 &&
      metrics.bodyScrollHeight <= metrics.viewport.height + 1,
    `${label} portrait recording scrolls: ${JSON.stringify(metrics)}`
  );
  assert(
    Math.abs(metrics.header.left - metrics.page.left) <= 0.5 &&
      Math.abs(metrics.header.right - metrics.page.right) <= 0.5 &&
      metrics.profile.left >= metrics.header.left - 0.5 &&
      metrics.profile.right <= metrics.header.right + 0.5,
    `${label} profile header does not own the full top row: ${JSON.stringify(metrics)}`
  );
  assert(
    Math.abs(metrics.timerCenterError) <= 0.5 &&
      metrics.timer.top >= metrics.profile.bottom + 6 &&
      metrics.timer.bottom <= metrics.header.bottom + 0.5 &&
      !metrics.profileTimerOverlap,
    `${label} timer is not centered on its own row below the profile: ${JSON.stringify(metrics)}`
  );
  assert(
    Math.abs(metrics.orb.width - expectedOrbWidth) <= 0.6,
    `${label} changed the portrait orb size: ${JSON.stringify(metrics)}`
  );
  assert(
    !metrics.timerOrbOverlap &&
      !metrics.timerStatusOverlap &&
      !metrics.orbControlsOverlap &&
      !metrics.statusControlsOverlap,
    `${label} portrait recording elements overlap: ${JSON.stringify(metrics)}`
  );
  assert(
    metrics.timer.top >= 0 &&
      metrics.orb.left >= 0 &&
      metrics.orb.right <= metrics.viewport.width &&
      metrics.controls.top >= 0 &&
      metrics.controls.bottom <= metrics.viewport.height,
    `${label} portrait recording element is clipped: ${JSON.stringify(metrics)}`
  );
  assert(
    metrics.buttons.length === 2 &&
      metrics.buttons.every((button) =>
        button.width >= 44 && button.height >= 44
      ),
    `${label} portrait recording controls are below 44px: ${JSON.stringify(metrics)}`
  );
}

async function runPortraitRecordingFit(browser, viewport) {
  const page = await browser.newPage({
    viewport,
    reducedMotion: "reduce",
  });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, { retryFirst: false });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');
  await page.waitForTimeout(80);

  const expectedOrbWidth = viewport.width === 390 ? 273 : 301;
  const listening = await portraitRecordingMetrics(page);
  assertPortraitRecordingMetrics(listening, expectedOrbWidth, "listening");

  await page.evaluate(() => setSessionState("paused"));
  await page.waitForTimeout(80);
  const paused = await portraitRecordingMetrics(page);
  assertPortraitRecordingMetrics(paused, expectedOrbWidth, "paused");

  console.log(
    "portrait recording geometry " +
      JSON.stringify({ viewport, expectedOrbWidth, listening, paused })
  );
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
    const status = document.querySelector("#analysis-status").getBoundingClientRect();
    const intersects = (left, right) => !(
      left.right <= right.left ||
      left.left >= right.right ||
      left.bottom <= right.top ||
      left.top >= right.bottom
    );
    const textOverlapsControls = [];
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT
    );
    while (walker.nextNode()) {
      const textNode = walker.currentNode;
      const text = textNode.textContent.trim();
      const parent = textNode.parentElement;
      if (
        !text ||
        !parent ||
        parent.closest("#ctl-capsule, [hidden], .sr-only")
      ) {
        continue;
      }
      const style = getComputedStyle(parent);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        Number(style.opacity) === 0
      ) {
        continue;
      }
      const range = document.createRange();
      range.selectNodeContents(textNode);
      const rect = range.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0 && intersects(rect, controls)) {
        textOverlapsControls.push({
          text: text.slice(0, 80),
          left: Math.round(rect.left),
          top: Math.round(rect.top),
          right: Math.round(rect.right),
          bottom: Math.round(rect.bottom),
        });
      }
    }
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
      orb: {
        left: +orb.left.toFixed(1),
        top: +orb.top.toFixed(1),
        right: +orb.right.toFixed(1),
        bottom: +orb.bottom.toFixed(1),
        width: +orb.width.toFixed(1),
      },
      status: {
        left: +status.left.toFixed(1),
        top: +status.top.toFixed(1),
        right: +status.right.toFixed(1),
        bottom: +status.bottom.toFixed(1),
      },
      orbOverlapsStatus: intersects(orb, status),
      orbOverlapsControls: intersects(orb, controls),
      textOverlapsControls,
      offenders,
    };
  });
}

async function runLandscapeListeningFit(browser, viewport) {
  const page = await browser.newPage({
    viewport,
    reducedMotion: "reduce",
  });
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
    plain.textOverlapsControls.length === 0,
    `landscape text is behind the recording controls: ${JSON.stringify(plain)}`
  );
  assert(
    Math.abs(plain.profileCenter - plain.recorderCenter) <= 4,
    `landscape timer is not aligned with the baby profile: ${JSON.stringify(plain)}`
  );
  const expectedOrbWidth = viewport.width === 932 ? 279.5 : 253.5;
  assert(
    Math.abs(plain.orb.width - expectedOrbWidth) <= 0.6,
    `landscape listening orb is not the intended larger size: ${JSON.stringify(plain)}`
  );
  assert(
    plain.orb.left >= 0 &&
      plain.orb.top >= 0 &&
      plain.orb.right <= viewport.width &&
      plain.orb.bottom <= viewport.height,
    `landscape listening orb is clipped: ${JSON.stringify(plain)}`
  );
  assert(
    !plain.orbOverlapsStatus && !plain.orbOverlapsControls,
    `landscape listening orb overlaps status or controls: ${JSON.stringify(plain)}`
  );

  await page.evaluate(() => setSessionState("paused"));
  await page.waitForTimeout(80);
  const paused = await landscapeMetrics(page);
  assert(
    Math.abs(paused.orb.width - expectedOrbWidth) <= 0.6 &&
      paused.orb.left >= 0 &&
      paused.orb.top >= 0 &&
      paused.orb.right <= viewport.width &&
      paused.orb.bottom <= viewport.height &&
      !paused.orbOverlapsStatus &&
      !paused.orbOverlapsControls,
    `landscape paused orb does not fit safely: ${JSON.stringify(paused)}`
  );
  console.log(
    "landscape orb geometry " +
      JSON.stringify({ viewport, expectedOrbWidth, listening: plain, paused })
  );
  await page.evaluate(() => setSessionState("listening"));
  await page.evaluate((serverDecision) => {
    window.latchDecision(serverDecision);
  }, decision);
  await page.waitForTimeout(80);
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
  assert(
    latched.textOverlapsControls.length === 0,
    `landscape suggestion text is behind controls: ${JSON.stringify(latched)}`
  );

  const rail = await page.evaluate(() => {
    const node = document.querySelector("#suggestion-rail");
    const cards = Array.from(node.querySelectorAll(".rail-card"))
      .filter((card) => getComputedStyle(card).display !== "none");
    return {
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
      snap: getComputedStyle(node).scrollSnapType,
      cards: cards.length,
      dots: document.querySelectorAll("#rail-dots button").length,
    };
  });
  assert(
    rail.scrollWidth > rail.clientWidth &&
      rail.snap.includes("x") &&
      rail.cards >= 5 &&
      rail.dots === rail.cards,
    `landscape memory rail is incomplete at ${viewport.width}x${viewport.height}: ` +
      JSON.stringify(rail)
  );

  await page.focus("#suggestion-rail");
  await page.keyboard.press("End");
  await page.waitForTimeout(80);
  assert(
    await page.locator("#suggestion-rail").evaluate((node) => node.scrollLeft > 0),
    `keyboard navigation did not move the memory rail at ${viewport.width}x${viewport.height}`
  );

  await page.click("#btn-dismiss-suggestion");
  const dismissed = await page.evaluate(() => ({
    retainedDecision: state.decision && state.decision.id,
    visiblePreference: state.suggestionVisible,
    pageDecision: document.querySelector("#page-listen").dataset.decision,
    suggestionHidden: document.querySelector("#suggestion-block").hidden,
    reopenHidden: document.querySelector("#btn-reopen-suggestion").hidden,
    session: state.session,
    orb: document.querySelector("#orb").dataset.visualState,
  }));
  assert(
    dismissed.retainedDecision === 88 &&
      dismissed.visiblePreference === false &&
      dismissed.pageDecision === "dismissed" &&
      dismissed.suggestionHidden &&
      !dismissed.reopenHidden &&
      dismissed.session === "listening" &&
      dismissed.orb === "listening",
    `dismiss lost the grounded result or stopped listening: ${JSON.stringify(dismissed)}`
  );

  await page.click("#btn-reopen-suggestion");
  const reopened = await page.evaluate(() => ({
    retainedDecision: state.decision && state.decision.id,
    visiblePreference: state.suggestionVisible,
    pageDecision: document.querySelector("#page-listen").dataset.decision,
    suggestionHidden: document.querySelector("#suggestion-block").hidden,
    reopenHidden: document.querySelector("#btn-reopen-suggestion").hidden,
    session: state.session,
  }));
  assert(
    reopened.retainedDecision === 88 &&
      reopened.visiblePreference === true &&
      reopened.pageDecision === "latched" &&
      !reopened.suggestionHidden &&
      reopened.reopenHidden &&
      reopened.session === "listening",
    `reopen did not restore the retained suggestion: ${JSON.stringify(reopened)}`
  );
  await page.close();
}

async function measurePortraitToLandscapeSuggestion(browser, viewport) {
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    reducedMotion: "reduce",
  });
  const requests = { created: [], chunks: [], stopped: 0, completed: [] };
  await installBrowserFakes(page);
  await installRoutes(page, requests, { retryFirst: false, safeArea: true });
  await page.goto("http://care.test/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#btn-start").disabled);
  await page.click("#btn-start");
  await page.waitForSelector('body[data-session="listening"]');

  const expandedDecision = {
    ...decision,
    guidance: {
      ...decision.guidance,
      headline: "A familiar feeding pattern is emerging",
      interpretation:
        "This cry is closest to two earlier evening moments when feeding helped.",
      recommendation:
        "Try the feeding routine that helped in the two closest earlier moments.",
      evidence_summary:
        "The cry signature, time of day, caregiver notes, and earlier outcomes all contributed.",
      support_count: 2,
      incident_ids: [101, 102],
    },
    basis: [
      "The cry signature is closest to two earlier recordings from this baby.",
      "The current time is within the same evening care window.",
      "Both earlier caregiver outcomes recorded that feeding helped.",
    ],
    scenarios: [
      decision.scenarios[0],
      {
        ...decision.scenarios[0],
        episode_id: 102,
        started_at: "2026-07-26T20:18:00-04:00",
        interventions: [
          {
            order: 1,
            action: "Offered a bottle and held upright",
            evidence: "Caregiver said the baby settled after feeding",
          },
        ],
        contributions: [
          "Similar cry signature",
          "Same evening care window",
          "Previously recorded as helpful",
        ],
        audio_url: "/api/profiles/12/incidents/102/audio",
      },
    ],
  };
  await page.evaluate((serverDecision) => {
    window.latchDecision(serverDecision);
  }, expandedDecision);
  await page.setViewportSize(viewport);
  await page.waitForTimeout(120);

  const layout = await page.evaluate(() => {
    const rect = (selector) => {
      const box = document.querySelector(selector).getBoundingClientRect();
      return {
        top: Math.round(box.top),
        right: Math.round(box.right),
        bottom: Math.round(box.bottom),
        left: Math.round(box.left),
        width: Math.round(box.width),
        height: Math.round(box.height),
      };
    };
    const rail = document.querySelector("#suggestion-rail");
    return {
      viewport: { width: innerWidth, height: innerHeight },
      shell: rect("#app-shell"),
      page: rect("#page-listen"),
      suggestion: rect("#suggestion-block"),
      rail: rect("#suggestion-rail"),
      documentScrollHeight: document.documentElement.scrollHeight,
      bodyScrollHeight: document.body.scrollHeight,
      pageClientHeight: document.querySelector("#page-listen").clientHeight,
      pageScrollHeight: document.querySelector("#page-listen").scrollHeight,
      railClientWidth: rail.clientWidth,
      railScrollWidth: rail.scrollWidth,
      railSnap: getComputedStyle(rail).scrollSnapType,
      visibleCards: Array.from(rail.querySelectorAll(".rail-card"))
        .filter((card) => getComputedStyle(card).display !== "none").length,
    };
  });

  await page.click("#btn-dismiss-suggestion");
  const dismissed = await page.evaluate(() => {
    const button = document.querySelector("#btn-reopen-suggestion");
    const capsule = document.querySelector("#ctl-capsule");
    const buttonRect = button.getBoundingClientRect();
    const capsuleRect = capsule.getBoundingClientRect();
    const center = {
      x: buttonRect.left + buttonRect.width / 2,
      y: buttonRect.top + buttonRect.height / 2,
    };
    const hit = document.elementFromPoint(center.x, center.y);
    const overlap = !(
      buttonRect.right <= capsuleRect.left ||
      buttonRect.left >= capsuleRect.right ||
      buttonRect.bottom <= capsuleRect.top ||
      buttonRect.top >= capsuleRect.bottom
    );
    return {
      button: {
        left: Math.round(buttonRect.left),
        top: Math.round(buttonRect.top),
        right: Math.round(buttonRect.right),
        bottom: Math.round(buttonRect.bottom),
      },
      capsule: {
        left: Math.round(capsuleRect.left),
        top: Math.round(capsuleRect.top),
        right: Math.round(capsuleRect.right),
        bottom: Math.round(capsuleRect.bottom),
      },
      overlap,
      hitId: hit && hit.closest("button") ? hit.closest("button").id : "",
    };
  });
  let reopened = false;
  if (dismissed.hitId === "btn-reopen-suggestion") {
    const x = (dismissed.button.left + dismissed.button.right) / 2;
    const y = (dismissed.button.top + dismissed.button.bottom) / 2;
    await page.mouse.click(x, y);
    reopened = await page.evaluate(() =>
      document.querySelector("#page-listen").dataset.decision === "latched" &&
      !document.querySelector("#suggestion-block").hidden
    );
  }
  await page.close();
  return { viewport, layout, dismissed, reopened };
}

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  await runLivePath(browser);
  await runAmbientMotionPreference(browser);
  await runNoCryPath(browser);
  await runSequentialOutcomePath(browser);
  const navbarMeasurements = [
    await measureNavbarGeometry(browser, { width: 932, height: 430 }, true),
    await measureNavbarGeometry(browser, { width: 844, height: 390 }, true),
  ];
  const portraitNavbar = await measureNavbarGeometry(
    browser,
    { width: 430, height: 932 },
    false
  );
  const navbarFailures = [];
  for (const metrics of navbarMeasurements) {
    const label = `${metrics.viewport.width}x${metrics.viewport.height}`;
    const touchTargetsValid = metrics.links.every(
      (rect) => rect.width >= 44 && rect.height >= 44
    );
    const insideSafeArea =
      metrics.nav.left >= metrics.safe.left - 0.5 &&
      metrics.nav.right <= metrics.viewport.width - metrics.safe.right + 0.5 &&
      metrics.viewport.height - metrics.nav.bottom >= metrics.safe.bottom;
    if (Math.abs(metrics.centerError) > 0.5) {
      navbarFailures.push(`${label} navbar is not horizontally centered`);
    }
    if (
      metrics.iconCenterOffset < -1.25 ||
      metrics.iconCenterOffset > -0.75
    ) {
      navbarFailures.push(`${label} active icon is not optically lifted by 1px`);
    }
    if (!touchTargetsValid || !insideSafeArea) {
      navbarFailures.push(`${label} navbar violates touch or safe-area bounds`);
    }
  }
  if (
    Math.abs(portraitNavbar.centerError) > 0.5 ||
    Math.abs(portraitNavbar.iconCenterOffset) > 0.25 ||
    portraitNavbar.links.some((rect) => rect.width < 44 || rect.height < 44)
  ) {
    navbarFailures.push("portrait navbar geometry changed");
  }
  assert(
    navbarFailures.length === 0,
    `${navbarFailures.join("; ")}: ${JSON.stringify({
      landscape: navbarMeasurements,
      portrait: portraitNavbar,
    })}`
  );
  console.log(
    "navbar geometry " +
      JSON.stringify({ landscape: navbarMeasurements, portrait: portraitNavbar })
  );
  await runPortraitRecordingFit(browser, { width: 390, height: 844 });
  await runPortraitRecordingFit(browser, { width: 430, height: 932 });
  await runLandscapeListeningFit(browser, { width: 932, height: 430 });
  await runLandscapeListeningFit(browser, { width: 844, height: 390 });
  const rotatedResults = [];
  rotatedResults.push(
    await measurePortraitToLandscapeSuggestion(browser, { width: 932, height: 430 })
  );
  rotatedResults.push(
    await measurePortraitToLandscapeSuggestion(browser, { width: 844, height: 390 })
  );
  const rotationFailures = [];
  for (const result of rotatedResults) {
    const { layout, dismissed, reopened, viewport } = result;
    const label = `${viewport.width}x${viewport.height}`;
    if (
      layout.shell.bottom > viewport.height + 1 ||
      layout.page.bottom > viewport.height + 1 ||
      layout.suggestion.bottom > viewport.height + 1 ||
      layout.rail.bottom > viewport.height + 1 ||
      layout.documentScrollHeight > viewport.height + 1 ||
      layout.bodyScrollHeight > viewport.height + 1 ||
      layout.pageScrollHeight > layout.pageClientHeight + 1
    ) {
      rotationFailures.push(`${label} clips the rotated suggestion`);
    }
    if (
      layout.railScrollWidth <= layout.railClientWidth ||
      !layout.railSnap.includes("x") ||
      layout.visibleCards < 6
    ) {
      rotationFailures.push(`${label} does not expose the full horizontal memory rail`);
    }
    if (
      dismissed.overlap ||
      dismissed.hitId !== "btn-reopen-suggestion" ||
      dismissed.button.top < 0 ||
      dismissed.button.bottom > viewport.height ||
      !reopened
    ) {
      rotationFailures.push(`${label} does not expose a unique tappable suggestion control`);
    }
  }
  assert(
    rotationFailures.length === 0,
    `${rotationFailures.join("; ")}: ${JSON.stringify(rotatedResults)}`
  );
  await checkResponsiveShell(browser, { width: 932, height: 430 });
  await checkResponsiveShell(browser, { width: 1440, height: 900 });
  console.log("continuous care browser checks passed");
} finally {
  await browser.close();
}
