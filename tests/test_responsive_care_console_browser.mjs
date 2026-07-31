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
    actions: [{ action: "Held baby upright after the evening feeding" }],
    outcome: "The baby settled after a few calm minutes.",
    outcome_source: "caregiver",
    worked: true,
    context: { tags: ["evening", "at home", "after feeding"] },
  },
  {
    id: 302,
    started_at: "2026-07-29T03:04:00-04:00",
    duration_s: 9,
    actions: [{ action: "White noise near the bedside" }],
    outcome: "Whether the baby settled was not recorded.",
    outcome_source: "seed",
    worked: null,
    context: { tags: ["overnight", "white-noise trial"] },
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
          training_clips: [
            {
              captured_at: "2026-07-30T20:06:00-04:00",
              duration_s: 15,
              playback_url: "/audio/training-1.wav",
            },
            {
              captured_at: "2026-07-30T20:05:00-04:00",
              duration_s: 15,
              playback_url: "/audio/training-2.wav",
            },
            {
              captured_at: "2026-07-30T20:04:00-04:00",
              duration_s: 15,
              playback_url: "/audio/training-3.wav",
            },
          ],
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
      profileAlignment: (() => {
        const artwork = document.querySelector("#profile-control .avatar img")
          .getBoundingClientRect();
        const text = document.querySelector("#profile-picker").getBoundingClientRect();
        return {
          artworkCenter: artwork.top + artwork.height / 2,
          textCenter: text.top + text.height / 2,
        };
      })(),
      lineArtCount: document.querySelectorAll("#ambient .am").length,
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
    portrait.lineArtCount === 0 &&
      portrait.stickerStyles.length === 4 &&
      portrait.stickerStyles.every((item) =>
        item.opacity <= 0.04 && item.animationName !== "none"
      ) &&
      new Set(portrait.stickerStyles.map((item) => item.animationDuration)).size > 1,
    `idle background still has line art or strong stickers: ${JSON.stringify(portrait)}`
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

  await page.evaluate(() => { location.hash = "history"; });
  await page.waitForFunction(() =>
    document.querySelectorAll("#history-list .record-card").length === 2
  );
  const portraitHistory = await page.evaluate(() => {
    const list = document.querySelector("#history-list").getBoundingClientRect();
    const cards = Array.from(document.querySelectorAll("#history-list .record-card"));
    const clipped = Array.from(document.querySelectorAll(
      "#history-list .record-copy, #history-list .record-meta, " +
      "#history-list .record-action, #history-list .record-outcome, " +
      "#history-list .badge, #history-list .record-tags"
    )).filter((node) => node.scrollWidth > node.clientWidth + 1)
      .map((node) => ({
        className: node.className,
        text: node.textContent,
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
      }));
    return {
      list: { left: list.left, right: list.right, width: list.width },
      cards: cards.map((node) => {
        const rect = node.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      }),
      containment: cards.map((card) => {
        const cardRect = card.getBoundingClientRect();
        const children = Array.from(card.querySelectorAll(
          ".record-open, .record-copy, .record-action, .record-meta, " +
          ".record-outcome, .record-tags"
        )).map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            className: node.className,
            left: rect.left,
            right: rect.right,
          };
        });
        return {
          clientWidth: card.clientWidth,
          scrollWidth: card.scrollWidth,
          left: cardRect.left,
          right: cardRect.right,
          children,
        };
      }),
      hierarchy: cards.map((card) => {
        const copy = card.querySelector(".record-copy");
        const footer = copy && copy.querySelector(":scope > .record-footer");
        const badge = footer && footer.querySelector(":scope > .badge");
        const tags = footer && footer.querySelector(":scope > .record-tags");
        const style = getComputedStyle(card);
        const rect = card.getBoundingClientRect();
        return {
          synthetic: card.classList.contains("seeded"),
          footerInsideCopy: Boolean(footer),
          badgeCount: card.querySelectorAll(".badge").length,
          tagsInsideFooter: Boolean(tags),
          tagCount: card.querySelectorAll(".record-tags").length,
          paddingTop: Number.parseFloat(style.paddingTop),
          paddingBottom: Number.parseFloat(style.paddingBottom),
          height: rect.height,
          badgeBackground: badge ? getComputedStyle(badge).backgroundColor : "",
        };
      }),
      clipped,
      bodyWidth: document.body.scrollWidth,
      pageWidth: document.querySelector("#page-history").scrollWidth,
      listWidth: document.querySelector("#history-list").scrollWidth,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
    };
  });
  assert(
    portraitHistory.cards.every((card) =>
      Math.abs(card.left - portraitHistory.list.left) <= 1 &&
      Math.abs(card.right - portraitHistory.list.right) <= 1
    ) &&
      portraitHistory.clipped.length === 0 &&
      portraitHistory.containment.every((card) =>
        card.scrollWidth <= card.clientWidth + 1 &&
        card.children.every((child) =>
          child.left >= card.left - 1 && child.right <= card.right + 1
        )
      ) &&
      portraitHistory.bodyWidth <= portraitHistory.viewportWidth &&
      portraitHistory.pageWidth <= portraitHistory.viewportWidth &&
      portraitHistory.listWidth <= portraitHistory.viewportWidth &&
      portraitHistory.documentWidth <= portraitHistory.viewportWidth,
    `portrait History clips or wraps outside its cards: ${JSON.stringify(portraitHistory)}`
  );
  const syntheticHistory = portraitHistory.hierarchy.find((card) => card.synthetic);
  const caregiverHistory = portraitHistory.hierarchy.find((card) => !card.synthetic);
  const artworkOffset = portrait.profileAlignment.textCenter -
    portrait.profileAlignment.artworkCenter;
  assert(
    portraitHistory.hierarchy.every((card) =>
      card.footerInsideCopy &&
      card.badgeCount === 1 &&
      card.tagsInsideFooter && card.tagCount === 1 &&
      card.paddingTop === 16 &&
      card.paddingBottom === 16
    ) &&
      syntheticHistory &&
      caregiverHistory &&
      syntheticHistory.height >= 150 &&
      syntheticHistory.badgeBackground !== caregiverHistory.badgeBackground &&
      artworkOffset >= 1.5 && artworkOffset <= 4.5,
    "iPhone History hierarchy or profile artwork alignment regressed: " +
      JSON.stringify({
        hierarchy: portraitHistory.hierarchy,
        artworkOffset,
      })
  );

  await page.evaluate(() => { location.hash = "baby"; });
  await page.waitForFunction(() =>
    document.querySelectorAll("#baby-training .training-row").length === 3
  );
  const portraitBaby = await page.evaluate(() => {
    const summary = document.querySelector("#baby-summary").getBoundingClientRect();
    const content = document.querySelector("#baby-content").getBoundingClientRect();
    const training = document.querySelector(
      "#baby-content > .training-card:not(.baby-context-card)"
    ).getBoundingClientRect();
    const tabbarNode = document.querySelector("#tabbar");
    const tabbar = tabbarNode.getBoundingClientRect();
    const rows = Array.from(document.querySelectorAll("#baby-training .training-row"))
      .map((node) => {
        const row = node.getBoundingClientRect();
        const copy = node.querySelector(".record-copy").getBoundingClientRect();
        const audio = node.querySelector("audio").getBoundingClientRect();
        return {
          row: { left: row.left, right: row.right },
          copy: {
            left: copy.left,
            right: copy.right,
            clipped: node.querySelector(".record-copy").scrollWidth >
              node.querySelector(".record-copy").clientWidth + 1,
          },
          audio: { left: audio.left, right: audio.right },
        };
      });
    return {
      summary: { left: summary.left, right: summary.right },
      content: { left: content.left, right: content.right },
      training: { left: training.left, right: training.right },
      tabbar: {
        top: tabbar.top,
        bottom: tabbar.bottom,
        position: getComputedStyle(tabbarNode).position,
        visibility: getComputedStyle(tabbarNode).visibility,
      },
      rows,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
    };
  });
  assert(
    Math.abs(portraitBaby.summary.left - portraitBaby.content.left) <= 1 &&
      Math.abs(portraitBaby.summary.right - portraitBaby.content.right) <= 1 &&
      Math.abs(portraitBaby.training.left - portraitBaby.content.left) <= 1 &&
      Math.abs(portraitBaby.training.right - portraitBaby.content.right) <= 1 &&
      portraitBaby.rows.every(({ row, copy, audio }) =>
        !copy.clipped &&
        copy.left >= row.left &&
        copy.right <= row.right &&
        audio.left >= row.left &&
        audio.right <= row.right
      ) &&
      portraitBaby.tabbar.position === "fixed" &&
      portraitBaby.tabbar.visibility === "visible" &&
      portraitBaby.tabbar.top >= 0 &&
      portraitBaby.tabbar.bottom <= portraitBaby.viewportHeight &&
      portraitBaby.documentWidth <= portraitBaby.viewportWidth,
    `portrait Baby content clips or wraps outside its cards: ${JSON.stringify(portraitBaby)}`
  );

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.evaluate(() => { location.hash = "history"; });
  await page.waitForFunction(() =>
    document.querySelectorAll("#history-list .record-card").length === 2
  );
  const desktopHistory = await page.evaluate(() => {
    const list = document.querySelector("#history-list").getBoundingClientRect();
    const headings = Array.from(document.querySelectorAll("#history-list .hist-day"))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      });
    const firstCard = document.querySelector("#history-list .record-card")
      .getBoundingClientRect();
    return {
      list: { left: list.left, right: list.right, width: list.width },
      headings,
      firstCard: { left: firstCard.left, top: firstCard.top },
      firstHeadingBottom: document.querySelector("#history-list .hist-day")
        .getBoundingClientRect().bottom,
    };
  });
  assert(
    desktopHistory.headings.every((heading) =>
      Math.abs(heading.left - desktopHistory.list.left) <= 1 &&
      Math.abs(heading.right - desktopHistory.list.right) <= 1
    ) &&
      Math.abs(desktopHistory.firstCard.left - desktopHistory.list.left) <= 1 &&
      desktopHistory.firstCard.top >= desktopHistory.firstHeadingBottom,
    `desktop History day groups break the card grid: ${JSON.stringify(desktopHistory)}`
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

  await page.evaluate(() => { location.hash = "baby"; });
  await page.waitForFunction(() =>
    document.querySelectorAll("#baby-training .training-row").length === 3
  );
  const landscapeBaby = await page.evaluate(() => {
    const summaryNode = document.querySelector("#baby-summary");
    const summary = summaryNode.getBoundingClientRect();
    const copy = summaryNode.querySelector(".memory-copy").getBoundingClientRect();
    const art = summaryNode.querySelector("img").getBoundingClientRect();
    const contextNode = document.querySelector(".baby-context-card");
    const context = contextNode.getBoundingClientRect();
    const trainingNode = document.querySelector(
      "#baby-content > .training-card:not(.baby-context-card)"
    );
    const training = trainingNode.getBoundingClientRect();
    const rows = Array.from(document.querySelectorAll("#baby-training .training-row"))
      .map((node) => {
        const rect = node.getBoundingClientRect();
        return { top: rect.top, bottom: rect.bottom };
      });
    return {
      summary: {
        top: summary.top,
        bottom: summary.bottom,
        clientHeight: summaryNode.clientHeight,
        scrollHeight: summaryNode.scrollHeight,
      },
      copy: { top: copy.top, bottom: copy.bottom },
      art: { top: art.top, bottom: art.bottom },
      context: {
        top: context.top,
        bottom: context.bottom,
        clientHeight: contextNode.clientHeight,
        scrollHeight: contextNode.scrollHeight,
      },
      training: { top: training.top, bottom: training.bottom },
      rows,
      documentHeight: document.documentElement.scrollHeight,
      viewportHeight: innerHeight,
    };
  });
  assert(
    landscapeBaby.summary.scrollHeight <= landscapeBaby.summary.clientHeight + 1 &&
      landscapeBaby.copy.top >= landscapeBaby.summary.top - 1 &&
      landscapeBaby.copy.bottom <= landscapeBaby.summary.bottom + 1 &&
      landscapeBaby.art.top >= landscapeBaby.summary.top - 1 &&
      landscapeBaby.art.bottom <= landscapeBaby.summary.bottom + 1 &&
      landscapeBaby.context.scrollHeight <= landscapeBaby.context.clientHeight + 1 &&
      landscapeBaby.rows.slice(0, 2).every((row) =>
        row.top >= landscapeBaby.training.top &&
        row.bottom <= landscapeBaby.training.bottom
      ) &&
      landscapeBaby.documentHeight <= landscapeBaby.viewportHeight,
    `short-landscape Baby clips its summary or training rows: ${JSON.stringify(landscapeBaby)}`
  );

  assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`);
  console.log("responsive care console browser acceptance passed");
} finally {
  await browser.close();
}
