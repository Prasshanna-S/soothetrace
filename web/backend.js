"use strict";

const POLL_MS = 1000;
const MINIMUM_AUDIO_SECONDS = 20;
const MINIMUM_SEGMENTS = 7;
const DEMO_PROFILE_NAME = "Demo Baby";

const elements = {
  body: document.body,
  connectionCopy: document.querySelector("#connection-copy"),
  sessionValue: document.querySelector("#session-value"),
  profileValue: document.querySelector("#profile-value"),
  sessionState: document.querySelector("#session-state"),
  currentState: document.querySelector("#current-state"),
  currentDetail: document.querySelector("#current-detail"),
  segmentRows: document.querySelector("#segment-rows"),
  emptyTable: document.querySelector("#empty-table"),
  suggestionPanel: document.querySelector("#suggestion-panel"),
  suggestionRecommendation: document.querySelector("#suggestion-recommendation"),
  suggestionTime: document.querySelector("#suggestion-time"),
  suggestionInterpretation: document.querySelector("#suggestion-interpretation"),
  suggestionPattern: document.querySelector("#suggestion-pattern"),
  suggestionSummary: document.querySelector("#suggestion-summary"),
  evidenceList: document.querySelector("#evidence-list"),
};

let pollTimer = null;
let activeSessionId = null;
const rowsBySegment = new Map();

function text(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function titleCase(value) {
  const copy = text(value, "unknown").replaceAll("_", " ");
  return copy.charAt(0).toUpperCase() + copy.slice(1);
}

function localTime(value) {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return parsed.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function localMinuteTime(value) {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return parsed.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function make(tag, className, copy) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (copy !== undefined) node.textContent = copy;
  return node;
}

function nonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function nonNegativeFinite(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function safeDecisionProgress(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { state: "missing", value: null };
  }
  const integerFields = [
    "consistent_grounded_segments",
    "required_consistent_grounded_segments",
    "segments_seen",
    "minimum_segments_before_decision",
  ];
  const numberFields = [
    "analyzed_audio_seconds",
    "minimum_analyzed_audio_seconds",
  ];
  if (
    !integerFields.every((field) => nonNegativeInteger(value[field])) ||
    !numberFields.every((field) => nonNegativeFinite(value[field])) ||
    typeof value.decision_eligible !== "boolean"
  ) {
    return { state: "invalid", value: null };
  }
  if (
    value.required_consistent_grounded_segments < 1 ||
    value.minimum_segments_before_decision < MINIMUM_SEGMENTS ||
    value.minimum_analyzed_audio_seconds < MINIMUM_AUDIO_SECONDS ||
    (
      value.decision_eligible &&
      (
        value.consistent_grounded_segments <
          value.required_consistent_grounded_segments ||
        value.segments_seen < value.minimum_segments_before_decision ||
        value.analyzed_audio_seconds <
          value.minimum_analyzed_audio_seconds
      )
    )
  ) {
    return { state: "invalid", value: null };
  }
  return {
    state: "valid",
    value: {
      consistent: value.consistent_grounded_segments,
      requiredConsistent: value.required_consistent_grounded_segments,
      segments: value.segments_seen,
      requiredSegments: value.minimum_segments_before_decision,
      audioSeconds: value.analyzed_audio_seconds,
      requiredAudioSeconds: value.minimum_analyzed_audio_seconds,
      eligible: value.decision_eligible,
    },
  };
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function isDemoSession(session) {
  return session?.profile?.display_name === DEMO_PROFILE_NAME;
}

function suggestionReady(session) {
  const guidance = session?.decision?.guidance;
  const grounded =
    guidance?.status === "grounded" &&
    Boolean(text(guidance.recommendation));
  if (!grounded) return false;
  if (!isDemoSession(session)) return true;
  const progress = safeDecisionProgress(
    session.decision_progress || session.latest_segment?.decision_progress
  );
  return progress.state === "valid" && progress.value.eligible;
}

function confirmationView(session, segment = session?.latest_segment) {
  if (session?.decision && !isDemoSession(session)) {
    return { state: "complete", copy: "Profile confirmation complete" };
  }
  const progress = safeDecisionProgress(
    session?.decision && segment === session.latest_segment
      ? session.decision_progress || segment?.decision_progress
      : segment?.decision_progress
  );
  if (progress.state === "invalid") {
    return {
      state: "waiting",
      copy: "Waiting for safe confirmation progress",
    };
  }
  if (progress.state === "missing") {
    return { state: "waiting", copy: "Waiting for confirmation progress" };
  }
  const value = progress.value;
  return {
    state: value.eligible ? "complete" : "collecting",
    copy: [
      `${formatNumber(value.audioSeconds)}/${formatNumber(value.requiredAudioSeconds)} s`,
      `${value.segments}/${value.requiredSegments} segments`,
      `${value.consistent}/${value.requiredConsistent} consistent`,
    ].join(" · "),
  };
}

function resultView(session, segment) {
  if (suggestionReady(session)) {
    return { state: "ready", copy: "Suggestion ready" };
  }
  if (segment?.cry_gate?.state !== "pass") {
    return { state: "no-cry", copy: "No cry" };
  }
  if (segment?.identity?.state !== "selected_profile") {
    return { state: "review", copy: "Reviewing" };
  }
  return { state: "listening", copy: "Listening" };
}

function addCell(row, mainCopy, metaCopy = "") {
  const cell = make("td");
  cell.appendChild(make("span", "cell-main", mainCopy));
  if (metaCopy) cell.appendChild(make("span", "cell-meta", metaCopy));
  row.appendChild(cell);
}

function updateSegmentRow(session, segment) {
  if (!Number.isInteger(segment?.sequence)) return;
  const key = `${session.id}:${segment.sequence}`;
  let row = rowsBySegment.get(key);
  if (!row) {
    row = make("tr");
    rowsBySegment.set(key, row);
    elements.segmentRows.appendChild(row);
  }
  clear(row);

  const confirmation = confirmationView(session, segment);
  const result = resultView(session, segment);
  row.dataset.result = result.state;

  addCell(row, `SEG ${String(segment.sequence).padStart(3, "0")}`);
  addCell(
    row,
    localTime(segment.created_at),
    typeof segment.duration_seconds === "number"
      ? `${segment.duration_seconds.toFixed(2)} s`
      : "Duration unavailable"
  );
  addCell(
    row,
    text(segment.cry_gate?.label, titleCase(segment.cry_gate?.state)),
    text(segment.cry_gate?.detail)
  );
  addCell(
    row,
    text(segment.identity?.label, titleCase(segment.identity?.state)),
    text(segment.identity?.detail)
  );
  addCell(row, confirmation.copy);
  const resultCell = make("td");
  resultCell.appendChild(make("span", "result-label", result.copy));
  row.appendChild(resultCell);
  elements.emptyTable.hidden = true;
}

function resetSession(sessionId) {
  activeSessionId = sessionId;
  rowsBySegment.clear();
  clear(elements.segmentRows);
  elements.emptyTable.hidden = false;
  hideSuggestion();
}

function hideSuggestion() {
  elements.suggestionPanel.hidden = true;
  elements.suggestionRecommendation.textContent = "";
  elements.suggestionTime.textContent = "";
  elements.suggestionInterpretation.textContent = "";
  elements.suggestionPattern.textContent = "";
  elements.suggestionSummary.textContent = "";
  clear(elements.evidenceList);
}

function renderEvidence(evidence) {
  clear(elements.evidenceList);
  (Array.isArray(evidence) ? evidence : []).forEach((incident, index) => {
    const item = make("article", "evidence-item");
    item.appendChild(
      make(
        "p",
        "evidence-rank",
        index === 0 ? "Top prior incident" : `Prior incident ${index + 1}`
      )
    );
    const content = make("div", "evidence-content");
    const intervention = Array.isArray(incident.interventions)
      ? incident.interventions[0]
      : null;
    content.appendChild(
      make("h3", "", text(intervention?.action, "Recorded care action"))
    );
    content.appendChild(
      make(
        "p",
        "",
        `${localMinuteTime(incident.recorded_at)} · ${text(
          incident.outcome,
          "Outcome not recorded"
        )}`
      )
    );
    if (text(intervention?.evidence)) {
      content.appendChild(
        make("p", "", `Source: ${text(intervention.evidence)}`)
      );
    }
    const contributions = Array.isArray(incident.contributions)
      ? incident.contributions
      : [];
    if (contributions.length) {
      const tags = make("div", "evidence-tags");
      contributions.forEach((value) => {
        const safeValue = text(value);
        if (safeValue) tags.appendChild(make("span", "", safeValue));
      });
      if (tags.childNodes.length) content.appendChild(tags);
    }
    item.appendChild(content);
    elements.evidenceList.appendChild(item);
  });
}

function renderSuggestion(session) {
  if (!suggestionReady(session)) {
    hideSuggestion();
    return;
  }
  const decision = session.decision;
  const guidance = decision.guidance;
  elements.suggestionPanel.hidden = false;
  elements.suggestionRecommendation.textContent = text(guidance.recommendation);
  elements.suggestionTime.textContent =
    `Ready ${localTime(decision.latched_at)}`;
  elements.suggestionInterpretation.textContent = text(guidance.interpretation);
  elements.suggestionPattern.textContent = text(guidance.pattern);
  elements.suggestionSummary.textContent = text(guidance.evidence_summary);
  renderEvidence(session.evidence);
}

function renderCurrentState(session) {
  const latest = session.latest_segment;
  if (!latest) {
    elements.currentState.textContent = "Waiting for the first segment";
    elements.currentDetail.textContent =
      "The table updates after each segment completes.";
    return;
  }
  if (suggestionReady(session)) {
    elements.currentState.textContent = "Suggestion ready";
    elements.currentDetail.textContent = text(
      session.decision?.guidance?.recommendation,
      "A grounded prior action is ready."
    );
    return;
  }
  elements.currentState.textContent =
    latest.cry_gate?.state === "pass"
      ? text(latest.cry_gate?.label, "Infant cry detected")
      : text(latest.cry_gate?.label, "No infant cry detected");
  elements.currentDetail.textContent = confirmationView(session, latest).copy;
}

function renderIdle() {
  if (activeSessionId !== null) resetSession(null);
  elements.sessionValue.textContent = "None";
  elements.profileValue.textContent = "Waiting";
  elements.sessionState.textContent = "Idle";
  elements.currentState.textContent = "Waiting for a phone session";
  elements.currentDetail.textContent = "Completed segments will appear below.";
}

function render(payload) {
  const session = payload?.session;
  if (!session) {
    renderIdle();
    return;
  }
  if (session.id !== activeSessionId) resetSession(session.id);

  elements.sessionValue.textContent = `#${session.id}`;
  elements.profileValue.textContent = text(
    session.profile?.display_name,
    "Unnamed profile"
  );
  elements.sessionState.textContent = titleCase(session.state);

  updateSegmentRow(session, session.latest_segment);
  renderCurrentState(session);
  renderSuggestion(session);
}

async function poll() {
  try {
    const response = await fetch("/api/demo-diagnostics", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    elements.body.dataset.connected = "true";
    elements.connectionCopy.textContent = "Connected";
    render(payload);
  } catch (error) {
    elements.body.dataset.connected = "false";
    elements.connectionCopy.textContent = "Disconnected";
  } finally {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, POLL_MS);
  }
}

poll();
