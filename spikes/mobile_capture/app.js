"use strict";

const TEST_DURATION_MS = 180_000;
const HEARTBEAT_MS = 2_000;
const MIME_CANDIDATES = [
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "video/mp4",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
];

const ui = {
  body: document.body,
  start: document.querySelector("#start"),
  stop: document.querySelector("#stop"),
  state: document.querySelector("#state"),
  timer: document.querySelector("#timer"),
  session: document.querySelector("#session"),
  secure: document.querySelector("#secure"),
  mime: document.querySelector("#mime"),
  settings: document.querySelector("#settings"),
  log: document.querySelector("#log"),
};

let sessionId = "";
let stream = null;
let recorder = null;
let selectedMime = "";
let startedAtPerformance = 0;
let startedAtWall = 0;
let heartbeatTimer = 0;
let countdownTimer = 0;
let stopTimer = 0;
let stopping = false;
let pieces = [];

function localLog(kind, detail = {}) {
  const elapsed = startedAtPerformance
    ? Math.round(performance.now() - startedAtPerformance)
    : 0;
  const line = JSON.stringify({ kind, elapsed_ms: elapsed, ...detail });
  ui.log.textContent += `${line}\n`;
  ui.log.scrollTop = ui.log.scrollHeight;
}

async function sendEvent(kind, detail = {}) {
  const event = {
    kind,
    client_wall_iso: new Date().toISOString(),
    client_performance_ms: Math.round(performance.now()),
    elapsed_ms: startedAtPerformance
      ? Math.round(performance.now() - startedAtPerformance)
      : 0,
    visibility: document.visibilityState,
    ...detail,
  };
  localLog(kind, detail);
  if (!sessionId) return;
  try {
    await fetch("/api/events", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Spike-Session": sessionId,
      },
      body: JSON.stringify(event),
      keepalive: true,
    });
  } catch (error) {
    localLog("event.upload_error", { message: String(error) });
  }
}

function setState(state, text) {
  ui.body.dataset.state = state;
  ui.state.textContent = text;
}

function updateTimer() {
  if (!startedAtWall) return;
  const remaining = Math.max(0, TEST_DURATION_MS - (Date.now() - startedAtWall));
  const totalSeconds = Math.ceil(remaining / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  ui.timer.textContent = `${minutes}:${seconds}`;
}

async function createSession() {
  const response = await fetch("/api/session", { method: "POST", body: "" });
  if (!response.ok) throw new Error(`session creation failed: ${response.status}`);
  const payload = await response.json();
  sessionId = payload.session_id;
  ui.session.textContent = sessionId;
  return sessionId;
}

function chooseMime() {
  if (!window.MediaRecorder) throw new Error("MediaRecorder is unavailable");
  if (typeof MediaRecorder.isTypeSupported !== "function") return "";
  return MIME_CANDIDATES.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
}

function attachLifecycleLogging(track) {
  document.addEventListener("visibilitychange", () => {
    void sendEvent(`visibility.${document.visibilityState}`);
  });
  window.addEventListener("pagehide", (event) => {
    void sendEvent("pagehide", { persisted: event.persisted });
  });
  window.addEventListener("pageshow", (event) => {
    void sendEvent("pageshow", { persisted: event.persisted });
  });
  window.addEventListener("freeze", () => void sendEvent("freeze"));
  window.addEventListener("resume", () => void sendEvent("resume"));
  window.addEventListener("offline", () => void sendEvent("network.offline"));
  window.addEventListener("online", () => void sendEvent("network.online"));
  for (const eventName of ["mute", "unmute", "ended"]) {
    track.addEventListener(eventName, () => {
      void sendEvent(`track.${eventName}`, {
        ready_state: track.readyState,
        muted: track.muted,
      });
    });
  }
}

async function uploadCapture(blob) {
  setState("uploading", "Uploading complete recording...");
  await sendEvent("upload.start", {
    bytes: blob.size,
    blob_type: blob.type,
    recorder_mime: recorder?.mimeType || "",
  });
  const response = await fetch("/api/upload", {
    method: "POST",
    headers: {
      "Content-Type": blob.type || selectedMime || "application/octet-stream",
      "X-Spike-Session": sessionId,
      "X-Spike-Sequence": "0",
    },
    body: blob,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `upload failed: ${response.status}`);
  await sendEvent("upload.complete", payload);
  setState("complete", "Upload complete - leave this page open");
  ui.start.disabled = false;
  ui.stop.disabled = true;
}

async function finishRecorder(reason) {
  if (stopping) return;
  stopping = true;
  clearTimeout(stopTimer);
  clearInterval(heartbeatTimer);
  clearInterval(countdownTimer);
  await sendEvent("recording.stop_requested", {
    reason,
    recorder_state: recorder?.state || "missing",
    wall_elapsed_ms: startedAtWall ? Date.now() - startedAtWall : 0,
  });
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
  }
}

async function startTest() {
  ui.start.disabled = true;
  ui.stop.disabled = false;
  ui.log.textContent = "";
  ui.timer.textContent = "03:00";
  setState("starting", "Requesting microphone...");
  pieces = [];
  stopping = false;
  startedAtPerformance = 0;
  startedAtWall = 0;

  try {
    await createSession();
    selectedMime = chooseMime();
    ui.mime.textContent = selectedMime || "Browser default";
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });
    const track = stream.getAudioTracks()[0];
    const settings = typeof track.getSettings === "function" ? track.getSettings() : {};
    const constraints =
      typeof track.getConstraints === "function" ? track.getConstraints() : {};
    ui.settings.textContent = JSON.stringify({ requested: constraints, applied: settings }, null, 2);
    attachLifecycleLogging(track);

    recorder = selectedMime
      ? new MediaRecorder(stream, { mimeType: selectedMime })
      : new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", (event) => {
      void sendEvent("recording.dataavailable", {
        bytes: event.data.size,
        blob_type: event.data.type,
      });
      if (event.data.size > 0) pieces.push(event.data);
    });
    recorder.addEventListener("error", (event) => {
      void sendEvent("recording.error", { message: event.error?.message || "unknown" });
      setState("error", "Recorder error");
    });
    recorder.addEventListener("stop", async () => {
      const blobType = recorder.mimeType || selectedMime || pieces[0]?.type || "";
      const blob = new Blob(pieces, { type: blobType });
      await sendEvent("recording.stopped", {
        bytes: blob.size,
        pieces: pieces.length,
        blob_type: blob.type,
        wall_elapsed_ms: Date.now() - startedAtWall,
      });
      for (const item of stream?.getTracks() || []) item.stop();
      try {
        await uploadCapture(blob);
      } catch (error) {
        await sendEvent("upload.error", { message: String(error) });
        setState("error", `Upload failed: ${error}`);
      }
    });

    startedAtPerformance = performance.now();
    startedAtWall = Date.now();
    recorder.start();
    setState("recording", "RECORDING - place phone face down");
    await sendEvent("recording.started", {
      selected_mime: selectedMime,
      recorder_mime: recorder.mimeType,
      requested_constraints: constraints,
      applied_settings: settings,
      secure_context: window.isSecureContext,
      user_agent: navigator.userAgent,
      target_duration_ms: TEST_DURATION_MS,
      wake_lock_requested: false,
      chunking_enabled: false,
    });
    heartbeatTimer = window.setInterval(() => {
      const currentTrack = stream?.getAudioTracks()[0];
      void sendEvent("heartbeat", {
        recorder_state: recorder?.state || "missing",
        track_ready_state: currentTrack?.readyState || "missing",
        track_muted: currentTrack?.muted ?? null,
        wall_elapsed_ms: Date.now() - startedAtWall,
      });
    }, HEARTBEAT_MS);
    countdownTimer = window.setInterval(updateTimer, 250);
    stopTimer = window.setTimeout(() => void finishRecorder("three_minute_timer"), TEST_DURATION_MS);
  } catch (error) {
    await sendEvent("start.error", { message: String(error), name: error?.name || "" });
    setState("error", `Could not start: ${error.message || error}`);
    ui.start.disabled = false;
    ui.stop.disabled = true;
  }
}

ui.secure.textContent = window.isSecureContext ? "Yes" : "NO - microphone will be blocked";
ui.start.addEventListener("click", () => void startTest());
ui.stop.addEventListener("click", () => void finishRecorder("manual_stop"));
void sendEvent("page.ready", {
  secure_context: window.isSecureContext,
  media_devices: Boolean(navigator.mediaDevices),
  media_recorder: Boolean(window.MediaRecorder),
});
