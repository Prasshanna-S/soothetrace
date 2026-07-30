"""Shared configuration. Owned by acoustics workstream - see docs/CONTRACTS.md."""
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _p(*parts):
    return os.path.join(_HERE, *parts)

# --- storage ---
DB_PATH    = _p("data", "episodes.db")
AUDIO_DIR  = _p("data", "audio")
SCHEMA_SQL = _p("src", "schema.sql")

# --- audio ---
SAMPLE_RATE = 16000

# --- models (speech path, product workstream) ---
TRANSCRIBE_MODEL = "gpt-4o-transcribe"
REASONING_MODEL  = "gpt-5.5"
OPENAI_ENV_PATH  = os.path.expanduser("~/apphatchery-discovery/.env")

# True -> use the local `whisper` CLI instead of the API.
# The acoustic path is offline regardless; this only affects transcription.
OFFLINE = os.environ.get("IM_OFFLINE", "").lower() in ("1", "true", "yes")

# --- retrieval ---
# Below this many PRIOR episodes, find_similar() returns [] and the UI must render
# the honest "not enough to compare yet" state. See docs/CONTRACTS.md.
#
# MEASURED, not guessed. Was 3 (my invention). Round-2 test I swept n=1..6 on live
# audio: at n=3-5 at least one held-out same-baby query still banded `none`; at n=6
# both held-out queries banded `weak` and all four different-baby queries banded
# `none`, with zero false-strongs. docs/ACCEPTANCE-RESULTS-02.md.
#
# Consequence for any demo: seed at least 6 PRIOR episodes before the recall moment,
# or the honest answer is "not enough to compare yet" and there is nothing to show.
MIN_EPISODES_FOR_MATCH = 6

# Band cutoffs, as percentiles of THIS subject's own historical similarities.
BAND_STRONG_PCTL = 90
BAND_WEAK_PCTL   = 60

# Key used for the population-level normalization baseline in the `baseline` table.
POPULATION_KEY = "__population__"
