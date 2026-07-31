#!/usr/bin/env node

import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const toolsDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.dirname(toolsDir);
const webRoot = path.join(repoRoot, "web");
const outputRoot = path.join(repoRoot, "demo_assets", "presentation");

const DESCRIPTION = Object.freeze({
  width: 1080,
  height: 1080,
  fps: 30,
  durationSeconds: 24,
  timeline: [
    { at: 0, label: "Listening", orbState: "listening", level: 0.12 },
    { at: 3, label: "Sound detected", orbState: "checking", level: 0.42 },
    { at: 6, label: "Checking infant cry", orbState: "checking", level: 0.56 },
    { at: 9, label: "Infant cry detected", orbState: "detected", level: 0.48 },
    {
      at: 12,
      label: "Comparing with this baby's memory",
      orbState: "detected",
      level: 0.34,
    },
    {
      at: 15,
      label: "Matching time and prior context",
      orbState: "detected",
      level: 0.26,
    },
    {
      at: 18,
      label: "Confirming against previous moments",
      orbState: "detected",
      level: 0.2,
    },
    { at: 21, label: "Suggestion ready", orbState: "grounded", level: 0.08 },
  ],
  outputs: {
    alpha: {
      codec: "prores_ks",
      pixelFormat: "yuva444p10le",
      profile: 4,
    },
    clean: {
      codec: "libx264",
      pixelFormat: "yuv420p",
      background: "#F1F2F8",
    },
  },
});

function runSelfCheck() {
  const webAssets = ["web/index.html", "web/app.css", "web/app.js"];
  const assetsReady = webAssets.every((relativePath) =>
    fs.existsSync(path.join(repoRoot, relativePath))
  );
  const ffmpeg = spawnSync("ffmpeg", ["-hide_banner", "-encoders"], {
    encoding: "utf8",
  });
  const encoderText = `${ffmpeg.stdout || ""}\n${ffmpeg.stderr || ""}`;
  let playwright;
  let chromiumPath = "";
  try {
    playwright = require("playwright");
    chromiumPath = playwright.chromium.executablePath();
  } catch (error) {
    playwright = null;
  }
  const result = {
    ready: Boolean(
      assetsReady &&
      ffmpeg.status === 0 &&
      encoderText.includes("prores_ks") &&
      encoderText.includes("libx264") &&
      playwright &&
      chromiumPath &&
      fs.existsSync(chromiumPath)
    ),
    webAssets,
    ffmpeg: {
      available: ffmpeg.status === 0,
      encoders: {
        prores_ks: encoderText.includes("prores_ks"),
        libx264: encoderText.includes("libx264"),
      },
    },
    playwright: {
      available: Boolean(playwright),
      chromiumAvailable: Boolean(chromiumPath && fs.existsSync(chromiumPath)),
    },
  };
  return result;
}

function renderPlan() {
  return {
    frameCount: DESCRIPTION.fps * DESCRIPTION.durationSeconds,
    outputs: {
      alpha: "demo_assets/presentation/soothetrace-orb-status-alpha.mov",
      clean: "demo_assets/presentation/soothetrace-orb-status-clean.mp4",
    },
    cleanWidth: 1920,
    cleanHeight: 1080,
    statusMotion: "rise-and-crossfade",
  };
}

function jsonResponse(response, status, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
  });
  response.end(body);
}

const MIME_TYPES = Object.freeze({
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json; charset=utf-8",
});

function presentationServer() {
  return http.createServer((request, response) => {
    const url = new URL(request.url || "/", "http://127.0.0.1");
    if (url.pathname === "/api/health") {
      jsonResponse(response, 200, {
        status: "ok",
        care: { ready: true },
      });
      return;
    }
    if (url.pathname === "/api/profiles") {
      jsonResponse(response, 200, {
        profiles: [
          {
            id: 12,
            display_name: "Demo Baby",
            kind: "infant",
            status: "ready",
            enrollments: 3,
          },
        ],
      });
      return;
    }
    if (url.pathname === "/api/visitor-session") {
      jsonResponse(response, 200, { session: null });
      return;
    }
    let relativePath;
    try {
      relativePath = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    } catch (error) {
      response.writeHead(400).end("Bad request");
      return;
    }
    if (!relativePath) relativePath = "index.html";
    const resolved = path.resolve(webRoot, relativePath);
    if (
      resolved !== webRoot &&
      !resolved.startsWith(`${webRoot}${path.sep}`)
    ) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
      response.writeHead(404).end("Not found");
      return;
    }
    const type = MIME_TYPES[path.extname(resolved).toLowerCase()] ||
      "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": type,
      "Cache-Control": "no-store",
    });
    fs.createReadStream(resolved).pipe(response);
  });
}

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Presentation server did not expose a TCP port."));
        return;
      }
      resolve(address.port);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: repoRoot, stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(
        new Error(
          `${command} failed with ${signal ? `signal ${signal}` : `exit ${code}`}`,
        ),
      );
    });
  });
}

function timelineFrame(timeSeconds) {
  let index = 0;
  for (let candidate = 1; candidate < DESCRIPTION.timeline.length; candidate += 1) {
    if (timeSeconds < DESCRIPTION.timeline[candidate].at) break;
    index = candidate;
  }
  const item = DESCRIPTION.timeline[index];
  const nextAt = index + 1 < DESCRIPTION.timeline.length
    ? DESCRIPTION.timeline[index + 1].at
    : DESCRIPTION.durationSeconds;
  const phase = timeSeconds - item.at;
  const stageDuration = nextAt - item.at;
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const smooth = (value) => {
    const bounded = clamp(value);
    return bounded * bounded * (3 - 2 * bounded);
  };
  const entrance = smooth(phase / 0.48);
  const exit = phase > stageDuration - 0.3
    ? smooth((stageDuration - phase) / 0.3)
    : 1;
  return {
    ...item,
    index,
    opacity: Math.min(entrance, exit),
    translateY: 18 * (1 - entrance),
  };
}

const EXPORT_CSS = `
  html, body {
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
    background: transparent !important;
  }
  body::before, body::after, #launch-screen, #ambient, #preview-bar, #rec-chip,
  #tabbar, #ctl-capsule {
    display: none !important;
  }
  #app-shell, #pages, #page-listen {
    position: fixed !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: transparent !important;
    opacity: 1 !important;
    animation: none !important;
  }
  #page-listen {
    display: block !important;
  }
  #page-listen > :not(#orb-stage) {
    display: none !important;
  }
  #orb-stage {
    display: block !important;
    position: fixed !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    background: transparent !important;
  }
  #orb-wrap {
    position: absolute !important;
    top: 116px !important;
    left: 230px !important;
    width: 620px !important;
    height: 620px !important;
    transition: none !important;
  }
  #orb {
    width: 100% !important;
    height: 100% !important;
    background: transparent !important;
  }
  #orb-shadow {
    display: none !important;
  }
  #analysis-status {
    display: block !important;
    position: absolute !important;
    left: 54px !important;
    right: 54px !important;
    bottom: 116px !important;
    min-height: 60px !important;
    margin: 0 !important;
    color: #37348C !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
      "Segoe UI", sans-serif !important;
    font-size: 38px !important;
    font-weight: 650 !important;
    line-height: 1.25 !important;
    letter-spacing: -0.025em !important;
    text-align: center !important;
    text-wrap: balance !important;
    will-change: opacity, transform !important;
  }
`;

async function captureFrames(frameDirectory) {
  const { chromium } = require("playwright");
  const server = presentationServer();
  const port = await listen(server);
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({
      viewport: { width: DESCRIPTION.width, height: DESCRIPTION.height },
      deviceScaleFactor: 1,
      colorScheme: "light",
    });
    await page.addInitScript(() => {
      let now = 0;
      let nextId = 1;
      const callbacks = new Map();
      try {
        Object.defineProperty(window.performance, "now", {
          configurable: true,
          value: () => now,
        });
      } catch (error) {
        // Chromium permits this in the renderer used by the export tool.
      }
      window.requestAnimationFrame = (callback) => {
        const id = nextId;
        nextId += 1;
        callbacks.set(id, callback);
        return id;
      };
      window.cancelAnimationFrame = (id) => callbacks.delete(id);
      window.__sootheTracePresentationClock = {
        step(milliseconds) {
          now = milliseconds;
          const pending = Array.from(callbacks.values());
          callbacks.clear();
          pending.forEach((callback) => callback(milliseconds));
          return pending.length;
        },
      };
    });
    await page.goto(`http://127.0.0.1:${port}/`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector("#orb");
    await page.addStyleTag({ content: EXPORT_CSS });
    const access = await page.evaluate(() => ({
      orbState: typeof orbState,
      setAnalysis: typeof setAnalysis,
      orb: typeof orb,
      clock: typeof window.__sootheTracePresentationClock?.step,
    }));
    if (
      access.orbState !== "function" ||
      access.setAnalysis !== "function" ||
      access.orb !== "object" ||
      access.clock !== "function"
    ) {
      throw new Error(
        `The live orb API was unavailable: ${JSON.stringify(access)}`,
      );
    }
    await page.evaluate(() => {
      const quietMotion = {
        idle: [0.16, 0.05],
        listening: [0.28, 0.12],
        checking: [0.34, 0.15],
        detected: [0.36, 0.14],
        grounded: [0.22, 0.07],
        paused: [0.04, 0],
      };
      for (const [name, values] of Object.entries(quietMotion)) {
        if (!ORB_STATES[name]) continue;
        ORB_STATES[name].speed = values[0];
        ORB_STATES[name].turn = values[1];
      }
      document.body.dataset.session = "listening";
      document.body.dataset.launched = "true";
      document.querySelector("#page-listen").dataset.state = "listening";
    });

    const frameCount = DESCRIPTION.fps * DESCRIPTION.durationSeconds;
    let activeIndex = -1;
    for (let frame = 0; frame < frameCount; frame += 1) {
      const timeSeconds = frame / DESCRIPTION.fps;
      const visual = timelineFrame(timeSeconds);
      await page.evaluate(
        ({ visual, milliseconds, stateChanged }) => {
          if (stateChanged) {
            orbState(visual.orbState);
            setAnalysis(visual.label, 0);
          }
          orb.setLevel(visual.level);
          const status = document.querySelector("#analysis-status");
          status.style.opacity = String(visual.opacity);
          status.style.transform = `translateY(${visual.translateY.toFixed(3)}px)`;
          window.__sootheTracePresentationClock.step(milliseconds);
        },
        {
          visual,
          milliseconds: timeSeconds * 1000,
          stateChanged: visual.index !== activeIndex,
        },
      );
      activeIndex = visual.index;
      const filename = `frame-${String(frame).padStart(5, "0")}.png`;
      await page.screenshot({
        path: path.join(frameDirectory, filename),
        type: "png",
        omitBackground: true,
      });
      if (frame % DESCRIPTION.fps === 0) {
        process.stdout.write(
          `Captured ${Math.floor(timeSeconds) + 1}/${DESCRIPTION.durationSeconds}s\r`,
        );
      }
    }
    process.stdout.write(
      `Captured ${DESCRIPTION.durationSeconds}/${DESCRIPTION.durationSeconds}s\n`,
    );
  } finally {
    if (browser) await browser.close();
    await closeServer(server);
  }
}

async function encodeOutputs(frameDirectory) {
  fs.mkdirSync(outputRoot, { recursive: true });
  const plan = renderPlan();
  const alphaPath = path.join(repoRoot, plan.outputs.alpha);
  const cleanPath = path.join(repoRoot, plan.outputs.clean);
  const framePattern = path.join(frameDirectory, "frame-%05d.png");

  await runCommand("ffmpeg", [
    "-hide_banner",
    "-loglevel",
    "warning",
    "-y",
    "-framerate",
    String(DESCRIPTION.fps),
    "-start_number",
    "0",
    "-i",
    framePattern,
    "-c:v",
    DESCRIPTION.outputs.alpha.codec,
    "-profile:v",
    String(DESCRIPTION.outputs.alpha.profile),
    "-bits_per_mb",
    "256",
    "-pix_fmt",
    DESCRIPTION.outputs.alpha.pixelFormat,
    "-alpha_bits",
    "16",
    "-vendor",
    "apl0",
    alphaPath,
  ]);

  await runCommand("ffmpeg", [
    "-hide_banner",
    "-loglevel",
    "warning",
    "-y",
    "-framerate",
    String(DESCRIPTION.fps),
    "-start_number",
    "0",
    "-i",
    framePattern,
    "-f",
    "lavfi",
    "-i",
    `color=c=0xF1F2F8:s=${plan.cleanWidth}x${plan.cleanHeight}:r=${DESCRIPTION.fps}:d=${DESCRIPTION.durationSeconds}`,
    "-filter_complex",
    "[1:v][0:v]overlay=(W-w)/2:(H-h)/2:alpha=straight:shortest=1,format=yuv420p[v]",
    "-map",
    "[v]",
    "-c:v",
    DESCRIPTION.outputs.clean.codec,
    "-crf",
    "18",
    "-preset",
    "medium",
    "-movflags",
    "+faststart",
    "-t",
    String(DESCRIPTION.durationSeconds),
    cleanPath,
  ]);
}

function probeVideo(relativePath) {
  const absolutePath = path.join(repoRoot, relativePath);
  const probe = spawnSync(
    "ffprobe",
    [
      "-v",
      "error",
      "-show_entries",
      "stream=codec_name,pix_fmt,width,height:format=duration",
      "-of",
      "json",
      absolutePath,
    ],
    { encoding: "utf8" },
  );
  if (probe.status !== 0) {
    return {
      path: relativePath,
      ok: false,
      error: (probe.stderr || "ffprobe failed").trim(),
    };
  }
  const parsed = JSON.parse(probe.stdout);
  const stream = parsed.streams && parsed.streams[0] ? parsed.streams[0] : {};
  return {
    path: relativePath,
    ok: true,
    bytes: fs.statSync(absolutePath).size,
    codec: stream.codec_name,
    pixelFormat: stream.pix_fmt,
    width: stream.width,
    height: stream.height,
    durationSeconds: Number(parsed.format && parsed.format.duration),
  };
}

function probeAlphaRange(relativePath) {
  const absolutePath = path.join(repoRoot, relativePath);
  const probe = spawnSync(
    "ffmpeg",
    [
      "-hide_banner",
      "-loglevel",
      "error",
      "-ss",
      "1",
      "-i",
      absolutePath,
      "-vf",
      "alphaextract,signalstats,metadata=print:file=-",
      "-frames:v",
      "1",
      "-f",
      "null",
      "-",
    ],
    { encoding: "utf8" },
  );
  const output = `${probe.stdout || ""}\n${probe.stderr || ""}`;
  const minimum = Number(output.match(/YMIN=([0-9.]+)/)?.[1]);
  const average = Number(output.match(/YAVG=([0-9.]+)/)?.[1]);
  const maximum = Number(output.match(/YMAX=([0-9.]+)/)?.[1]);
  const readable = [minimum, average, maximum].every(Number.isFinite);
  return {
    readable,
    minimum: readable ? minimum : null,
    average: readable ? average : null,
    maximum: readable ? maximum : null,
    hasTransparency: readable && minimum < average,
    hasVisiblePixels: readable && maximum > average,
  };
}

function verifyOutputs() {
  const plan = renderPlan();
  const alpha = probeVideo(plan.outputs.alpha);
  const clean = probeVideo(plan.outputs.clean);
  if (alpha.ok) alpha.alphaRange = probeAlphaRange(plan.outputs.alpha);
  const alphaReady = Boolean(
    alpha.ok &&
    alpha.codec === "prores" &&
    /^yuva444p/.test(alpha.pixelFormat || "") &&
    alpha.width === DESCRIPTION.width &&
    alpha.height === DESCRIPTION.height &&
    Math.abs(alpha.durationSeconds - DESCRIPTION.durationSeconds) < 0.1 &&
    alpha.alphaRange &&
    alpha.alphaRange.hasTransparency &&
    alpha.alphaRange.hasVisiblePixels
  );
  const cleanReady = Boolean(
    clean.ok &&
    clean.codec === "h264" &&
    clean.pixelFormat === DESCRIPTION.outputs.clean.pixelFormat &&
    clean.width === plan.cleanWidth &&
    clean.height === plan.cleanHeight &&
    Math.abs(clean.durationSeconds - DESCRIPTION.durationSeconds) < 0.1
  );
  return {
    ready: alphaReady && cleanReady,
    alpha,
    clean,
  };
}

async function render() {
  const selfCheck = runSelfCheck();
  if (!selfCheck.ready) {
    throw new Error(`Renderer self-check failed: ${JSON.stringify(selfCheck)}`);
  }
  const frameDirectory = fs.mkdtempSync(
    path.join(os.tmpdir(), "soothetrace-orb-frames-"),
  );
  const keepFrames = process.argv.includes("--keep-frames");
  try {
    await captureFrames(frameDirectory);
    await encodeOutputs(frameDirectory);
  } finally {
    const safeTempPrefix = `${path.resolve(os.tmpdir())}${path.sep}`;
    const resolvedFrames = path.resolve(frameDirectory);
    if (
      !keepFrames &&
      resolvedFrames.startsWith(safeTempPrefix) &&
      path.basename(resolvedFrames).startsWith("soothetrace-orb-frames-")
    ) {
      fs.rmSync(resolvedFrames, { recursive: true, force: true });
    } else if (keepFrames) {
      process.stdout.write(`Frames retained at ${frameDirectory}\n`);
    }
  }
  const verified = verifyOutputs();
  process.stdout.write(`${JSON.stringify(verified, null, 2)}\n`);
  if (!verified.ready) process.exitCode = 1;
}

if (process.argv.includes("--describe")) {
  process.stdout.write(`${JSON.stringify(DESCRIPTION, null, 2)}\n`);
} else if (process.argv.includes("--self-check")) {
  const result = runSelfCheck();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.ready) process.exitCode = 1;
} else if (process.argv.includes("--plan")) {
  process.stdout.write(`${JSON.stringify(renderPlan(), null, 2)}\n`);
} else if (process.argv.includes("--verify")) {
  const result = verifyOutputs();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.ready) process.exitCode = 1;
} else {
  await render();
}
