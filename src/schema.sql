-- Owned by acoustics workstream. See docs/CONTRACTS.md for the Episode shape.

CREATE TABLE IF NOT EXISTS episode (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_id    TEXT    NOT NULL,
  started_at    TEXT    NOT NULL,   -- ISO 8601 with timezone
  duration_s    REAL,
  audio_path    TEXT,
  -- 87 float32, UN-normalized. Normalization happens at compare time because the
  -- baseline shifts as episodes accumulate; stored normalized vectors go stale.
  fingerprint   BLOB,
  transcript    TEXT    DEFAULT '',
  interventions TEXT    DEFAULT '[]',  -- JSON array of Intervention
  outcome       TEXT,
  outcome_src   TEXT,                  -- 'caregiver' | 'inferred' | NULL
  worked        INTEGER,               -- 1 | 0 | NULL
  context       TEXT    DEFAULT '{}'   -- JSON Context
);

CREATE INDEX IF NOT EXISTS idx_episode_subject ON episode(subject_id, started_at DESC);

-- Normalization baselines. subject_id = config.POPULATION_KEY holds the population
-- baseline built from the public corpus (tools/build_baseline.py). Per-subject rows
-- are only used as a fallback when no population baseline exists.
CREATE TABLE IF NOT EXISTS baseline (
  subject_id TEXT PRIMARY KEY,
  n          INTEGER NOT NULL,
  mu         BLOB    NOT NULL,
  sd         BLOB    NOT NULL,
  updated_at TEXT
);

-- ── Identity subsystem (additive, 2026-07-29) ────────────────────────────────
-- A profile is the SET of its independent enrollments, never just the latest clip.

CREATE TABLE IF NOT EXISTS profile (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name  TEXT NOT NULL,
  kind          TEXT NOT NULL,              -- 'infant' | 'human_imitation'
  status        TEXT NOT NULL DEFAULT 'provisional',  -- provisional | ready | archived
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollment (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  profile_id          INTEGER NOT NULL,
  audio_path          TEXT NOT NULL,
  audio_sha256        TEXT NOT NULL,
  captured_at         TEXT NOT NULL,
  duration_s          REAL,
  capture_device_name TEXT,
  capture_quality     TEXT,        -- JSON: mean_db, peak_db, voiced_fraction
  source_type         TEXT,        -- infant_cry | human_imitation_or_other_vocalization | uncertain
  encoder_version     TEXT NOT NULL,
  embedding           BLOB NOT NULL,
  FOREIGN KEY (profile_id) REFERENCES profile(id)
);

CREATE INDEX IF NOT EXISTS idx_enrollment_profile ON enrollment(profile_id);

-- Every identity decision is auditable after the fact.
CREATE TABLE IF NOT EXISTS identity_query (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  audio_path              TEXT,
  audio_sha256            TEXT,
  captured_at             TEXT NOT NULL,
  result_status           TEXT NOT NULL,
  matched_profile_id      INTEGER,
  supporting_enrollment_id INTEGER,
  band                    TEXT,
  score                   REAL,
  margin                  REAL,
  reason_codes            TEXT,   -- JSON array
  encoder_version         TEXT,
  calibration_version     TEXT
);

-- ── Identity attempt lifecycle (additive, Task 5, 2026-07-30) ────────────────
-- Implements `independent-retry-confirmation-v1` with refinement 5a.
--
-- An ATTEMPT is one incident: "who is this?" It holds at most two valid CAPTURES.
-- The retry is EVIDENTIAL, not a second roll of the dice: capture 1 may only
-- NOMINATE a profile, and capture 2 must independently pass a STRICTER bar and name
-- that same profile. Nothing is ever pooled - no waveform, embedding, cosine, margin
-- or headroom is averaged across captures.

CREATE TABLE IF NOT EXISTS identity_attempt (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  kind                  TEXT NOT NULL,           -- infant | human_imitation
  created_at            TEXT NOT NULL,
  status                TEXT NOT NULL,           -- open | match | unresolved
  -- display restriction ONLY. Scoring always runs against the full same-kind pool so
  -- the runner-up margin stays honest; narrowing the pool would inflate it.
  candidate_profile_ids TEXT,                    -- JSON array or NULL
  retry_allowed         INTEGER NOT NULL DEFAULT 1,
  nominated_profile_id  INTEGER,                 -- capture 1's top rank, even when uncertain
  matched_profile_id    INTEGER,
  resolution_path       TEXT,                    -- first_capture | retry_confirmed | human
  resolution_source     TEXT,                    -- system | human
  resolved_at           TEXT,
  reasons               TEXT                     -- JSON array, attempt-level
);

CREATE TABLE IF NOT EXISTS identity_attempt_capture (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id           INTEGER NOT NULL,
  seq                  INTEGER NOT NULL,         -- 1 or 2; invalid captures do not consume it
  captured_at          TEXT NOT NULL,
  -- three DISTINCT paths, never collapsed into one ambiguous field
  source_audio_path    TEXT,                     -- as uploaded
  canonical_audio_path TEXT,                     -- decoded raw; transcription reads THIS
  identity_audio_path  TEXT NOT NULL,            -- what was actually encoded for identity
  audio_sha256         TEXT,
  capture_metadata     TEXT,                     -- JSON: device, ingest versions, capture facts
  quality              TEXT,                     -- JSON: mean_db, peak_db, voiced_fraction, duration
  status               TEXT NOT NULL,            -- match | uncertain | invalid
  top_profile_id       INTEGER,
  score                REAL,                     -- DEBUG ONLY, never rendered
  margin               REAL,
  band                 TEXT,
  pool_size            INTEGER,                  -- profiles actually scored against
  candidates           TEXT,                     -- JSON ranked list
  reasons              TEXT,                     -- JSON array
  encoder_version      TEXT,
  calibration_version  TEXT,
  aggregation_version  TEXT,
  cohort_version       TEXT,                     -- NULL until cohort norm is wired
  retry_bar_applied    INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (attempt_id) REFERENCES identity_attempt(id)
);

CREATE INDEX IF NOT EXISTS idx_attempt_capture ON identity_attempt_capture(attempt_id, seq);

-- Incremental live identity sessions (additive, 2026-07-30)

CREATE TABLE IF NOT EXISTS live_identity_session (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS live_identity_participant (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  profile_id INTEGER NOT NULL,
  display_name TEXT NOT NULL,
  state TEXT NOT NULL,
  support_count INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  established_at TEXT,
  UNIQUE(session_id, profile_id)
);

CREATE TABLE IF NOT EXISTS live_identity_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  sequence INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  source_type TEXT,
  source_audio_path TEXT,
  canonical_audio_path TEXT,
  identity_audio_path TEXT NOT NULL,
  audio_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  participant_id INTEGER,
  closest_participant_id INTEGER,
  reinforced INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  UNIQUE(session_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_live_participant_session
  ON live_identity_participant(session_id, id);
CREATE INDEX IF NOT EXISTS idx_live_observation_session
  ON live_identity_observation(session_id, sequence);
