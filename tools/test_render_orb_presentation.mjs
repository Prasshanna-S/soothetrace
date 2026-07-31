import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const toolsDir = path.dirname(fileURLToPath(import.meta.url));
const renderer = path.join(toolsDir, "render_orb_presentation.mjs");
const result = spawnSync(process.execPath, [renderer, "--describe"], {
  cwd: path.dirname(toolsDir),
  encoding: "utf8",
});

assert.equal(
  result.status,
  0,
  `renderer description failed:\n${result.stdout}\n${result.stderr}`,
);

const description = JSON.parse(result.stdout);
assert.equal(description.width, 1080);
assert.equal(description.height, 1080);
assert.equal(description.fps, 30);
assert.equal(description.durationSeconds, 24);
assert.deepEqual(
  description.timeline.map(({ at, label, orbState }) => ({
    at,
    label,
    orbState,
  })),
  [
    { at: 0, label: "Listening", orbState: "listening" },
    { at: 3, label: "Sound detected", orbState: "checking" },
    { at: 6, label: "Checking infant cry", orbState: "checking" },
    { at: 9, label: "Infant cry detected", orbState: "detected" },
    {
      at: 12,
      label: "Comparing with this baby's memory",
      orbState: "detected",
    },
    {
      at: 15,
      label: "Matching time and prior context",
      orbState: "detected",
    },
    {
      at: 18,
      label: "Confirming against previous moments",
      orbState: "detected",
    },
    { at: 21, label: "Suggestion ready", orbState: "grounded" },
  ],
);
assert.equal(description.outputs.alpha.codec, "prores_ks");
assert.equal(description.outputs.alpha.pixelFormat, "yuva444p10le");
assert.equal(description.outputs.alpha.profile, 4);
assert.equal(description.outputs.clean.codec, "libx264");
assert.equal(description.outputs.clean.pixelFormat, "yuv420p");
assert.equal(description.outputs.clean.background, "#F1F2F8");

const selfCheck = spawnSync(process.execPath, [renderer, "--self-check"], {
  cwd: path.dirname(toolsDir),
  encoding: "utf8",
});
assert.equal(
  selfCheck.status,
  0,
  `renderer self-check failed:\n${selfCheck.stdout}\n${selfCheck.stderr}`,
);
const checked = JSON.parse(selfCheck.stdout);
assert.equal(checked.ready, true);
assert.deepEqual(checked.webAssets, ["web/index.html", "web/app.css", "web/app.js"]);
assert.equal(checked.ffmpeg.encoders.prores_ks, true);
assert.equal(checked.ffmpeg.encoders.libx264, true);
assert.equal(checked.playwright.available, true);
assert.equal(checked.playwright.chromiumAvailable, true);

const planResult = spawnSync(process.execPath, [renderer, "--plan"], {
  cwd: path.dirname(toolsDir),
  encoding: "utf8",
});
assert.equal(
  planResult.status,
  0,
  `renderer plan failed:\n${planResult.stdout}\n${planResult.stderr}`,
);
const plan = JSON.parse(planResult.stdout);
assert.equal(plan.frameCount, 720);
assert.equal(
  plan.outputs.alpha,
  "demo_assets/presentation/soothetrace-orb-status-alpha.mov",
);
assert.equal(
  plan.outputs.clean,
  "demo_assets/presentation/soothetrace-orb-status-clean.mp4",
);
assert.equal(plan.cleanWidth, 1920);
assert.equal(plan.cleanHeight, 1080);
assert.equal(plan.statusMotion, "rise-and-crossfade");

const alphaOutput = path.join(
  path.dirname(toolsDir),
  "demo_assets",
  "presentation",
  "soothetrace-orb-status-alpha.mov",
);
const cleanOutput = path.join(
  path.dirname(toolsDir),
  "demo_assets",
  "presentation",
  "soothetrace-orb-status-clean.mp4",
);
if (fs.existsSync(alphaOutput) && fs.existsSync(cleanOutput)) {
  const verifyResult = spawnSync(process.execPath, [renderer, "--verify"], {
    cwd: path.dirname(toolsDir),
    encoding: "utf8",
  });
  assert.equal(
    verifyResult.status,
    0,
    `rendered output verification failed:\n${verifyResult.stdout}\n${verifyResult.stderr}`,
  );
  const verified = JSON.parse(verifyResult.stdout);
  assert.equal(verified.ready, true);
  assert.ok(verified.alpha.alphaRange, "alpha range was not checked");
  assert.equal(verified.alpha.alphaRange.hasTransparency, true);
  assert.equal(verified.alpha.alphaRange.hasVisiblePixels, true);
  assert.equal(verified.clean.codec, "h264");
}

console.log("orb presentation renderer description: PASS");
