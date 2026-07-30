# 🔒 CONTRACTS - frozen interface boundaries

**Do not change anything in this file without an `ACK` from the other agent in
`docs/MESSAGES.md`.** Everything here is a boundary between `acoustics workstream`'s code and `product workstream`'s
code. If you change a signature unilaterally, the other agent's work stops compiling and
neither of you notices for an hour.

Version: **2** - bump on every agreed change and note it in `MESSAGES.md`.

*v2 (2026-07-29): `find_similar` normalizes against a stored baseline, population preferred,
per-subject fallback; returns `[]` when no baseline exists; documented the optional
`exclude_episode_id` kwarg. Proposed by acoustics workstream, ACK'd by product workstream.*

---

## Module ownership

| Module | Owner | Purpose |
|---|---|---|
| `src/fingerprint.py` | `acoustics workstream` | audio → 87-dim acoustic vector |
| `src/store.py` | `acoustics workstream` | SQLite persistence |
| `src/retrieve.py` | `acoustics workstream` | similarity search + confidence banding |
| `src/speech.py` | `product workstream` | transcription + LLM extraction (OpenAI) |
| `src/session.py` | `product workstream` | record → stop → ask caregiver → save |
| `src/cli.py` | `product workstream` | operator entry point |
| `src/schema.sql` | `acoustics workstream` | table definitions |
| `src/config.py` | `acoustics workstream` | paths, model names, thresholds |

**Nobody owns `docs/MESSAGES.md`** - it is append-only, both write.

---

## Shared data shapes (plain dicts - JSON-serializable, no cross-module classes)

### `Episode`
```python
{
  "id":            int | None,     # None before save
  "subject_id":    str,            # one infant/patient, e.g. "baby-01"
  "started_at":    str,            # ISO 8601 with timezone
  "duration_s":    float,
  "audio_path":    str,            # wav on disk, 16 kHz mono
  "fingerprint":   list[float],    # len 87, UN-normalized  (acoustics workstream)
  "transcript":    str,            # "" if unavailable       (product workstream)
  "interventions": list[Intervention],                     # (product workstream)
  "outcome":       str | None,     # caregiver's own words   (product workstream)
  "outcome_src":   "caregiver" | "inferred" | None,         # (product workstream)
  "worked":        bool | None,
  "context":       Context,
}
```

### `Intervention`
```python
{ "order": int,            # 1-based, as attempted
  "action": str,           # short verb phrase: "offered bottle"
  "evidence": str }        # the transcript span it came from - REQUIRED, no invention
```

### `Context`
```python
{ "hour_local":     int,          # 0-23 - strongest single feature (see RESEARCH.md §1)
  "minutes_since_prev_episode": float | None,
  "subject_age_days": int | None }
```

### `Match` - returned by retrieval
```python
{ "episode_id":  int,
  "similarity":  float,                        # raw cosine, for logs/debug ONLY
  "band":        "strong" | "weak" | "none",   # ← show this to humans, never similarity
  "started_at":  str,
  "interventions": list[Intervention],
  "outcome":     str | None,
  "outcome_src": str | None }
```

---

## `acoustics workstream` - acoustic path

```python
# src/fingerprint.py
DIM = 87

def compute(wav_path: str) -> list[float] | None:
    """87-dim UN-normalized fingerprint. None if too little voiced audio (<0.3 s).
    Reference implementation: experiments/feats.py::fingerprint."""

def load_audio(path: str, sr: int = 16000) -> "np.ndarray":
    """Mono float32 via ffmpeg. Accepts any ffmpeg-readable format."""
```

```python
# src/store.py
def init_db(path: str = None) -> None: ...
def save_episode(ep: dict) -> int:
    """Insert; returns new episode id. Accepts a partial Episode: transcript,
    interventions, outcome may be absent and be filled in later by update_episode."""
def update_episode(episode_id: int, **fields) -> None:
    """Patch any Episode field. product workstream uses this to attach transcript/outcome
    after the caregiver answers."""
def get_episode(episode_id: int) -> dict | None: ...
def list_episodes(subject_id: str) -> list[dict]:
    """Newest first."""
```

```python
# src/retrieve.py
def find_similar(subject_id: str, fingerprint: list[float], k: int = 3) -> list[dict]:
    """Top-k Matches from this subject's PRIOR episodes, best first.

    Contract guarantees:
      - z-scores against a stored baseline (POPULATION preferred, per-subject fallback)
        before cosine - mandatory, never raw
      - returns [] if fewer than MIN_EPISODES_FOR_MATCH prior episodes exist
        -> caller MUST render the honest 'not enough data yet' state
      - returns [] if no baseline exists at all -> run tools/build_baseline.py
      - band thresholds are percentiles of this subject's own history, not constants
    """

MIN_EPISODES_FOR_MATCH = 3

# Optional kwarg beyond the positional signature: exclude_episode_id=None. Pass the query
# episode's id when it has already been saved, or it will match itself.
```

**Banding rule** (owned by `acoustics workstream`, consumed by `product workstream`):
`strong` = ≥90th percentile of this subject's historical pairwise similarities;
`weak` = 60th-90th; `none` = below 60th. Fewer than 3 prior episodes → `find_similar` returns
`[]`, and the UI must say *"only your Nth recording - not enough to compare yet."*

---

## `product workstream` - speech path

```python
# src/speech.py
def transcribe(wav_path: str) -> str:
    """Caregiver speech from the RAW MIXTURE. Do not pre-separate - verified harmful
    (FINDINGS.md §3). Model: config.TRANSCRIBE_MODEL. Returns "" on failure, never raises."""

def extract_interventions(transcript: str) -> list[dict]:
    """Ordered Interventions. Every item MUST carry an `evidence` span copied from the
    transcript. If the transcript does not support an action, omit it - do not infer."""

def infer_outcome(transcript: str, interventions: list[dict]) -> dict | None:
    """Fallback ONLY when the caregiver skips the question.
    Returns {"outcome": str, "worked": bool} or None if the transcript doesn't say.
    Caller MUST set outcome_src='inferred'. Prefer returning None over guessing.

    ⚠️ `outcome` is the LITERAL VERBATIM TRANSCRIPT SPAN, never the model's paraphrase.
    Deliberate (proposed acoustics workstream, confirmed product workstream 2026-07-29): a quote cannot be a
    fabrication, a summary can. Renderers and src/diary.py print this value directly,
    so it will read as a quotation - that is intended, do not "clean it up"."""
```

```python
# src/session.py
def record(subject_id: str, seconds: float | None = None) -> str:
    """Capture mic to 16 kHz mono wav; returns path."""

def finish(subject_id: str, audio_path: str, caregiver_answer: str | None) -> dict:
    """Full pipeline: fingerprint -> transcribe -> extract -> save -> return the
    saved Episode. caregiver_answer=None means she skipped -> use infer_outcome
    and set outcome_src='inferred'."""
```

---

## `src/config.py` (`acoustics workstream`)

```python
DB_PATH           = "data/episodes.db"
AUDIO_DIR         = "data/audio"
SAMPLE_RATE       = 16000
TRANSCRIBE_MODEL  = "gpt-4o-transcribe"
REASONING_MODEL   = "gpt-5.5"
OPENAI_ENV_PATH   = "~/apphatchery-discovery/.env"   # key already lives here
OFFLINE           = False   # True -> local `whisper` CLI instead of the API
```

---

## Rules that are part of the contract

1. **`transcribe()` and `compute()` both receive the same un-separated wav.** No caller may
   pre-split channels.
2. **`retrieve.find_similar` is the only place cosine is computed.** `product workstream` must never
   compute similarity - call the function.
3. **`similarity` is never shown to a human.** Only `band`. No percentages.
4. **`evidence` on an Intervention is mandatory.** An action with no transcript span is a
   fabrication and must be dropped.
5. **`outcome_src` must always be surfaced in any UI** - the caregiver must be able to tell
   what she said from what the system guessed.
6. **Every function returns a value or `None`; none raise on bad input.** A crash mid-demo is
   worse than a degraded result. Log and return the empty case.
7. **No network calls in `acoustics workstream`'s modules.** The acoustic path stays fully offline-capable.
