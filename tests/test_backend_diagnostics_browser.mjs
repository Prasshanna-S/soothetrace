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
  "/backend.html": ["text/html", "backend.html"],
  "/backend.css": ["text/css", "backend.css"],
  "/backend.js": ["text/javascript", "backend.js"],
};

function progressPayload() {
  return {
    status: "active",
    server_time: "2026-07-30T22:14:07-04:00",
    segment_target_seconds: 3,
    session: {
      id: 42,
      state: "listening",
      started_at: "2026-07-30T22:13:48-04:00",
      last_sequence: 6,
      profile: { id: 1, display_name: "Demo Baby" },
      context: {
        local_time: "10:14 PM",
        time_of_day: "night",
        tags: ["before-feed"],
        factors: [
          { label: "Cry pattern", value: "Infant cry gate passed" },
          { label: "Time", value: "Night at 10:14 PM" },
          { label: "Care tags", value: "before-feed" },
          { label: "Recorded memory", value: "A prior incident is being confirmed" },
        ],
      },
      latest_segment: {
        sequence: 6,
        created_at: "2026-07-30T22:14:06-04:00",
        duration_seconds: 3,
        status: "matched_no_guidance",
        ingest: {
          state: "decoded",
          quality: "usable",
          detail: "Decoded into analysis-ready audio.",
        },
        cry_gate: {
          state: "pass",
          label: "Infant cry detected",
          detail: "The cry gate passed this segment.",
        },
        identity: {
          state: "selected_profile",
          label: "Selected profile comparison complete",
          detail: "The comparison opened Demo Baby's recorded memory.",
        },
        memory: {
          state: "grounded",
          label: "Prior memory found",
          detail: "A prior action is being confirmed.",
        },
        guidance: {
          state: "waiting",
          label: "No suggestion yet",
          detail: "The monitor is still confirming the pattern.",
        },
        decision_progress: {
          consistent_grounded_segments: 4,
          required_consistent_grounded_segments: 6,
          additional_confirmations: 3,
          required_additional_confirmations: 5,
          segments_seen: 6,
          minimum_segments_before_decision: 7,
          analyzed_audio_seconds: 18,
          minimum_analyzed_audio_seconds: 20,
          decision_eligible: false,
          label: "98% confidence from /private/segment.wav",
        },
      },
      decision: null,
      evidence: [],
      events: [],
    },
  };
}

function suggestionPayload() {
  const payload = structuredClone(progressPayload());
  payload.server_time = "2026-07-30T22:14:10-04:00";
  payload.session.last_sequence = 7;
  payload.session.latest_segment.sequence = 7;
  payload.session.latest_segment.created_at = "2026-07-30T22:14:09-04:00";
  payload.session.latest_segment.status = "guidance_ready";
  payload.session.latest_segment.guidance = {
    state: "grounded",
    label: "Suggestion ready",
    detail: "A grounded prior action is ready.",
  };
  payload.session.latest_segment.decision_progress = {
    consistent_grounded_segments: 6,
    required_consistent_grounded_segments: 6,
    additional_confirmations: 5,
    required_additional_confirmations: 5,
    segments_seen: 7,
    minimum_segments_before_decision: 7,
    analyzed_audio_seconds: 21,
    minimum_analyzed_audio_seconds: 20,
    decision_eligible: true,
  };
  payload.session.decision_progress =
    payload.session.latest_segment.decision_progress;
  payload.session.decision = {
    latched_at: "2026-07-30T22:14:09-04:00",
    guidance: {
      status: "grounded",
      headline: "What helped before",
      recommendation: "Try holding the baby upright.",
      interpretation: "This resembles a previous late-evening pattern.",
      pattern: "Night, before a feed",
      evidence_summary: "Supported by a similar recorded incident.",
    },
  };
  payload.session.evidence = [
    {
      incident_id: 7,
      recorded_at: "2026-07-28T22:02:00-04:00",
      interventions: [
        {
          order: 1,
          action: "Held upright",
          evidence: "Caregiver follow-up",
        },
      ],
      outcome: "Settled after a few minutes",
      contributions: [
        "similar cry pattern",
        "same time of day",
        "before-feed context",
      ],
    },
  ];
  return payload;
}

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (assets[url.pathname]) {
      const [contentType, name] = assets[url.pathname];
      await route.fulfill({
        status: 200,
        contentType,
        body: fs.readFileSync(path.join(repoRoot, "web", name)),
      });
      return;
    }
    if (url.pathname === "/api/demo-diagnostics") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(progressPayload()),
      });
      return;
    }
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://backend-monitor.test/backend.html", {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(
    () => document.body.dataset.connected === "true"
  );

  const initial = await page.evaluate(() => ({
    connection: document.querySelector("#connection-copy")?.textContent,
    session: document.querySelector("#session-value")?.textContent,
    profile: document.querySelector("#profile-value")?.textContent,
    state: document.querySelector("#current-state")?.textContent,
    detail: document.querySelector("#current-detail")?.textContent,
    headers: [...document.querySelectorAll("#segment-table th")]
      .map((node) => node.textContent.trim()),
    rows: [...document.querySelectorAll("#segment-rows tr")]
      .map((row) => row.innerText),
    ornateElements: document.querySelectorAll(
      ".scanline, .brand-mark, .signal-rail, .flow-panel"
    ).length,
    body: document.body.innerText,
  }));
  assert(
    initial.connection === "Connected" &&
      initial.session === "#42" &&
      initial.profile === "Demo Baby",
    `compact header is incomplete: ${JSON.stringify(initial)}`
  );
  assert(
    initial.state === "Infant cry detected" &&
      initial.detail.includes("18/20 s") &&
      initial.detail.includes("4/6 consistent"),
    `current cry state is not immediately visible: ${JSON.stringify(initial)}`
  );
  assert(
    JSON.stringify(initial.headers) === JSON.stringify([
      "Segment",
      "Received",
      "Cry gate",
      "Baby match",
      "Confirmations",
      "Result",
    ]),
    `live table headers are wrong: ${JSON.stringify(initial)}`
  );
  assert(
    initial.rows.length === 1 &&
      initial.rows[0].includes("SEG 006") &&
      initial.rows[0].includes("3.00 s") &&
      initial.rows[0].includes("Infant cry detected") &&
      initial.rows[0].includes("Selected profile comparison complete") &&
      initial.rows[0].includes("18/20 s") &&
      initial.rows[0].includes("6/7 segments") &&
      initial.rows[0].includes("Listening"),
    `first completed segment was not appended cleanly: ${JSON.stringify(initial)}`
  );
  assert(
    initial.ornateElements === 0 &&
      !initial.body.includes("Six-second") &&
      !initial.body.includes("6-second") &&
      !initial.body.includes("98% confidence") &&
      !initial.body.includes("/private/segment.wav"),
    `the monitor remained ornate or leaked diagnostics: ${JSON.stringify(initial)}`
  );

  const deduplicated = await page.evaluate((payload) => {
    render(payload);
    return document.querySelectorAll("#segment-rows tr").length;
  }, progressPayload());
  assert(
    deduplicated === 1,
    `polling duplicated the same completed segment: ${deduplicated}`
  );

  const malformed = await page.evaluate((payload) => {
    payload.session.latest_segment.sequence = 7;
    payload.session.latest_segment.decision_progress = {
      consistent_grounded_segments: "4",
      required_consistent_grounded_segments: 6,
      segments_seen: 7,
      minimum_segments_before_decision: 7,
      analyzed_audio_seconds: null,
      minimum_analyzed_audio_seconds: 20,
      decision_eligible: true,
      score: 0.99,
      raw_detector: "private",
    };
    render(payload);
    return {
      rowCount: document.querySelectorAll("#segment-rows tr").length,
      detail: document.querySelector("#current-detail").textContent,
      latestRow: document.querySelector("#segment-rows tr:last-child").innerText,
      body: document.body.innerText,
    };
  }, progressPayload());
  assert(
    malformed.rowCount === 2 &&
      malformed.detail.includes("Waiting for safe confirmation progress") &&
      malformed.latestRow.includes("Waiting for safe confirmation progress") &&
      !malformed.body.includes("0.99") &&
      !malformed.body.includes("raw_detector"),
    `malformed progress did not fail closed: ${JSON.stringify(malformed)}`
  );

  const suggestion = await page.evaluate((payload) => {
    render(payload);
    return {
      rowCount: document.querySelectorAll("#segment-rows tr").length,
      latestRow: document.querySelector("#segment-rows tr:last-child").innerText,
      hidden: document.querySelector("#suggestion-panel").hidden,
      recommendation: document.querySelector("#suggestion-recommendation").textContent,
      evidence: document.querySelector("#evidence-list").innerText,
      body: document.body.innerText,
    };
  }, suggestionPayload());
  assert(
    suggestion.rowCount === 2 &&
      suggestion.latestRow.includes("Suggestion ready") &&
      suggestion.hidden === false &&
      suggestion.recommendation === "Try holding the baby upright.",
    `grounded suggestion did not update the existing segment row: ${JSON.stringify(suggestion)}`
  );
  for (const copy of [
    "Top prior incident",
    "Held upright",
    "10:02 PM",
    "Settled after a few minutes",
    "Caregiver follow-up",
    "similar cry pattern",
  ]) {
    assert(
      suggestion.evidence.includes(copy),
      `minimal evidence omitted ${copy}: ${JSON.stringify(suggestion)}`
    );
  }
  assert(
    !suggestion.body.toLowerCase().includes("confidence") &&
      !suggestion.body.toLowerCase().includes("score") &&
      !suggestion.evidence.includes("#7"),
    `suggestion view exposed prohibited diagnostic claims: ${JSON.stringify(suggestion)}`
  );

  const learning = await page.evaluate((payload) => {
    payload.session.id = 43;
    payload.session.profile = { id: 2, display_name: "Learning Baby" };
    delete payload.session.decision_progress;
    delete payload.session.latest_segment.decision_progress;
    render(payload);
    return {
      rows: document.querySelectorAll("#segment-rows tr").length,
      recommendation: document.querySelector("#suggestion-recommendation").textContent,
      body: document.body.innerText,
    };
  }, suggestionPayload());
  assert(
    learning.rows === 1 &&
      learning.recommendation === "Try holding the baby upright." &&
      !learning.body.includes("20/20 s") &&
      !learning.body.includes("7/7 segments"),
    `session reset or profile-specific behavior is wrong: ${JSON.stringify(learning)}`
  );

  for (const viewport of [
    { width: 1024, height: 720 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    const layout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      tableViewport: document.querySelector(".table-scroll").clientWidth,
      tableWidth: document.querySelector("#segment-table").scrollWidth,
    }));
    assert(
      layout.documentWidth <= layout.viewport &&
        layout.tableWidth > layout.tableViewport,
      `the table did not stay inside its responsive scroll region: ${JSON.stringify(layout)}`
    );
  }

  console.log("backend diagnostics browser contract passed");
} finally {
  await browser.close();
}
