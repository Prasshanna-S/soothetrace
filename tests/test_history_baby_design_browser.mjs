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

async function activate(page, selector) {
  await page.locator(selector).evaluate((node) => node.click());
}

const profiles = [
  {
    id: 21,
    display_name: "Server Baby",
    kind: "infant",
    status: "provisional",
    enrollments: 2,
  },
  {
    id: 22,
    display_name: "Empty Baby",
    kind: "infant",
    status: "ready",
    enrollments: 2,
  },
  {
    id: 23,
    display_name: "Unavailable Baby",
    kind: "infant",
    status: "ready",
    enrollments: 2,
  },
];

const unsafeCapturedSpeech =
  'I picked the baby up <img src=x ' +
  'onerror="window.__speechInjected=true">.';
const typedFollowUp = "Action: Held baby upright. Settled: yes.";
const unsafeSpeech =
  "Audio transcript: " + unsafeCapturedSpeech + "\n" +
  "Typed caregiver follow-up: " + typedFollowUp;
const unsafeEvidence =
  '<svg onload="window.__evidenceInjected=true">unsafe</svg> held upright';

function activeHistoryIncident({
  id,
  action,
  startedAt,
  outcome,
  outcomeSource,
  worked,
  transcriptExcerpt,
  audioUrl,
}) {
  const actions = [
    {
      action,
      evidence: unsafeEvidence,
      worked,
    },
  ];
  return {
    id,
    started_at: startedAt,
    duration_s: 12,
    time: { hour_local: 20 },
    tags: ["evening", "at home"],
    interventions: actions,
    actions,
    outcome,
    outcome_source: outcomeSource,
    worked,
    transcript_excerpt: transcriptExcerpt,
    audio_url: audioUrl,
    context: {
      hour_local: 20,
      tags: ["evening", "at home"],
    },
    audio: audioUrl ? { url: audioUrl } : null,
  };
}

const firstIncident = activeHistoryIncident({
  id: 301,
  action: "Held baby upright",
  startedAt: "2026-07-30T20:16:00-04:00",
  outcome: "The baby settled.",
  outcomeSource: "caregiver",
  worked: true,
  transcriptExcerpt: unsafeSpeech.slice(0, 220),
  audioUrl: "/api/profiles/21/incidents/301/audio",
});
const secondIncident = activeHistoryIncident({
  id: 302,
  action: "White noise",
  startedAt: "2026-07-29T19:52:00-04:00",
  outcome: "Whether the baby settled was not recorded.",
  outcomeSource: "seed",
  worked: null,
  transcriptExcerpt: "",
  audioUrl: null,
});

function activeIncidentDetail(summary, transcript) {
  return {
    ...summary,
    transcript,
    speech: {
      segments: transcript
        ? [
            {
              text: unsafeCapturedSpeech,
              source: "captured_transcript",
              label: "Caregiver speech transcript",
            },
            {
              text: typedFollowUp,
              source: "typed_follow_up",
              label: "Caregiver typed",
            },
          ]
        : [],
    },
    supporting_incident_ids: [],
    caregiver_notes: null,
  };
}

const profileSummary = {
  profile: {
    id: 21,
    display_name: "Server Baby",
    kind: "infant",
    status: "provisional",
    enrollment_count: 2,
    enrollments: [
      {
        id: 501,
        captured_at: "2026-07-30T18:02:00-04:00",
        duration_s: 7.1,
        playback_url: "/api/audio/enrollments/501",
      },
      {
        id: 502,
        captured_at: "2026-07-30T18:04:00-04:00",
        duration_s: 6.4,
        playback_url: "/api/audio/enrollments/502",
      },
    ],
    memory_count: 4,
    latest_memory_at: "2026-07-30T20:16:00-04:00",
    available_context: [
      "acoustic_pattern",
      "time_of_day",
      "caregiver_tags",
      "previous_outcomes",
    ],
  },
  training_clips: [
    {
      id: 501,
      captured_at: "2026-07-30T18:02:00-04:00",
      duration_s: 7.1,
      playback_url: "/api/audio/enrollments/501",
    },
    {
      id: 502,
      captured_at: "2026-07-30T18:04:00-04:00",
      duration_s: 6.4,
      playback_url: "/api/audio/enrollments/502",
    },
  ],
};

const assets = {
  "/": ["text/html", "index.html"],
  "/app.css": ["text/css", "app.css"],
  "/app.js": ["text/javascript", "app.js"],
  "/manifest.webmanifest": ["application/manifest+json", "manifest.webmanifest"],
};

let releaseFirstHistory;
let firstHistoryStarted;
const firstHistoryGate = new Promise((resolve) => {
  releaseFirstHistory = resolve;
});
const firstHistoryRequest = new Promise((resolve) => {
  firstHistoryStarted = resolve;
});
let holdFirstHistory = true;
const requestedProfileIds = [];

const { chromium } = loadPlaywright();
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 932, height: 430 },
    reducedMotion: "reduce",
  });
  const pageErrors = [];
  page.on("pageerror", (error) => {
    pageErrors.push(error && error.message ? error.message : String(error));
  });

  await page.addInitScript(() => {
    window.__speechInjected = false;
    window.__evidenceInjected = false;
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
      requestedProfileIds.push(profileId);
      if (profileId === 21 && holdFirstHistory) {
        holdFirstHistory = false;
        firstHistoryStarted();
        await firstHistoryGate;
      }
      if (profileId === 23) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ reason: "history_unavailable" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          profile: profiles.find((profile) => profile.id === profileId),
          incidents: profileId === 21 ? [firstIncident, secondIncident] : [],
          next_before_id: null,
          next_cursor: null,
        }),
      });
      return;
    }

    const detailMatch = url.pathname.match(
      /^\/api\/profiles\/(\d+)\/incidents\/(\d+)$/
    );
    if (detailMatch && request.method() === "GET") {
      const profileId = Number(detailMatch[1]);
      const incidentId = Number(detailMatch[2]);
      requestedProfileIds.push(profileId);
      const summary = incidentId === 301 ? firstIncident : secondIncident;
      const transcript = incidentId === 301 ? unsafeSpeech : "";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ready",
          profile: {
            id: profileId,
            display_name: "Server Baby",
          },
          incident: activeIncidentDetail(summary, transcript),
        }),
      });
      return;
    }

    const profileMatch = url.pathname.match(/^\/api\/profiles\/(\d+)$/);
    if (profileMatch && request.method() === "GET") {
      const profileId = Number(profileMatch[1]);
      requestedProfileIds.push(profileId);
      if (profileId !== 21) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            profile: profiles.find((profile) => profile.id === profileId),
            training_clips: [],
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(profileSummary),
      });
      return;
    }

    if (
      url.pathname.startsWith("/api/profiles/21/incidents/") ||
      url.pathname.startsWith("/api/audio/enrollments/")
    ) {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ reason: "audio_not_loaded_in_contract_test" }),
      });
      return;
    }

    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.goto("http://history-baby-design.test/", {
    waitUntil: "domcontentloaded",
  });
  try {
    await page.waitForFunction(
      () => document.querySelector("#profile-picker")?.options.length === 4,
      null,
      { timeout: 5000 }
    );
  } catch (error) {
    const bootState = await page.evaluate(() => ({
      options: Array.from(
        document.querySelectorAll("#profile-picker option"),
        (option) => option.textContent
      ),
      bodyState: document.body.dataset.state,
    }));
    const manualProfiles = await page.evaluate(async () => {
      try {
        const response = await fetch("/api/profiles");
        return {
          ok: response.ok,
          status: response.status,
          text: await response.text(),
        };
      } catch (fetchError) {
        return { error: String(fetchError) };
      }
    });
    throw new Error(
      `App did not load the mocked profiles: ${JSON.stringify({
        bootState,
        manualProfiles,
        pageErrors,
      })}`
    );
  }
  await page.selectOption("#profile-picker", "21");

  await activate(page, "#tab-history");
  await firstHistoryRequest;
  const loadingState = await page.evaluate(() => ({
    state: document.querySelector("#page-history")?.dataset.state,
    loadingVisible: Boolean(
      document.querySelector("#history-loading") &&
      !document.querySelector("#history-loading").hidden
    ),
    listVisible: Boolean(
      document.querySelector("#history-list") &&
      !document.querySelector("#history-list").hidden
    ),
  }));
  releaseFirstHistory();
  assert(
    loadingState.state === "loading" &&
      loadingState.loadingVisible &&
      !loadingState.listVisible,
    `History loading state is not the designed state: ${JSON.stringify(loadingState)}`
  );

  await page.waitForFunction(
    () => document.querySelector("#page-history")?.dataset.state === "ready"
  );
  let historyRows = await page.locator("#history-list > li").allTextContents();
  assert(
    historyRows.length === 2 &&
      historyRows[0].includes("Held baby upright") &&
      historyRows[0].includes("The baby settled.") &&
      historyRows[1].includes("White noise") &&
      historyRows[1].includes("Synthetic demo memory"),
    `History did not render the real active API shape: ${JSON.stringify(historyRows)}`
  );

  await activate(page, "#tab-listen");
  await page.selectOption("#profile-picker", "22");
  await activate(page, "#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#page-history")?.dataset.state === "empty"
  );
  assert(
    await page.locator("#history-empty").isVisible(),
    "History empty state is not visible"
  );

  await activate(page, "#tab-listen");
  await page.selectOption("#profile-picker", "23");
  await activate(page, "#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#page-history")?.dataset.state === "error"
  );
  assert(
    await page.locator("#history-error").isVisible(),
    "History error state is not visible"
  );

  await activate(page, "#tab-listen");
  await page.selectOption("#profile-picker", "21");
  await activate(page, "#tab-history");
  await page.waitForFunction(
    () => document.querySelector("#page-history")?.dataset.state === "ready"
  );
  await page.locator("#history-list > li").filter({
    hasText: "Held baby upright",
  }).click();
  await page.waitForFunction(
    () => {
      const detail = document.querySelector("#history-detail");
      return detail && !detail.hidden;
    }
  );

  const tabNames = await page.locator(
    "#history-detail-tabs button[data-tab]"
  ).allTextContents();
  assert(
    JSON.stringify(tabNames.map((value) => value.trim())) ===
      JSON.stringify(["Overview", "Said", "Context", "Evidence"]),
    `Incident tabs are incomplete: ${JSON.stringify(tabNames)}`
  );
  const overviewText = await page.locator("#history-detail-overview").innerText();
  assert(
    overviewText.includes("Held baby upright") &&
      overviewText.includes("The baby settled.") &&
      await page.locator("#history-detail-overview audio").count() === 1 &&
      await page.locator("#history-detail-overview audio").getAttribute("src") ===
        "/api/profiles/21/incidents/301/audio",
    "Incident Overview did not adapt the active outcome or audio shape"
  );

  await page.click('#history-detail-tabs button[data-tab="said"]');
  const saidText = await page.locator("#history-detail-said").innerText();
  const saidInjection = await page.evaluate(() => ({
    ran: window.__speechInjected,
    injectedNodes: document.querySelectorAll(
      "#history-detail-said img, #history-detail-said script"
    ).length,
  }));
  assert(
    saidText.includes("<img src=x") &&
      saidText.includes("Captured transcript") &&
      saidText.includes("Caregiver typed") &&
      !saidText.toLowerCase().includes("caregiver speech") &&
      !saidInjection.ran &&
      saidInjection.injectedNodes === 0,
    `Stored transcript was unsafe or mislabeled as caregiver speech: ` +
      JSON.stringify({ saidText, saidInjection })
  );

  await page.click('#history-detail-tabs button[data-tab="context"]');
  const contextText = await page.locator("#history-detail-context").innerText();
  assert(
    contextText.includes("evening") &&
      contextText.includes("at home") &&
      contextText.includes("20"),
    `Incident Context omitted real server fields: ${contextText}`
  );

  await page.click('#history-detail-tabs button[data-tab="evidence"]');
  const evidenceText = await page.locator("#history-detail-evidence").innerText();
  const evidenceInjection = await page.evaluate(() => ({
    ran: window.__evidenceInjected,
    injectedNodes: document.querySelectorAll(
      "#history-detail-evidence svg, #history-detail-evidence script"
    ).length,
  }));
  assert(
    evidenceText.includes("<svg onload=") &&
      !evidenceText.toLowerCase().includes("caregiver said") &&
      !evidenceText.toLowerCase().includes("heard in the recording") &&
      !evidenceInjection.ran &&
      evidenceInjection.injectedNodes === 0,
    `Literal evidence was unsafe or given invented provenance: ` +
      JSON.stringify({ evidenceText, evidenceInjection })
  );

  await page.click("#history-detail-close");
  assert(
    await page.locator("#page-history").isVisible() &&
      await page.locator("#history-list > li").count() === 2,
    "Closing incident detail did not restore the existing History list"
  );

  await page.locator("#history-list > li").filter({
    hasText: "White noise",
  }).click();
  await page.waitForFunction(
    () => {
      const detail = document.querySelector("#history-detail");
      return detail && !detail.hidden;
    }
  );
  assert(
    await page.locator("#history-detail-overview audio").count() === 0,
    "Incident audio appeared even though the server supplied no URL"
  );
  await page.click("#history-detail-close");

  await activate(page, "#tab-listen");
  await page.selectOption("#profile-picker", "21");
  await activate(page, "#tab-baby");
  await page.waitForFunction(
    () => document.querySelector("#page-baby")?.dataset.state === "ready"
  );
  const babyView = await page.evaluate(() => {
    const text = document.querySelector("#page-baby")?.innerText || "";
    return {
      text,
      title: document.querySelector("#baby-title")?.textContent,
      status: document.querySelector("#baby-profile-status")?.textContent,
      memoryCount: document.querySelector("#baby-memory-count")?.textContent,
      trainingRows: document.querySelectorAll("#baby-training > li").length,
      careTiles: document.querySelectorAll(".care-tile, [data-care-event]").length,
    };
  });
  const normalizedBabyText = babyView.text.toLowerCase();
  assert(
    babyView.title === "Server Baby" &&
      babyView.status === "provisional" &&
      babyView.memoryCount === "Memories: 4" &&
      babyView.trainingRows === 2,
    `Baby page did not use real server profile and training data: ` +
      JSON.stringify(babyView)
  );
  assert(
    /(cry acoustics|acoustic(?:_|\s)+pattern)/i.test(babyView.text) &&
      /time(?:_|\s)+of(?:_|\s)+day/i.test(babyView.text) &&
      /caregiver(?:_|\s)+tags/i.test(babyView.text),
    `Baby page omitted available server context: ${babyView.text}`
  );
  assert(
    babyView.careTiles === 0 &&
      !normalizedBabyText.includes("held baby upright") &&
      !normalizedBabyText.includes("white noise") &&
      !normalizedBabyText.includes("ready for recall") &&
      !normalizedBabyText.includes("recall unlocks at") &&
      !normalizedBabyText.includes("six saved"),
    `Baby page fabricated care events or a fixed readiness claim: ` +
      JSON.stringify(babyView)
  );
  assert(
    requestedProfileIds.every((profileId) => [21, 22, 23].includes(profileId)) &&
      !requestedProfileIds.includes(12),
    `The selected profile contract fell back to a fixed profile: ` +
      JSON.stringify(requestedProfileIds)
  );

  console.log("History and Baby design browser contract passed");
} finally {
  releaseFirstHistory();
  await browser.close();
}
