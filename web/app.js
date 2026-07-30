"use strict";

/* Cry Memory - dual-mode client for laptop and iPhone Safari.
 *
 * Hard rules this file obeys, all of them product rules and not style choices:
 *   - No identity number ever reaches the DOM. The API deliberately does not send one; this
 *     client never asks for one, never computes one, and renders status + band + plain reasons.
 *   - No cause is ever stated. Result text is a record of what a caregiver said and did.
 *   - Audio only. There is no video capture call anywhere in this file, by design.
 *   - Care text on a matched infant is printed verbatim from the server fields
 *     guidance.interpretation / guidance.recommendation / guidance.evidence_summary.
 *     Nothing here composes, paraphrases or invents care advice.
 *   - A retry is a second independent recording. A clip already sent to an attempt can never
 *     be sent again.
 *   - Playback is blocked while the microphone is live: iOS suppresses its own speaker feed.
 */

/* -- constants --------------------------------------------------------------- */

const KIND_INFANT = "infant";
const KIND_IMITATION = "human_imitation";

const KIND_LABEL = {
  [KIND_INFANT]: "Baby cry",
  [KIND_IMITATION]: "Human cry imitation",
};

// Safari emits MP4/AAC, Chrome WebM/Opus. Feature-detected, never assumed.
const RECORDER_MIME_CANDIDATES = [
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
];

// Exactly what src/audio_ingest.py will decode. Anything else is refused with useful text.
// This is an AUDIO-ONLY set on purpose. src/audio_ingest.py happens to decode an mp4 video
// container too, but this client never names or forwards a video content type: a .mp4 picked from
// the file picker is relabelled audio/mp4 through EXTENSION_MIMES below, which the server accepts
// just the same.
const SERVER_MIMES = new Set([
  "audio/wav",
  "audio/x-wav",
  "audio/mp4",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/x-m4a",
  "audio/mpeg",
  "audio/aac",
  "audio/flac",
  "audio/webm",
  "audio/webm;codecs=opus",
  "audio/ogg",
  "audio/ogg;codecs=opus",
]);

const EXTENSION_MIMES = {
  wav: "audio/wav",
  m4a: "audio/mp4",
  mp4: "audio/mp4",
  aac: "audio/aac",
  mp3: "audio/mpeg",
  mpga: "audio/mpeg",
  flac: "audio/flac",
  webm: "audio/webm",
  ogg: "audio/ogg",
  oga: "audio/ogg",
  opus: "audio/ogg",
};

const MAX_RECORD_MS = 120000;
// The recorder stops itself at MAX_RECORD_MS. Warn before that instead of dying silently.
const RECORD_WARN_MS = 105000;
const HEALTH_POLL_MS = 20000;
const DEMO_READY_ENROLLMENTS = 3;

// Plain language for every reason code the API can send. No thresholds, no numbers, no causes.
const REASON_TEXT = {
  acoustically_consistent_with_enrolled_profile:
    "This recording is acoustically consistent with one enrolled profile.",
  retry_confirmed_nomination:
    "The second independent recording named the same profile as the first.",
  profile_provisional_single_enrollment:
    "That profile is still provisional - add more independent enrollments.",
  below_accept_threshold: "This recording was not close enough to any enrolled profile.",
  new_or_unenrolled_source: "It may be a source that has never been enrolled.",
  close_top_profiles: "Two enrolled profiles looked equally alike, so nothing was named.",
  only_one_enrolled_profile: "Only one profile of this kind is enrolled, so there is nothing to compare against.",
  cannot_identify_without_a_comparison: "Identification is comparative and needs a second profile.",
  enrol_a_second_profile_to_compare: "Enroll a second profile of this kind, then query again.",
  no_enrolled_profiles: "No profiles of this kind are enrolled yet.",
  ambiguous_source_type: "The kind of source was ambiguous, so no profile was named.",
  matched_more_than_one_family: "More than one kind of source fitted, which is never treated as an answer.",
  retry_bar_not_met: "The second recording did not clear the stricter bar a retry has to clear.",
  retry_exhausted: "The one allowed retry has been used.",
  retry_audio_identical_to_earlier_capture:
    "Those exact bytes were already sent in this attempt. A retry has to be a genuinely different recording, and the server checks that, not just this page.",
  captures_disagree: "The two recordings named different profiles, so nothing was named.",
  no_usable_voiced_audio: "No usable voice was found in the recording.",
  no_population_baseline: "The server has no population baseline for this kind yet.",
  missing_audio: "The uploaded audio could not be found on the server.",
  near_silence: "The recording was almost silent. Move closer or raise the source volume.",
  unsafe_normalization_headroom: "The recording was too loud and would distort. Lower the volume and record again.",
  empty_upload: "Nothing was uploaded.",
  upload_too_large: "That file is larger than the server accepts.",
  unsupported_mime: "The server cannot decode that audio format.",
  storage_failed: "The server could not store the upload.",
  decoder_unavailable: "The server has no working audio decoder (ffmpeg is missing).",
  decode_failed: "The server could not decode that audio.",
  empty_decoded_audio: "The decoded audio was empty.",
  decoded_audio_invalid: "The decoded audio was unusable.",
  invalid_audio: "That audio could not be used.",
  invalid_result: "The server returned a result this client could not read.",
  closed_without_resolution: "This attempt was closed without naming anyone.",
  human_confirmed_not_machine_identified:
    "A person named this profile. The system did not identify it.",
  duplicate_audio: "This exact audio is already enrolled on that profile. Use a different recording.",
  audio_already_enrolled_to_another_profile:
    "This exact audio is already enrolled on another profile of this kind.",
  no_such_profile: "That profile no longer exists.",
  identity_not_matched: "History is only revealed after identity resolves to a stored profile.",
  managed_capture_unavailable: "The server no longer has the managed audio for this attempt.",
  capture_has_no_identity_signal: "The stored capture carried no usable acoustic signal.",
  context_unavailable: "The server could not build the context for this incident.",
  incident_save_failed: "The incident could not be saved.",
  no_such_attempt: "That attempt no longer exists. Start a new query.",
  attempt_immutable: "This attempt is already closed. Start a new query.",
  retry_not_allowed: "A retry is not allowed for this attempt.",
  first_capture_already_recorded: "This attempt already has a first recording. Use the retry.",
  no_first_capture: "This attempt has no first recording yet.",
  bad_kind: "That kind of source is not one the server knows.",
  invalid_profile: "A profile needs a name and a valid kind.",
  profile_create_failed: "The server could not create that profile.",
  invalid_caregiver_answer: "The outcome text was not accepted by the server.",
  invalid_tags: "The context tags were not accepted by the server.",
  request_body_too_large: "That upload is larger than the server accepts.",
  malformed_json: "The client sent something the server could not read.",
  not_found: "That endpoint does not exist on this server.",
  unreadable_server_response: "The server sent a response this client could not read.",
  resolved_profile_unavailable: "The named profile is no longer available on the server.",
  invalid_attempt: "That attempt id is not valid.",
  incident_completion_failed: "The server could not complete this incident.",
  incident_preview_failed: "The server could not read this profile's history.",
};

const BAND_TEXT = {
  strong: "Band: strong acoustic consistency",
  weak: "Band: weak acoustic consistency - real, and deliberately not inflated",
};

// Reading history writes nothing; saving an incident writes exactly one, and cannot be undone.
const ALREADY_SAVED =
  "This incident is already recorded. The local API has no update route, so run a new query to record another one.";
const PENDING_READ = "Reading this profile's recorded history. Nothing is saved by this.";
const PENDING_SAVE =
  "Saving this incident. This can take a few seconds on the laptop.";

const OUTCOME_SOURCE_TEXT = {
  caregiver: "Caregiver reported",
  inferred: "Inferred from transcript",
  seed: "Synthetic demo data - not a real caregiver report",
};

/* -- element handles --------------------------------------------------------- */

const el = (id) => document.getElementById(id);

const ui = {
  body: document.body,
  health: el("health-status"),
  modeLabel: el("mode-label"),
  errorBanner: el("error-banner"),
  secureWarning: el("secure-warning"),
  screenMode: el("screen-mode"),
  screenWork: el("screen-work"),
  modeHeading: el("mode-heading"),
  workHeading: el("work-heading"),
  kindInfant: el("btn-kind-infant"),
  kindImitation: el("btn-kind-imitation"),
  changeMode: el("btn-change-mode"),
  legacyWorkflow: el("legacy-workflow"),
  liveSessionConsole: el("live-session-console"),
  liveCapturePanel: el("live-capture-panel"),
  liveResultPanel: el("live-result-panel"),
  liveResultHeading: el("live-result-heading"),
  liveResultStatus: el("live-result-status"),
  liveResultName: el("live-result-name"),
  liveResultExplanation: el("live-result-explanation"),
  liveSessionStatus: el("live-session-status"),
  liveSubmitStatus: el("live-submit-status"),
  newLiveSession: el("btn-new-live-session"),
  liveRetry: el("btn-live-retry"),
  liveTimelineList: el("live-timeline-list"),
  liveTimelineEmpty: el("live-timeline-empty"),
  liveParticipantsList: el("live-participants-list"),
  liveParticipantsEmpty: el("live-participants-empty"),
  liveRecordState: el("live-record-state"),
  liveRecordTimer: el("live-record-timer"),
  liveRecordStart: el("btn-live-record-start"),
  liveRecordStop: el("btn-live-record-stop"),
  livePlaybackNotice: el("live-playback-block-notice"),
  liveFileInput: el("live-file-input"),
  liveClipSummary: el("live-clip-summary"),
  liveConstraints: el("live-constraints-applied"),
  liveMime: el("live-mime-selected"),
  liveClipQuality: el("live-clip-quality"),
  recBar: el("rec-bar"),
  recBarTime: el("rec-bar-time"),
  recBarNote: el("rec-bar-note"),
  recordState: el("record-state"),
  recordTimer: el("record-timer"),
  recordStart: el("btn-record-start"),
  recordStop: el("btn-record-stop"),
  playbackNotice: el("playback-block-notice"),
  captureHint: el("capture-hint"),
  fileInput: el("file-input"),
  clipSummary: el("clip-summary"),
  constraints: el("constraints-applied"),
  mime: el("mime-selected"),
  clipQuality: el("clip-quality"),
  profileName: el("profile-name-input"),
  manualProfileCreate: el("manual-profile-create"),
  createProfile: el("btn-create-profile"),
  profileStatus: el("profile-status"),
  profileList: el("profile-list"),
  profilesEmpty: el("profiles-empty"),
  sessionSummary: el("session-summary"),
  sessionPhase: el("session-phase"),
  newHumanSession: el("btn-new-human-session"),
  profileSelect: el("profile-select"),
  panelEnroll: el("panel-enroll"),
  enroll: el("btn-enroll"),
  enrollStatus: el("enroll-status"),
  query: el("btn-query"),
  panelQuery: el("panel-query"),
  queryStatus: el("query-status"),
  resultPanel: el("panel-result"),
  resultHeading: el("result-heading"),
  resultStatus: el("result-status"),
  resultProfile: el("result-profile"),
  resultReasons: el("result-reasons"),
  retryBlock: el("retry-block"),
  retry: el("btn-retry"),
  guidanceBlock: el("guidance-block"),
  guidanceInterpretation: el("guidance-interpretation"),
  guidanceRecommendation: el("guidance-recommendation"),
  guidanceEvidence: el("guidance-evidence"),
  guidanceEmpty: el("guidance-empty"),
  revealBlock: el("reveal-block"),
  reveal: el("btn-reveal-guidance"),
  incidentsBlock: el("incidents-block"),
  incidentsList: el("incidents-list"),
  incidentsEmpty: el("incidents-empty"),
  outcomeForm: el("outcome-form"),
  outcomeInput: el("outcome-input"),
  outcomeTags: el("outcome-tags"),
  saveOutcome: el("btn-save-outcome"),
  outcomeStatus: el("outcome-status"),
  safety: el("safety-message"),
};

/* -- state ------------------------------------------------------------------- */

const state = {
  kind: null,
  profiles: [],
  clip: null, // { id, blob, contentType, label, source }
  clipUse: new Map(), // clip id -> "query" | "enrollment"
  attempt: null, // { id, retryAllowed, sentClipIds: Set }
  matchedProfileId: null,
  matchedProfileName: "",
  incidentCompleted: false,
  historyRevealed: false,
  recording: false,
  recorder: null,
  stream: null,
  chunks: [],
  timerHandle: 0,
  stopHandle: 0,
  startedAt: 0,
  wakeLock: null,
  clipCounter: 0,
  health: null,
  liveSession: null,
  liveClassification: null,
  liveSubmitting: false,
};

/* -- small helpers ----------------------------------------------------------- */

function setText(node, value) {
  // Stable by construction: never touch the DOM when the text has not changed, so a repaint,
  // a health poll or a second render cannot make the large result text flicker.
  const next = value == null ? "" : String(value);
  if (node.textContent !== next) node.textContent = next;
}

function setStatus(node, value, tone) {
  setText(node, value);
  if (tone) node.dataset.tone = tone;
  else delete node.dataset.tone;
}

function show(node, visible) {
  node.hidden = !visible;
}

function showError(message) {
  setText(ui.errorBanner, message);
  show(ui.errorBanner, Boolean(message));
}

function clearError() {
  showError("");
}

function reasonLines(reasons) {
  const list = Array.isArray(reasons) ? reasons : [];
  const seen = new Set();
  const lines = [];
  for (const reason of list) {
    if (typeof reason !== "string" || seen.has(reason)) continue;
    seen.add(reason);
    lines.push(REASON_TEXT[reason] || `The server reported: ${reason.replace(/_/g, " ")}.`);
  }
  return lines;
}

function fillList(node, lines) {
  node.replaceChildren();
  for (const line of lines) {
    const item = document.createElement("li");
    item.textContent = line;
    node.appendChild(item);
  }
}

function asciiHeader(value) {
  return String(value || "").replace(/[^\x20-\x7e]/g, "").slice(0, 120);
}

function clockText(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function byteText(bytes) {
  if (!Number.isFinite(bytes)) return "unknown size";
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* -- transport --------------------------------------------------------------- */

async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return { status: "error", reason: "unreadable_server_response" };
  }
}

async function apiJson(path, method, payload) {
  const options = { method, headers: {} };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  return { ok: response.ok, status: response.status, data: await readJson(response) };
}

async function apiAudio(path, clip) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": clip.contentType,
      "X-Capture-Source": clip.source === "microphone" ? "microphone" : "upload",
      "X-Capture-Device": asciiHeader(navigator.userAgent),
    },
    body: clip.blob,
  });
  return { ok: response.ok, status: response.status, data: await readJson(response) };
}

/* -- health ------------------------------------------------------------------ */

function describeHealth(health) {
  const missing = [];
  if (health.ffmpeg === false) missing.push("no ffmpeg decoder");
  if (health.database === false) missing.push("no database");
  if (health.encoders && health.encoders.infant === false) missing.push("infant encoder unavailable");
  if (health.encoders && health.encoders.human_imitation === false) {
    missing.push("imitation encoder unavailable");
  }
  if (health.population_baseline === false) missing.push("no population baseline");
  if (health.status === "ready" && !missing.length) return "Local server ready";
  if (!missing.length) return "Local server degraded";
  return `Local server degraded - ${missing.join(", ")}`;
}

async function refreshHealth() {
  try {
    const result = await apiJson("/api/health", "GET");
    if (!result.ok) throw new Error(`health ${result.status}`);
    state.health = result.data;
    ui.health.dataset.health = result.data.status === "ready" ? "ready" : "degraded";
    setText(ui.health, describeHealth(result.data));
  } catch (error) {
    ui.health.dataset.health = "down";
    setText(ui.health, "Local server unreachable - is it still running on the laptop?");
  }
}

/* -- capability gate: getUserMedia needs a secure context -------------------- */

function captureBlockReason() {
  if (!window.isSecureContext) {
    return (
      "Microphone access is blocked because this page is not a secure context. " +
      "iOS Safari only grants the microphone over https:// with a trusted certificate, or on " +
      "http://localhost. A plain http://192.168.x.x address will always be refused. " +
      "Restart the server with --cert/--key and open the https:// address, or choose an existing " +
      "audio file with the picker below."
    );
  }
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    return (
      "This browser exposes no microphone API. Use the file picker below to choose an existing " +
      "audio file instead."
    );
  }
  if (typeof window.MediaRecorder !== "function") {
    return (
      "This browser has no MediaRecorder, so in-page recording is unavailable. Use the file " +
      "picker below to choose an existing audio file instead."
    );
  }
  return "";
}

function activeCaptureUi() {
  if (isLiveMode()) {
    return {
      recordState: ui.liveRecordState,
      recordTimer: ui.liveRecordTimer,
      recordStart: ui.liveRecordStart,
      recordStop: ui.liveRecordStop,
      playbackNotice: ui.livePlaybackNotice,
      fileInput: ui.liveFileInput,
      clipSummary: ui.liveClipSummary,
      constraints: ui.liveConstraints,
      mime: ui.liveMime,
      clipQuality: ui.liveClipQuality,
    };
  }
  return {
    recordState: ui.recordState,
    recordTimer: ui.recordTimer,
    recordStart: ui.recordStart,
    recordStop: ui.recordStop,
    playbackNotice: ui.playbackNotice,
    fileInput: ui.fileInput,
    clipSummary: ui.clipSummary,
    constraints: ui.constraints,
    mime: ui.mime,
    clipQuality: ui.clipQuality,
  };
}

function liveSessionIsOpen() {
  return Boolean(state.liveSession && state.liveSession.status === "open");
}

function applyCaptureGate() {
  const reason = captureBlockReason();
  setText(ui.secureWarning, reason);
  show(ui.secureWarning, Boolean(reason));
  ui.recordStart.disabled = Boolean(reason) || state.recording || isLiveMode();
  ui.recordStop.disabled = !state.recording || isLiveMode();
  ui.fileInput.disabled = state.recording || isLiveMode();
  const liveReady = isLiveMode() && liveSessionIsOpen() && !state.liveSubmitting;
  ui.liveRecordStart.disabled = Boolean(reason) || state.recording || !liveReady;
  ui.liveRecordStop.disabled = !state.recording || !isLiveMode();
  ui.liveFileInput.disabled = state.recording || !liveReady;
  ui.newLiveSession.disabled = state.recording || state.liveSubmitting;
  ui.liveRetry.disabled = state.liveSubmitting || !state.clip || !liveSessionIsOpen();
}

/* -- mode -------------------------------------------------------------------- */

function focusHeading(node) {
  if (typeof node.focus === "function") node.focus();
}

function isLiveMode() {
  return state.kind === KIND_IMITATION;
}

function selectKind(kind) {
  state.kind = kind;
  const liveMode = kind === KIND_IMITATION;
  if (liveMode) ui.body.dataset.workflow = "live-session";
  else ui.body.dataset.workflow = "care-memory";
  setText(ui.modeLabel, `Kind: ${KIND_LABEL[kind]}`);
  show(ui.modeLabel, true);
  show(ui.screenMode, false);
  show(ui.screenWork, true);
  setText(ui.workHeading, liveMode ? "Live identity session" : `Capture - ${KIND_LABEL[kind]}`);
  show(ui.liveSessionConsole, liveMode);
  show(ui.legacyWorkflow, !liveMode);
  show(ui.sessionSummary, false);
  show(ui.manualProfileCreate, true);
  show(ui.panelEnroll, true);
  show(ui.panelQuery, true);
  setText(
    ui.captureHint,
    "Record here, or choose an audio file already on this device. Then choose enrollment " +
      "or blind query."
  );
  ui.profileName.placeholder = "e.g. Baby A";
  setStatus(ui.profileStatus, "");
  setStatus(ui.enrollStatus, "");
  setStatus(ui.queryStatus, "");
  resetAttempt();
  clearClip();
  focusHeading(ui.workHeading);
  if (liveMode) renderLiveSession(state.liveSession);
  else void loadProfiles();
  applyCaptureGate();
  if (state.health && state.health.encoders && state.health.encoders[kind] === false) {
    showError(
      `The server reports the encoder for ${KIND_LABEL[kind]} is unavailable, so queries of this ` +
        "kind cannot be evaluated. Check the server console."
    );
  }
}

function backToMode() {
  if (state.recording) return;
  show(ui.screenWork, false);
  show(ui.screenMode, true);
  show(ui.modeLabel, false);
  state.kind = null;
  delete ui.body.dataset.workflow;
  show(ui.sessionSummary, false);
  clearError();
  focusHeading(ui.modeHeading);
}

/* -- profiles ---------------------------------------------------------------- */

function enrollmentDots(count) {
  const filled = Math.min(count, DEMO_READY_ENROLLMENTS);
  const empty = Math.max(0, DEMO_READY_ENROLLMENTS - filled);
  return "*".repeat(filled) + "o".repeat(empty);
}

function renderProfiles() {
  const mine = state.profiles.filter((profile) => profile.kind === state.kind);
  ui.profileList.replaceChildren();
  show(ui.profilesEmpty, mine.length === 0);
  ui.newHumanSession.disabled = true;

  for (const profile of mine) {
    const count = Number.isFinite(profile.enrollments) ? profile.enrollments : 0;
    const item = document.createElement("li");

    const name = document.createElement("span");
    name.className = "profile-name";
    name.textContent = profile.display_name || "Profile name unavailable";
    item.appendChild(name);

    const meta = document.createElement("span");
    meta.className = "profile-meta";
    const word = count === 1 ? "independent recording" : "independent recordings";
    meta.textContent = `${count} ${word} enrolled - server status: ${profile.status || "unknown"}`;
    item.appendChild(meta);

    const dots = document.createElement("span");
    dots.className = "profile-meta dots";
    dots.textContent = enrollmentDots(count);
    item.appendChild(dots);

    const tag = document.createElement("span");
    if (count >= DEMO_READY_ENROLLMENTS) {
      tag.className = "tag tag-ready";
      tag.textContent = "3 independent enrollment recordings captured";
    } else {
      tag.className = "tag tag-partial";
      const need = DEMO_READY_ENROLLMENTS - count;
      tag.textContent =
        `${need} more for 3 independent enrollment recordings`;
    }
    item.appendChild(tag);

    ui.profileList.appendChild(item);
  }

  const previous = ui.profileSelect.value;
  ui.profileSelect.replaceChildren();
  if (!mine.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No profile of this kind yet";
    ui.profileSelect.appendChild(option);
    ui.profileSelect.disabled = true;
  } else {
    ui.profileSelect.disabled = false;
    for (const profile of mine) {
      const option = document.createElement("option");
      option.value = String(profile.id);
      option.textContent = `${profile.display_name} (${profile.enrollments} enrolled)`;
      ui.profileSelect.appendChild(option);
    }
    if (mine.some((profile) => String(profile.id) === previous)) {
      ui.profileSelect.value = previous;
    }
  }

  if (mine.length === 1) {
    setStatus(
      ui.queryStatus,
      "Only one profile of this kind is enrolled. A query will stay unresolved until a second " +
        "profile exists - identification here is comparative.",
      "warn"
    );
  } else if (!mine.length) {
    setStatus(ui.queryStatus, "Create and enroll two profiles of this kind first.", "warn");
  }
  updateActionButtons();
}

async function loadProfiles() {
  try {
    const result = await apiJson("/api/profiles", "GET");
    if (!result.ok) throw new Error(`profiles ${result.status}`);
    state.profiles = Array.isArray(result.data.profiles) ? result.data.profiles : [];
    renderProfiles();
  } catch (error) {
    showError("Could not load profiles from the local server.");
  }
}

async function createProfile() {
  const name = ui.profileName.value.trim();
  if (!name) {
    setStatus(ui.profileStatus, "Type a name first.", "bad");
    ui.profileName.focus();
    return;
  }
  ui.createProfile.disabled = true;
  setStatus(ui.profileStatus, "Creating...");
  try {
    const result = await apiJson("/api/profiles", "POST", {
      display_name: name,
      kind: state.kind,
    });
    if (!result.ok) {
      setStatus(ui.profileStatus, describeFailure(result.data), "bad");
      return;
    }
    ui.profileName.value = "";
    setStatus(ui.profileStatus, `Created ${name}. Now add enrollments.`, "good");
    await loadProfiles();
  } catch (error) {
    setStatus(ui.profileStatus, "The local server did not answer.", "bad");
  } finally {
    ui.createProfile.disabled = false;
  }
}

function describeFailure(data) {
  if (!data || typeof data !== "object") return "The server refused that request.";
  const reason = data.reason;
  if (typeof reason === "string" && REASON_TEXT[reason]) return REASON_TEXT[reason];
  if (typeof reason === "string") return `The server refused that request: ${reason.replace(/_/g, " ")}.`;
  const lines = reasonLines(data.reasons);
  if (lines.length) return lines.join(" ");
  return "The server refused that request.";
}

/* -- live identity session -------------------------------------------------- */

function liveParticipantName(participant) {
  if (!participant || typeof participant !== "object") return "";
  return typeof participant.display_name === "string"
    ? participant.display_name.trim()
    : "";
}

function supportingRecordingText(value) {
  if (value === 1) return "One supporting recording";
  if (value === 2) return "Two supporting recordings";
  if (Number.isInteger(value) && value > 2) return `${value} supporting recordings`;
  return "Supporting recordings not available";
}

function resetLiveResult(sessionReady) {
  ui.liveResultPanel.dataset.status = "empty";
  setText(ui.liveResultHeading, sessionReady ? "Waiting for a recording" : "Waiting for a session");
  setText(
    ui.liveResultStatus,
    sessionReady ? "Ready for the first recording." : "Every recording gets its own result here."
  );
  setText(ui.liveResultName, "");
  show(ui.liveResultName, false);
  setText(
    ui.liveResultExplanation,
    sessionReady
      ? "Record or choose one clip. It will be submitted automatically."
      : "Create a session, then record or choose one clip."
  );
}

function renderLiveClassification(classification) {
  const result =
    classification && typeof classification === "object" ? classification : {};
  const status = typeof result.status === "string" ? result.status : "invalid";
  const name = liveParticipantName(result.participant);
  let heading = "Latest recording";
  let verdict = "Recording not used";
  let explanation = "This recording could not be used. Move closer and try again.";
  let showName = false;

  if (status === "provisional_created") {
    verdict = "New pattern";
    explanation = name
      ? `New pattern. ${name} is provisional. Record another independent sample.`
      : "New pattern. It is provisional. Record another independent sample.";
    showName = Boolean(name);
  } else if (status === "participant") {
    verdict = "Repeated pattern";
    explanation = name
      ? `Repeated pattern. This matches ${name}.`
      : "Repeated pattern. The server matched an established participant.";
    showName = Boolean(name);
  } else if (status === "leaning") {
    verdict = name ? `Leaning toward ${name}` : "Leaning toward an existing participant";
    explanation = name
      ? `Leaning toward ${name}. This recording does not strengthen the profile.`
      : "This recording points in a direction but does not strengthen any profile.";
  } else if (status === "possible_new") {
    verdict = "Possible new person";
    explanation = "This may be a new person. Record another independent sample.";
  } else if (status === "duplicate") {
    verdict = "Exact duplicate";
    explanation = "Exact duplicate. Record a new sample so it can count as evidence.";
    showName = Boolean(name);
  } else if (status === "invalid") {
    verdict = "Recording not used";
    explanation = "This recording could not be used. Move closer and try again.";
  } else if (status === "session_completed") {
    heading = "Session complete";
    verdict = "Capture is closed";
    explanation = "Press New session before recording another sample.";
  } else {
    verdict = "No result available";
    explanation = "The server did not return a public classification for this recording.";
  }

  ui.liveResultPanel.dataset.status = status;
  setText(ui.liveResultHeading, heading);
  setText(ui.liveResultStatus, verdict);
  setText(ui.liveResultName, name);
  show(ui.liveResultName, showName);
  setText(ui.liveResultExplanation, explanation);
  focusHeading(ui.liveResultHeading);
}

function liveObservationLabel(observation) {
  const status = observation && observation.status;
  const participant = liveParticipantName(observation && observation.participant);
  const closest = liveParticipantName(observation && observation.closest_participant);
  if (status === "provisional_created") {
    return participant ? `New provisional: ${participant}` : "New provisional";
  }
  if (status === "participant") {
    return participant ? `Reinforced profile: ${participant}` : "Reinforced profile";
  }
  if (status === "leaning") {
    return closest ? `Direction only: ${closest}` : "Direction only";
  }
  if (status === "possible_new") return "Possible new pattern";
  if (status === "duplicate") {
    return participant ? `Duplicate: ${participant}` : "Duplicate";
  }
  if (status === "invalid") return "Recording not used";
  return "Result not available";
}

function liveObservationSource(sourceType) {
  if (sourceType === "microphone") return "Microphone capture";
  if (sourceType === "upload") return "File upload";
  return "Recording";
}

function renderLiveTimeline(observations) {
  const items = Array.isArray(observations) ? observations : [];
  ui.liveTimelineList.replaceChildren();
  show(ui.liveTimelineEmpty, items.length === 0);
  for (const observation of items) {
    if (!observation || typeof observation !== "object") continue;
    const item = document.createElement("li");
    item.className = "live-timeline-item";
    item.dataset.status =
      typeof observation.status === "string" ? observation.status : "unknown";

    const source = document.createElement("p");
    source.className = "live-timeline-source";
    source.textContent = liveObservationSource(observation.source_type);
    item.appendChild(source);

    const result = document.createElement("p");
    result.className = "live-timeline-result";
    result.textContent = liveObservationLabel(observation);
    item.appendChild(result);

    if (
      typeof observation.playback_url === "string" &&
      observation.playback_url.startsWith("/")
    ) {
      const player = document.createElement("audio");
      player.controls = !state.recording;
      player.preload = "none";
      player.src = observation.playback_url;
      if (state.recording) player.dataset.blocked = "true";
      item.appendChild(player);
    }
    ui.liveTimelineList.appendChild(item);
  }
}

function renderLiveParticipants(participants) {
  const items = Array.isArray(participants) ? participants : [];
  ui.liveParticipantsList.replaceChildren();
  show(ui.liveParticipantsEmpty, items.length === 0);
  for (const participant of items) {
    if (!participant || typeof participant !== "object") continue;
    const bubble = document.createElement("article");
    const participantState =
      participant.state === "established"
        ? "established"
        : participant.state === "provisional"
          ? "provisional"
          : "unknown";
    bubble.className = "live-participant";
    bubble.dataset.state = participantState;

    const name = document.createElement("p");
    name.className = "live-participant-name";
    name.textContent = liveParticipantName(participant) || "Participant";
    bubble.appendChild(name);

    const stateLabel = document.createElement("p");
    stateLabel.className = "live-participant-state";
    stateLabel.textContent =
      participantState === "established"
        ? "Repeated pattern"
        : participantState === "provisional"
          ? "Pattern forming"
          : "State not available";
    bubble.appendChild(stateLabel);

    const support = document.createElement("p");
    support.className = "live-participant-support";
    support.textContent = supportingRecordingText(participant.support_count);
    bubble.appendChild(support);

    ui.liveParticipantsList.appendChild(bubble);
  }
}

function renderLiveSession(session) {
  const current = session && typeof session === "object" ? session : null;
  state.liveSession = current;
  if (!current) {
    setText(ui.liveSessionStatus, "No session yet. Press New session to begin.");
    renderLiveTimeline([]);
    renderLiveParticipants([]);
    resetLiveResult(false);
    applyCaptureGate();
    return;
  }

  if (current.status === "completed") {
    setText(
      ui.liveSessionStatus,
      "This session is complete. Press New session before capturing another recording."
    );
  } else {
    setText(
      ui.liveSessionStatus,
      "Session ready. Each microphone stop or file selection submits one recording."
    );
  }
  renderLiveTimeline(current.observations);
  renderLiveParticipants(current.participants);
  applyCaptureGate();
}

async function createLiveSession() {
  if (state.liveSubmitting || state.recording) return;
  state.liveSubmitting = true;
  ui.newLiveSession.disabled = true;
  setStatus(ui.liveSubmitStatus, "Creating an empty session...");
  show(ui.liveRetry, false);
  try {
    const result = await apiJson("/api/live-sessions", "POST", {
      kind: KIND_IMITATION,
    });
    const session = result.data && result.data.session;
    if (!result.ok || !session || typeof session !== "object") {
      throw new Error("live session create failed");
    }
    const retainedClip = state.clip;
    state.liveClassification = null;
    renderLiveSession(session);
    resetLiveResult(true);
    if (retainedClip) {
      ui.liveClipSummary.dataset.hasClip = "true";
      setText(
        ui.liveClipSummary,
        `Retained: ${retainedClip.label} - ready to retry as ${retainedClip.contentType}.`
      );
      show(ui.liveRetry, true);
      setStatus(
        ui.liveSubmitStatus,
        "New session ready. The recording that was not accepted is available to retry.",
        "good"
      );
    } else {
      clearClip();
      setStatus(
        ui.liveSubmitStatus,
        "Session ready. Submit a fresh recording for each observation.",
        "good"
      );
    }
  } catch (error) {
    setStatus(
      ui.liveSubmitStatus,
      "The session could not be created. Check the local server and try again.",
      "bad"
    );
  } finally {
    state.liveSubmitting = false;
    applyCaptureGate();
  }
}

async function submitLiveObservation() {
  if (
    !isLiveMode() ||
    !liveSessionIsOpen() ||
    state.liveSubmitting ||
    !state.clip
  ) {
    return;
  }
  const clip = state.clip;
  const sessionId = state.liveSession.id;
  state.liveSubmitting = true;
  show(ui.liveRetry, false);
  setStatus(ui.liveSubmitStatus, "Submitting this recording...");
  applyCaptureGate();
  try {
    const result = await apiAudio(
      `/api/live-sessions/${sessionId}/observations`,
      clip
    );
    const data = result.data;
    if (
      !data ||
      typeof data !== "object" ||
      !data.session ||
      typeof data.classification !== "object"
    ) {
      throw new Error("live observation response missing");
    }
    state.liveClassification = data.classification;
    renderLiveSession(data.session);
    renderLiveClassification(data.classification);
    if (data.classification.status === "session_completed") {
      setText(
        ui.liveClipSummary,
        "This recording was not added. Start a new session to make it available for retry."
      );
      setStatus(
        ui.liveSubmitStatus,
        "Session complete. This recording was not added and remains available.",
        "warn"
      );
    } else {
      state.clip = null;
      ui.liveFileInput.value = "";
      ui.liveClipSummary.dataset.hasClip = "false";
      setText(ui.liveClipSummary, "Ready for another independent recording.");
      setStatus(
        ui.liveSubmitStatus,
        data.classification.status === "duplicate"
          ? "Duplicate recorded in the timeline. Capture a different sample next."
          : "Recording added to the session.",
        data.classification.status === "invalid" ? "bad" : "good"
      );
    }
  } catch (error) {
    setStatus(
      ui.liveSubmitStatus,
      "The upload did not finish. The selected recording is still available to retry.",
      "bad"
    );
    show(ui.liveRetry, true);
  } finally {
    state.liveSubmitting = false;
    applyCaptureGate();
  }
}

/* -- recording --------------------------------------------------------------- */

function pickRecorderMime() {
  if (typeof MediaRecorder.isTypeSupported !== "function") return "";
  for (const candidate of RECORDER_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return "";
}

function normalizeContentType(rawType, fileName) {
  const normalized = String(rawType || "")
    .toLowerCase()
    .split(";")
    .map((part) => part.trim())
    .filter((part, index) => index === 0 || part.length > 0)
    .join(";");
  if (SERVER_MIMES.has(normalized)) return normalized;
  const base = normalized.split(";")[0];
  if (SERVER_MIMES.has(base)) return base;
  const dot = String(fileName || "").lastIndexOf(".");
  if (dot > -1) {
    const extension = String(fileName).slice(dot + 1).toLowerCase();
    if (EXTENSION_MIMES[extension]) return EXTENSION_MIMES[extension];
  }
  return "";
}

function blockPlayback(blocked) {
  show(ui.playbackNotice, blocked && !isLiveMode());
  show(ui.livePlaybackNotice, blocked && isLiveMode());
  for (const player of document.querySelectorAll("audio")) {
    if (blocked) {
      player.pause();
      player.controls = false;
      player.dataset.blocked = "true";
    } else {
      player.controls = true;
      delete player.dataset.blocked;
    }
  }
}

function setRecordingUi(recording) {
  state.recording = recording;
  ui.body.dataset.recording = recording ? "true" : "false";
  const capture = activeCaptureUi();
  applyCaptureGate();
  // The fixed bar is the only recording evidence that survives scrolling down to the query button.
  show(ui.recBar, recording);
  if (!recording) {
    delete ui.recBar.dataset.warn;
    setText(ui.recBarNote, "");
  }
  blockPlayback(recording);
  if (recording) setText(capture.recordState, "Recording - microphone is live");
}

function tickRecordingClock() {
  const elapsed = Date.now() - state.startedAt;
  const text = clockText(elapsed);
  setText(activeCaptureUi().recordTimer, text);
  setText(ui.recBarTime, text);
  if (elapsed > RECORD_WARN_MS) {
    ui.recBar.dataset.warn = "true";
    setText(ui.recBarNote, ` auto stop at ${clockText(MAX_RECORD_MS)}`);
  }
}

// iOS releases the microphone when the screen locks or the app is backgrounded, and it mutes the
// track for an audio session interruption (a call, Siri, Control Center). None of that fires an
// error, so without the handlers below the page keeps claiming the microphone is live over a
// silent or truncated capture, and the failure only surfaces as near_silence from the server.
function watchTrackInterruptions(track) {
  if (!track || typeof track.addEventListener !== "function") return;
  track.addEventListener("mute", () => {
    ui.body.dataset.micMuted = "true";
    setText(activeCaptureUi().recordState, "Microphone muted by iOS - stop and record again");
  });
  track.addEventListener("unmute", () => {
    delete ui.body.dataset.micMuted;
    if (state.recording) {
      setText(activeCaptureUi().recordState, "Recording - microphone is live");
    }
  });
  track.addEventListener("ended", () => {
    showError("iOS ended the microphone track. Stop and record again.");
    stopRecording();
  });
}

// iOS auto-locks in 30 seconds by default, and a lock mid-capture truncates the clip.
async function holdScreenAwake() {
  if (!navigator.wakeLock || typeof navigator.wakeLock.request !== "function") return;
  try {
    state.wakeLock = await navigator.wakeLock.request("screen");
  } catch (error) {
    state.wakeLock = null;
  }
}

function releaseScreenAwake() {
  const lock = state.wakeLock;
  state.wakeLock = null;
  if (lock && typeof lock.release === "function") {
    try {
      void lock.release();
    } catch (error) {
      /* the lock is already gone, which is the state we wanted */
    }
  }
}

function stopTracks() {
  if (!state.stream) return;
  for (const track of state.stream.getTracks()) track.stop();
  state.stream = null;
}

async function startRecording() {
  const capture = activeCaptureUi();
  const blocked = captureBlockReason();
  if (blocked) {
    showError(blocked);
    return;
  }
  clearError();
  state.chunks = [];
  setText(capture.recordState, "Asking for the microphone...");

  try {
    // Audio only. Auto gain silently moves the capture level, and level drift breaks matching.
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });
  } catch (error) {
    const name = error && error.name ? error.name : "Error";
    if (name === "NotAllowedError" || name === "SecurityError") {
      showError(
        "Microphone permission was refused. On iOS Safari: aA menu -> Website Settings -> " +
          "Microphone -> Allow, then reload. On the laptop: allow the microphone in the site " +
          "permissions, or use the file picker."
      );
    } else if (name === "NotFoundError" || name === "OverconstrainedError") {
      showError("No usable microphone was found on this device. Use the file picker instead.");
    } else {
      showError(`The microphone could not be opened (${name}). Use the file picker instead.`);
    }
    setText(capture.recordState, "Idle - not recording");
    return;
  }

  const track = state.stream.getAudioTracks()[0];
  const applied = track && typeof track.getSettings === "function" ? track.getSettings() : {};
  // iOS Safari may quietly ignore a requested constraint, so show what the track actually did.
  const readback = ["echoCancellation", "noiseSuppression", "autoGainControl"]
    .map((key) => {
      const value = applied[key];
      return `${key}: ${value === undefined ? "not reported by this browser" : String(value)}`;
    })
    .join(" - ");
  setText(
    capture.constraints,
    `Requested all three off. Applied by the live track -> ${readback}` +
      (applied.sampleRate ? ` - sampleRate: ${applied.sampleRate}` : "")
  );

  watchTrackInterruptions(track);
  delete ui.body.dataset.micMuted;

  const chosen = pickRecorderMime();
  try {
    state.recorder = chosen
      ? new MediaRecorder(state.stream, { mimeType: chosen })
      : new MediaRecorder(state.stream);
  } catch (error) {
    stopTracks();
    showError("This browser refused every recording format offered. Use the file picker instead.");
    setText(capture.recordState, "Idle - not recording");
    return;
  }
  setText(
    capture.mime,
    `Recorder format: ${state.recorder.mimeType || chosen || "browser default"} ` +
      "(whatever this browser produced is uploaded as-is; the server decodes it)"
  );

  state.recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) state.chunks.push(event.data);
  });
  state.recorder.addEventListener("error", () => {
    showError("The recorder failed mid-recording. Try again.");
  });
  state.recorder.addEventListener("stop", () => {
    stopTracks();
    releaseScreenAwake();
    window.clearInterval(state.timerHandle);
    window.clearTimeout(state.stopHandle);
    const elapsed = Date.now() - state.startedAt;
    const type =
      (state.recorder && state.recorder.mimeType) ||
      (state.chunks[0] && state.chunks[0].type) ||
      chosen ||
      "";
    const blob = new Blob(state.chunks, { type });
    setRecordingUi(false);
    setText(capture.recordState, `Stopped - ${clockText(elapsed)} recorded`);
    if (!blob.size) {
      showError("The recording came back empty. Nothing was selected.");
      return;
    }
    adoptClip(blob, {
      source: "microphone",
      label: `Recording - ${clockText(elapsed)} - ${byteText(blob.size)}`,
      fileName: "",
    });
  });

  state.startedAt = Date.now();
  setRecordingUi(true);
  try {
    state.recorder.start();
  } catch (error) {
    setRecordingUi(false);
    stopTracks();
    showError("The recorder could not start. Use the file picker instead.");
    setText(capture.recordState, "Idle - not recording");
    return;
  }
  setText(capture.recordTimer, "00:00");
  setText(ui.recBarTime, "00:00");
  state.timerHandle = window.setInterval(tickRecordingClock, 250);
  state.stopHandle = window.setTimeout(() => stopRecording(), MAX_RECORD_MS);
  void holdScreenAwake();
}

function stopRecording() {
  if (state.recorder && state.recorder.state !== "inactive") {
    setText(activeCaptureUi().recordState, "Finishing the recording...");
    state.recorder.stop();
  }
}

/* -- the selected clip ------------------------------------------------------- */

function adoptClip(blob, meta) {
  const capture = activeCaptureUi();
  const contentType = normalizeContentType(blob.type || meta.fileName, meta.fileName);
  if (!contentType) {
    state.clip = null;
    setText(
      capture.clipSummary,
      `That file's format (${blob.type || "unknown"}) is not one the server can decode. ` +
        "Supported: WAV, MP4/M4A/AAC, MP3, FLAC, WebM, OGG/Opus."
    );
    capture.clipSummary.dataset.hasClip = "false";
    updateActionButtons();
    return;
  }
  state.clipCounter += 1;
  state.clip = {
    id: `clip-${state.clipCounter}`,
    blob,
    contentType,
    label: meta.label,
    source: meta.source,
  };
  setText(capture.clipSummary, `Selected: ${meta.label} - uploaded as ${contentType}`);
  capture.clipSummary.dataset.hasClip = "true";
  setStatus(ui.enrollStatus, "");
  clearError();
  updateActionButtons();
  if (isLiveMode() && liveSessionIsOpen() && !state.liveSubmitting) {
    void submitLiveObservation();
  }
}

function clearClip() {
  state.clip = null;
  ui.clipSummary.dataset.hasClip = "false";
  ui.liveClipSummary.dataset.hasClip = "false";
  setText(ui.clipSummary, "No clip selected yet.");
  setText(
    ui.liveClipSummary,
    liveSessionIsOpen()
      ? "Ready for one independent recording."
      : "Create a session before selecting a recording."
  );
  setText(ui.recordTimer, "00:00");
  setText(ui.liveRecordTimer, "00:00");
  show(ui.liveRetry, false);
  updateActionButtons();
}

function chooseFile(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  adoptClip(file, {
    source: "upload",
    label: `File - ${file.name} - ${byteText(file.size)}`,
    fileName: file.name,
  });
}

function clipUsedFor() {
  if (!state.clip) return "";
  return state.clipUse.get(state.clip.id) || "";
}

function updateActionButtons() {
  const hasClip = Boolean(state.clip);
  const used = clipUsedFor();
  const profileChosen = Boolean(ui.profileSelect.value);
  const automaticSession = isLiveMode();

  ui.enroll.disabled =
    automaticSession || !hasClip || used === "query" || !profileChosen || state.recording;
  ui.query.disabled = automaticSession || !hasClip || used === "enrollment" || state.recording;
  ui.createProfile.disabled = automaticSession || state.recording;

  const attempt = state.attempt;
  const fresh = hasClip && !used && attempt && !attempt.sentClipIds.has(state.clip.id);
  ui.retry.disabled =
    !(attempt && attempt.firstCaptureDone && attempt.retryAllowed && fresh) || state.recording;
  if (hasClip && used === "query") {
    setStatus(
      ui.enrollStatus,
      "This clip was already used as a blind query. Enrollment and query must be different " +
        "recordings, so take a fresh one.",
      "warn"
    );
  }
  if (hasClip && used === "enrollment") {
    setStatus(
      ui.queryStatus,
      "This clip is already enrolled, so querying with it would only prove it matches itself. " +
        "Record or choose a different clip.",
      "warn"
    );
  }
  applyCaptureGate();
}

/* -- enrollment -------------------------------------------------------------- */

function describeQuality(quality) {
  if (!quality || typeof quality !== "object") return "";
  const parts = [];
  if (Number.isFinite(quality.duration_s)) parts.push(`length ${quality.duration_s} s`);
  if (Number.isFinite(quality.mean_db)) parts.push(`level ${quality.mean_db} dB`);
  if (Number.isFinite(quality.peak_db)) parts.push(`peak ${quality.peak_db} dB`);
  return parts.join(" - ");
}

async function enrollClip() {
  if (!state.clip) return;
  const profileId = ui.profileSelect.value;
  if (!profileId) return;
  ui.enroll.disabled = true;
  setStatus(ui.enrollStatus, "Uploading the enrollment...");
  try {
    const result = await apiAudio(`/api/profiles/${profileId}/enroll`, state.clip);
    const data = result.data || {};
    if (result.ok && data.status === "enrolled") {
      state.clipUse.set(state.clip.id, "enrollment");
      const count = Number.isFinite(data.enrollments) ? data.enrollments : 0;
      const ready = count >= DEMO_READY_ENROLLMENTS;
      setStatus(
        ui.enrollStatus,
        `Enrolled. ${count} independent recording${count === 1 ? "" : "s"} on this profile. ` +
          (ready
            ? "3 independent enrollment recordings captured."
            : `${DEMO_READY_ENROLLMENTS - count} more for 3 independent enrollment recordings.`),
        ready ? "good" : "warn"
      );
      const quality = describeQuality(data.quality);
      if (quality) setText(ui.clipQuality, `Last enrollment: ${quality}`);
      await loadProfiles();
    } else {
      setStatus(ui.enrollStatus, describeFailure(data), "bad");
      const quality = describeQuality(data.quality);
      if (quality) setText(ui.clipQuality, `Rejected capture: ${quality}`);
    }
  } catch (error) {
    setStatus(ui.enrollStatus, "The upload failed. Is the local server still running?", "bad");
  } finally {
    updateActionButtons();
  }
}

/* -- query, retry ------------------------------------------------------------ */

function resetAttempt() {
  state.attempt = null;
  state.matchedProfileId = null;
  state.matchedProfileName = "";
  state.incidentCompleted = false;
  state.historyRevealed = false;
  show(ui.revealBlock, false);
  ui.reveal.disabled = false;
  ui.saveOutcome.disabled = false;
  show(ui.resultPanel, false);
  show(ui.retryBlock, false);
  show(ui.guidanceBlock, false);
  show(ui.incidentsBlock, false);
  show(ui.revealBlock, false);
  show(ui.outcomeForm, false);
  show(ui.safety, false);
  show(ui.resultProfile, false);
  delete ui.resultPanel.dataset.verdict;
  setText(ui.guidanceInterpretation, "");
  setText(ui.guidanceRecommendation, "");
  setText(ui.guidanceEvidence, "");
  ui.incidentsList.replaceChildren();
  setStatus(ui.outcomeStatus, "");
}

async function runQuery() {
  if (!state.clip) return;
  ui.query.disabled = true;
  // An invalid capture does not consume the attempt's first capture, so the next clip has to go
  // to /captures again - sending it to /retry would be refused as having no first capture.
  if (state.attempt && !state.attempt.firstCaptureDone) {
    const open = state.attempt;
    setStatus(ui.queryStatus, "Uploading a fresh first recording...");
    try {
      await sendCapture(`/api/identity/attempts/${open.id}/captures`);
    } catch (error) {
      setStatus(ui.queryStatus, "The query failed. Is the local server still running?", "bad");
    } finally {
      updateActionButtons();
    }
    return;
  }
  resetAttempt();
  setStatus(ui.queryStatus, "Opening an attempt...");
  try {
    const opened = await apiJson("/api/identity/attempts", "POST", { kind: state.kind });
    if (!opened.ok) {
      setStatus(ui.queryStatus, describeFailure(opened.data), "bad");
      return;
    }
    const attempt = opened.data.attempt || {};
    state.attempt = {
      id: attempt.id,
      retryAllowed: Boolean(attempt.retry_allowed),
      firstCaptureDone: false,
      sentClipIds: new Set(),
    };
    setStatus(ui.queryStatus, "Uploading the blind query...");
    await sendCapture(`/api/identity/attempts/${attempt.id}/captures`);
  } catch (error) {
    setStatus(ui.queryStatus, "The query failed. Is the local server still running?", "bad");
  } finally {
    updateActionButtons();
  }
}

async function runRetry() {
  if (!state.clip || !state.attempt) return;
  ui.retry.disabled = true;
  setStatus(ui.queryStatus, "Uploading the second independent recording...");
  try {
    await sendCapture(`/api/identity/attempts/${state.attempt.id}/retry`);
  } catch (error) {
    setStatus(ui.queryStatus, "The retry failed. Is the local server still running?", "bad");
  } finally {
    updateActionButtons();
  }
}

async function sendCapture(path) {
  const clip = state.clip;
  const result = await apiAudio(path, clip);
  const data = result.data || {};
  state.attempt.sentClipIds.add(clip.id);
  state.clipUse.set(clip.id, "query");

  if (data.identity) {
    setStatus(ui.queryStatus, "");
    renderIdentity(data.identity);
    return;
  }
  // 409 from the attempt lifecycle, or an unexpected shape.
  setStatus(ui.queryStatus, describeFailure(data), "bad");
}

/* -- rendering the identity result ------------------------------------------- */

function renderIdentity(identity) {
  const status = identity.status;
  show(ui.resultPanel, true);
  show(ui.guidanceBlock, false);
  show(ui.incidentsBlock, false);
  show(ui.outcomeForm, false);
  show(ui.safety, false);

  if (state.attempt) {
    state.attempt.retryAllowed = Boolean(identity.retry_allowed);
    // Only a decodable capture counts as the attempt's first capture.
    if (status !== "invalid") state.attempt.firstCaptureDone = true;
  }

  const lines = reasonLines(identity.reasons);

  if (status === "match") {
    ui.resultPanel.dataset.verdict = "match";
    const profile = identity.profile || {};
    state.matchedProfileId = profile.id;
    state.matchedProfileName = profile.display_name || "";
    setText(ui.resultStatus, "Matched an enrolled profile");
    setText(ui.resultProfile, state.matchedProfileName || "Profile name unavailable");
    show(ui.resultProfile, true);
    if (BAND_TEXT[identity.band]) lines.unshift(BAND_TEXT[identity.band]);
    if (identity.resolution_path === "retry_confirmed") {
      lines.unshift("Confirmed by a second independent recording.");
    }
    show(ui.retryBlock, false);
    if (state.kind === KIND_INFANT) {
      show(ui.revealBlock, true);
      show(ui.outcomeForm, true);
      show(ui.safety, true);
    } else {
      show(ui.revealBlock, false);
      show(ui.outcomeForm, false);
    }
  } else if (status === "uncertain") {
    const direction = identity.direction;
    const leaning = identity.leaning_profile || identity.closest_profile;
    const closest = identity.closest_profile;
    const possibleNew = identity.novelty === "candidate_new_profile";
    const hasDirection =
      leaning &&
      typeof leaning === "object" &&
      (direction === "clear_lead_not_confirmed" ||
        direction === "close_call_not_confirmed" ||
        direction === "outside_profiles_not_confirmed");
    if (possibleNew) {
      ui.resultPanel.dataset.verdict = "new-pending";
      setText(ui.resultStatus, "Possible new participant");
      setText(ui.resultProfile, "One more cry needed");
      show(ui.resultProfile, true);
      lines.unshift(
        "This cry was outside the current profiles. A second independent cry must show the " +
          "same novelty before the session creates another person."
      );
      if (closest && closest.display_name) {
        lines.unshift(
          `Closest existing profile: ${closest.display_name}. This direction is not confirmed.`
        );
      }
    } else if (hasDirection) {
      ui.resultPanel.dataset.verdict = "leaning";
      setText(ui.resultStatus, "Leaning toward");
      setText(ui.resultProfile, leaning.display_name || "Profile name unavailable");
      show(ui.resultProfile, true);
      lines.unshift(
        direction === "close_call_not_confirmed"
          ? "Not confirmed. This was a close call within the active session."
          : "Not confirmed. This profile led the active session but did not clear the " +
              "confirmation gate."
      );
    } else {
      ui.resultPanel.dataset.verdict = "uncertain";
      show(ui.resultProfile, false);
      setText(
        ui.resultStatus,
        identity.retry_allowed
          ? "Not enough evidence yet - one retry is allowed"
          : "Not enough evidence - no profile named"
      );
    }
    show(ui.retryBlock, Boolean(identity.retry_allowed));
    if (identity.retry_allowed) {
      lines.push(
        "Record a second, independent recording, then send it as the retry. The same clip " +
          "cannot be sent twice."
      );
    }
  } else if (status === "unresolved") {
    ui.resultPanel.dataset.verdict = "unresolved";
    const closest = identity.closest_profile;
    if (closest && closest.display_name) {
      setText(ui.resultStatus, "Closest existing profile");
      setText(ui.resultProfile, closest.display_name);
      show(ui.resultProfile, true);
      lines.unshift(
        "Not confirmed. The evidence was not strong or consistent enough to name this person."
      );
    } else {
      show(ui.resultProfile, false);
      setText(ui.resultStatus, "Unresolved - the system did not name anyone");
    }
    if ((identity.reasons || []).includes("novelty_pair_inconsistent")) {
      lines.unshift(
        "The two possible-new recordings did not match each other, so no new profile was created."
      );
    }
    show(ui.retryBlock, false);
    lines.push("No identity is confirmed, and no history is revealed.");
  } else {
    ui.resultPanel.dataset.verdict = "invalid";
    show(ui.resultProfile, false);
    setText(ui.resultStatus, "Invalid recording - nothing was decided");
    // An invalid capture did not use the retry, and it did not become the first capture either.
    // The next clip therefore goes through the blind query button again, not the retry button.
    show(ui.retryBlock, false);
    lines.push(
      "Nothing was used up. Record or choose a fresh sample and run the blind query again."
    );
  }

  fillList(ui.resultReasons, lines);
  clearClip();
  updateActionButtons();
  focusHeading(ui.resultHeading);
}

/* -- the matched infant's own recorded history -------------------------------- */

// Reading the history is a DIFFERENT request from saving the incident, and this split matters.
//
// POST /api/incidents/{attempt}/preview is read-only: it returns the matched profile's own
// scenarios and guidance and writes nothing, so it can be pressed as often as the room wants.
// POST /api/incidents/{attempt}/complete WRITES one episode. Using /complete to peek at the
// history and then again to save the outcome would store TWO episodes for one cry and silently
// inflate the profile's own history, so this client completes an attempt at most once.
async function previewIncident(tags) {
  if (!state.attempt) return;
  const payload = {};
  if (tags && tags.length) payload.tags = tags;
  const result = await apiJson(
    `/api/incidents/${state.attempt.id}/preview`,
    "POST",
    payload
  );
  const data = result.data || {};
  if (!result.ok) {
    setStatus(ui.outcomeStatus, describeFailure(data), "bad");
    return;
  }
  state.historyRevealed = true;
  renderGuidance(data.guidance);
  renderIncidents(data.scenarios, null);
  show(ui.outcomeForm, true);
}

async function completeIncident(answer, tags) {
  if (!state.attempt || state.incidentCompleted) return;
  const payload = {};
  payload.caregiver_answer = answer && answer.trim() ? answer.trim() : null;
  if (tags && tags.length) payload.tags = tags;
  const result = await apiJson(
    `/api/incidents/${state.attempt.id}/complete`,
    "POST",
    payload
  );
  const data = result.data || {};
  if (!result.ok) {
    setStatus(ui.outcomeStatus, describeFailure(data), "bad");
    return;
  }
  state.incidentCompleted = true;
  ui.saveOutcome.disabled = true;
  renderGuidance(data.guidance);
  renderIncidents(data.scenarios, data.episode);
  show(ui.outcomeForm, true);
}

function renderGuidance(guidance) {
  // Every string here is authored by the server. This client selects which server field goes in
  // which slot and does nothing else - no paraphrase, no composition, no added advice.
  const payload = guidance && typeof guidance === "object" ? guidance : {};
  const interpretation = typeof payload.interpretation === "string" ? payload.interpretation : "";
  const recommendation = typeof payload.recommendation === "string" ? payload.recommendation : "";
  const evidence = typeof payload.evidence_summary === "string" ? payload.evidence_summary : "";

  setText(ui.guidanceInterpretation, interpretation);
  setText(ui.guidanceRecommendation, recommendation);
  setText(ui.guidanceEvidence, evidence);
  show(ui.guidanceEmpty, !interpretation && !recommendation && !evidence);
  show(ui.guidanceBlock, true);
}

function appendLine(parent, text) {
  const line = document.createElement("p");
  line.className = "incident-line";
  line.textContent = text;
  parent.appendChild(line);
}

function interventionText(interventions) {
  const actions = (Array.isArray(interventions) ? interventions : [])
    .map((item) => (item && typeof item.action === "string" ? item.action.trim() : ""))
    .filter(Boolean);
  return actions.join(", ");
}

function renderIncidents(scenarios, episode) {
  const list = Array.isArray(scenarios) ? scenarios : [];
  ui.incidentsList.replaceChildren();
  show(ui.incidentsBlock, true);
  show(ui.incidentsEmpty, list.length === 0);

  if (episode && typeof episode === "object" && episode.audio_url) {
    ui.incidentsList.appendChild(
      incidentItem(
        {
          started_at: episode.started_at,
          interventions: episode.interventions,
          outcome: episode.outcome,
          outcome_src: episode.outcome_src,
          worked: episode.worked,
          audio_url: episode.audio_url,
        },
        "This recording, as saved"
      )
    );
  }
  for (const scenario of list) {
    ui.incidentsList.appendChild(incidentItem(scenario, "Earlier incident"));
  }
  if (state.recording) blockPlayback(true);
}

function incidentItem(scenario, heading) {
  const item = document.createElement("li");

  const title = document.createElement("p");
  title.className = "incident-line";
  const when = typeof scenario.started_at === "string" ? scenario.started_at : "time unrecorded";
  title.textContent = `${heading} - ${when}`;
  item.appendChild(title);

  // Provenance is never optional: a seeded row must never read as a caregiver report.
  const source = document.createElement("span");
  const key = scenario.outcome_src;
  source.className = `src src-${key === "caregiver" || key === "inferred" || key === "seed" ? key : "unknown"}`;
  source.textContent = OUTCOME_SOURCE_TEXT[key] || "Outcome source not recorded";
  item.appendChild(source);

  const actions = interventionText(scenario.interventions);
  if (actions) appendLine(item, `What the caregiver did: ${actions}`);
  if (typeof scenario.outcome === "string" && scenario.outcome.trim()) {
    appendLine(item, `Recorded outcome: ${scenario.outcome.trim()}`);
  } else {
    appendLine(item, "No outcome was recorded for this incident.");
  }
  if (scenario.worked === true) appendLine(item, "Recorded as settled afterwards.");
  else if (scenario.worked === false) appendLine(item, "Recorded as not settled afterwards.");
  if (scenario.band === "strong" || scenario.band === "weak") {
    appendLine(item, `Band: ${scenario.band}`);
  }

  if (scenario.audio_url) {
    const player = document.createElement("audio");
    player.controls = !state.recording;
    player.preload = "none";
    player.src = scenario.audio_url;
    if (state.recording) player.dataset.blocked = "true";
    item.appendChild(player);
  } else {
    appendLine(item, "No stored audio for this incident.");
  }
  return item;
}

function currentTags() {
  return ui.outcomeTags.value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

async function saveOutcome() {
  if (!state.attempt) return;
  if (state.incidentCompleted) {
    setStatus(ui.outcomeStatus, ALREADY_SAVED, "warn");
    return;
  }
  const answer = ui.outcomeInput.value;
  const tags = currentTags();
  ui.saveOutcome.disabled = true;
  setStatus(ui.outcomeStatus, PENDING_SAVE);
  try {
    await completeIncident(answer, tags);
    if (state.incidentCompleted) {
      setStatus(
        ui.outcomeStatus,
        answer.trim()
          ? "Saved. Exactly one incident is recorded for this profile, with your outcome."
          : "Saved. Exactly one incident is recorded for this profile, with no outcome text.",
        "good"
      );
    }
  } catch (error) {
    setStatus(ui.outcomeStatus, "The save failed. Is the local server still running?", "bad");
  } finally {
    ui.saveOutcome.disabled = state.incidentCompleted;
  }
}

async function revealHistory() {
  ui.reveal.disabled = true;
  setStatus(ui.outcomeStatus, PENDING_READ);
  try {
    await previewIncident(currentTags());
    if (ui.outcomeStatus.textContent === PENDING_READ) setStatus(ui.outcomeStatus, "");
  } catch (error) {
    setStatus(ui.outcomeStatus, "The local server did not answer.", "bad");
  } finally {
    ui.reveal.disabled = false;
  }
}

/* -- wiring ------------------------------------------------------------------ */

ui.kindInfant.addEventListener("click", () => selectKind(KIND_INFANT));
ui.kindImitation.addEventListener("click", () => selectKind(KIND_IMITATION));
ui.changeMode.addEventListener("click", backToMode);
ui.recordStart.addEventListener("click", () => void startRecording());
ui.recordStop.addEventListener("click", () => stopRecording());
ui.fileInput.addEventListener("change", chooseFile);
ui.liveRecordStart.addEventListener("click", () => void startRecording());
ui.liveRecordStop.addEventListener("click", () => stopRecording());
ui.liveFileInput.addEventListener("change", chooseFile);
ui.newLiveSession.addEventListener("click", () => void createLiveSession());
ui.liveRetry.addEventListener("click", () => void submitLiveObservation());
ui.createProfile.addEventListener("click", () => void createProfile());
ui.profileSelect.addEventListener("change", updateActionButtons);
ui.enroll.addEventListener("click", () => void enrollClip());
ui.query.addEventListener("click", () => void runQuery());
ui.retry.addEventListener("click", () => void runRetry());
ui.reveal.addEventListener("click", () => void revealHistory());
ui.saveOutcome.addEventListener("click", () => void saveOutcome());
window.addEventListener("pagehide", () => {
  if (state.recording) stopRecording();
});
// pagehide alone is not enough on iOS: backgrounding a standalone web app, or a screen lock,
// fires visibilitychange instead. Without this the recorder stalls while the timer keeps counting.
document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.recording) {
    showError("iOS backgrounded this page, so the recording was stopped to keep it honest.");
    stopRecording();
  }
});

applyCaptureGate();
setRecordingUi(false);
setText(ui.recordState, "Idle - not recording");
setText(ui.liveRecordState, "Idle - not recording");
focusHeading(ui.modeHeading);
void refreshHealth();
window.setInterval(() => void refreshHealth(), HEALTH_POLL_MS);
