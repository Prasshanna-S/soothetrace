"use strict";

const POLL_MS = 1000;

const elements = {
  body: document.body,
  serverState: document.querySelector("#server-state"),
  serverStateCopy: document.querySelector("#server-state-copy"),
  runKicker: document.querySelector("#run-kicker"),
  runTitle: document.querySelector("#run-title"),
  runSummary: document.querySelector("#run-summary"),
  sessionId: document.querySelector("#session-id"),
  segmentId: document.querySelector("#segment-id"),
  sessionState: document.querySelector("#session-state"),
  flowClock: document.querySelector("#flow-clock"),
  signalRail: document.querySelector("#signal-rail"),
  decisionPanel: document.querySelector("#decision-panel"),
  decisionState: document.querySelector("#decision-state"),
  decisionTitle: document.querySelector("#decision-title"),
  decisionRecommendation: document.querySelector("#decision-recommendation"),
  decisionDetail: document.querySelector("#decision-detail"),
  decisionEvidence: document.querySelector("#decision-evidence"),
  latchStamp: document.querySelector("#latch-stamp"),
  latchTime: document.querySelector("#latch-time"),
  factorList: document.querySelector("#factor-list"),
  segmentDuration: document.querySelector("#segment-duration"),
  segmentStages: document.querySelector("#segment-stages"),
  evidenceList: document.querySelector("#evidence-list"),
  eventStream: document.querySelector("#event-stream"),
};

let pollTimer = null;
let lastSequence = null;

function text(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function localTime(value) {
  if (!value) return "Waiting";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return parsed.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function titleCase(value) {
  const copy = text(value, "unknown").replaceAll("_", " ");
  return copy.charAt(0).toUpperCase() + copy.slice(1);
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

function renderPipeline(steps) {
  clear(elements.signalRail);
  steps.forEach((step, index) => {
    const item = make("li", "rail-step");
    item.dataset.state = text(step.state, "waiting");
    item.appendChild(make("span", "rail-step-number", String(index + 1).padStart(2, "0")));
    item.appendChild(make("span", "rail-state", titleCase(step.state)));
    item.appendChild(make("strong", "", text(step.label, "Processing step")));
    item.appendChild(make("p", "", text(step.detail, "Waiting for input.")));
    elements.signalRail.appendChild(item);
  });
}

function renderFactors(context) {
  clear(elements.factorList);
  const factors = Array.isArray(context?.factors) ? context.factors : [];
  factors.forEach((factor) => {
    const row = make("div");
    row.appendChild(make("dt", "", text(factor.label, "Signal")));
    row.appendChild(make("dd", "", text(factor.value, "Not available")));
    elements.factorList.appendChild(row);
  });
}

function renderSegment(latest) {
  clear(elements.segmentStages);
  if (!latest) {
    elements.segmentDuration.textContent = "0.00 s";
    [
      ["Ingest", "Waiting", "No phone segment yet"],
      ["Cry gate", "Waiting", "No phone segment yet"],
      ["Identity", "Waiting", "No phone segment yet"],
    ].forEach(([label, value, detail]) => {
      const card = make("article");
      card.dataset.state = "waiting";
      card.appendChild(make("p", "", label));
      card.appendChild(make("strong", "", value));
      card.appendChild(make("span", "", detail));
      elements.segmentStages.appendChild(card);
    });
    return;
  }

  elements.segmentDuration.textContent =
    typeof latest.duration_seconds === "number"
      ? `${latest.duration_seconds.toFixed(2)} s`
      : "Duration unavailable";
  const cards = [
    {
      label: "Ingest",
      state: latest.ingest?.state,
      value: `${titleCase(latest.ingest?.state)} · ${text(latest.ingest?.quality, "unknown")}`,
      detail: latest.ingest?.detail,
    },
    {
      label: "Cry gate",
      state: latest.cry_gate?.state,
      value: latest.cry_gate?.label,
      detail: latest.cry_gate?.detail,
    },
    {
      label: "Identity",
      state: latest.identity?.state,
      value: latest.identity?.label,
      detail: latest.identity?.detail,
    },
  ];
  cards.forEach((stage) => {
    const card = make("article");
    card.dataset.state = text(stage.state, "waiting");
    card.appendChild(make("p", "", stage.label));
    card.appendChild(make("strong", "", text(stage.value, "Waiting")));
    card.appendChild(make("span", "", text(stage.detail, "Waiting for input.")));
    elements.segmentStages.appendChild(card);
  });
}

function renderDecision(decision) {
  const guidance = decision?.guidance;
  const latched =
    guidance?.status === "grounded" &&
    typeof guidance.recommendation === "string" &&
    guidance.recommendation.trim();
  elements.decisionPanel.dataset.latched = latched ? "true" : "false";
  elements.latchStamp.hidden = !latched;

  if (!latched) {
    elements.decisionState.textContent = "No output yet";
    elements.decisionTitle.textContent = "Listening for a grounded pattern";
    elements.decisionRecommendation.textContent =
      "No suggestion has been created. The system only responds when the cry gate, selected baby check, and recorded history all support it.";
    elements.decisionDetail.textContent = "";
    elements.decisionEvidence.textContent = "";
    return;
  }

  elements.decisionState.textContent = text(guidance.headline, "Grounded guidance");
  elements.decisionTitle.textContent = guidance.recommendation;
  elements.decisionRecommendation.textContent = text(guidance.interpretation);
  elements.decisionDetail.textContent = text(guidance.pattern);
  elements.decisionEvidence.textContent = text(guidance.evidence_summary);
  elements.latchTime.textContent = localTime(decision.latched_at);
}

function renderEvidence(evidence) {
  clear(elements.evidenceList);
  if (!Array.isArray(evidence) || !evidence.length) {
    elements.evidenceList.appendChild(
      make("p", "empty-copy", "Evidence appears only after guidance latches.")
    );
    return;
  }
  evidence.forEach((incident) => {
    const card = make("article", "evidence-card");
    card.appendChild(
      make("span", "evidence-number", `#${incident.incident_id}`)
    );
    const copy = make("div");
    const intervention = Array.isArray(incident.interventions)
      ? incident.interventions[0]
      : null;
    copy.appendChild(
      make("h3", "", text(intervention?.action, `Incident ${incident.incident_id}`))
    );
    const outcome = text(incident.outcome, "Outcome was not recorded");
    const when = localTime(incident.recorded_at);
    copy.appendChild(make("p", "", `${when} · ${outcome}`));
    if (intervention?.evidence) {
      copy.appendChild(make("p", "", `Source: ${intervention.evidence}`));
    }
    const chips = make("div", "evidence-chips");
    (Array.isArray(incident.contributions) ? incident.contributions : []).forEach(
      (contribution) => chips.appendChild(make("span", "", contribution))
    );
    if (chips.childNodes.length) copy.appendChild(chips);
    card.appendChild(copy);
    elements.evidenceList.appendChild(card);
  });
}

function renderEvents(events) {
  clear(elements.eventStream);
  if (!Array.isArray(events) || !events.length) {
    elements.eventStream.appendChild(
      make("li", "event-empty", "Waiting for the first phone segment.")
    );
    return;
  }
  events.forEach((event) => {
    const item = make("li");
    item.dataset.tone = text(event.tone, "neutral");
    item.appendChild(
      make(
        "span",
        "event-sequence",
        typeof event.sequence === "number" ? `SEG ${String(event.sequence).padStart(3, "0")}` : "SESSION"
      )
    );
    item.appendChild(make("span", "event-time", localTime(event.created_at)));
    item.appendChild(make("span", "event-message", text(event.message, "Segment processed")));
    elements.eventStream.appendChild(item);
  });
}

function renderIdle(payload) {
  elements.body.dataset.live = "false";
  elements.runKicker.textContent = "Waiting for a care session";
  elements.runTitle.textContent = "The phone feed will appear here";
  elements.runSummary.textContent =
    "Start listening on the phone to watch each segment move through the backend.";
  elements.sessionId.textContent = "None";
  elements.segmentId.textContent = "Waiting";
  elements.sessionState.textContent = "Idle";
  elements.flowClock.textContent = `Server ${localTime(payload.server_time)}`;
  renderPipeline([
    ["ingest", "Ingest and decode"],
    ["cry_gate", "Infant cry gate"],
    ["identity", "Selected baby check"],
    ["memory", "Recorded memory"],
    ["guidance", "Guidance latch"],
  ].map(([key, label]) => ({
    key,
    label,
    state: "waiting",
    detail: "Waiting for the first 6-second segment.",
  })));
  renderDecision(null);
  renderFactors({
    factors: [
      { label: "Cry pattern", value: "Waiting for the first segment" },
      { label: "Time", value: "Waiting for an active session" },
      { label: "Care tags", value: "No active session" },
      { label: "Recorded memory", value: "No grounded incident selected yet" },
    ],
  });
  renderSegment(null);
  renderEvidence([]);
  renderEvents([]);
}

function render(payload) {
  const session = payload?.session;
  if (!session) {
    renderIdle(payload || {});
    return;
  }
  const latest = session.latest_segment;
  elements.body.dataset.live = session.state === "listening" ? "true" : "false";
  elements.runKicker.textContent = `${titleCase(session.state)} · selected profile`;
  elements.runTitle.textContent = text(session.profile?.display_name, "Unnamed baby");
  elements.runSummary.textContent =
    "Each completed phone segment is decoded, checked for an infant cry, matched to the selected baby, and compared only with that baby's recorded history.";
  elements.sessionId.textContent = `#${session.id}`;
  elements.segmentId.textContent =
    typeof latest?.sequence === "number" ? `#${latest.sequence}` : "Waiting";
  elements.sessionState.textContent = titleCase(session.state);
  elements.flowClock.textContent = latest
    ? `Segment ${latest.sequence} completed ${localTime(latest.created_at)}`
    : "Waiting for input";

  renderPipeline(Array.isArray(session.pipeline) ? session.pipeline : []);
  renderDecision(session.decision);
  renderFactors(session.context);
  renderSegment(latest);
  renderEvidence(session.evidence);
  renderEvents(session.events);

  if (typeof latest?.sequence === "number" && latest.sequence !== lastSequence) {
    elements.signalRail.animate(
      [
        { opacity: 0.55, transform: "translateY(4px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      { duration: 300, easing: "ease-out" }
    );
    lastSequence = latest.sequence;
  }
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
    elements.body.dataset.stale = "false";
    elements.serverStateCopy.textContent =
      payload.status === "idle"
        ? "Local server ready, waiting for phone"
        : "Local server receiving demo data";
    render(payload);
  } catch (error) {
    elements.body.dataset.connected = "false";
    elements.body.dataset.stale = "true";
    elements.serverStateCopy.textContent =
      "Connection lost, showing last successful state";
  } finally {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, POLL_MS);
  }
}

poll();
