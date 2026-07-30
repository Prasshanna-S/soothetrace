"""SQLite persistence. Owned by acoustics workstream - see docs/CONTRACTS.md.

Design notes that matter:

* Fingerprints are stored UN-normalized. Normalization happens at compare time in
  retrieve.py, because the baseline shifts as episodes accumulate and stored normalized
  vectors would silently go stale.
* No function raises on bad input (docs/CONTRACTS.md rule 6). A crash mid-demo is worse
  than a degraded result.
* No network calls (rule 7).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

try:
    from . import config
except ImportError:
    import config

_FIELDS = ("subject_id", "started_at", "duration_s", "audio_path", "fingerprint",
           "transcript", "interventions", "outcome", "outcome_src", "worked", "context")
_JSON_FIELDS = ("interventions", "context")


# ------------------------------------------------------------------ helpers

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _to_blob(vec) -> bytes | None:
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob) -> list[float] | None:
    if not blob:
        return None
    try:
        return [float(x) for x in np.frombuffer(blob, dtype=np.float32)]
    except (TypeError, ValueError):
        return None


def _connect(path: str | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    parent = os.path.dirname(path)
    if parent:                      # bare filenames have no dirname; makedirs("") raises
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _row_to_episode(row: sqlite3.Row) -> dict:
    ep = dict(row)
    ep["fingerprint"] = _from_blob(ep.get("fingerprint"))
    for f in _JSON_FIELDS:
        raw = ep.get(f)
        try:
            ep[f] = json.loads(raw) if raw else ([] if f == "interventions" else {})
        except (json.JSONDecodeError, TypeError):
            ep[f] = [] if f == "interventions" else {}
    if ep.get("worked") is not None:
        ep["worked"] = bool(ep["worked"])
    return ep


# --------------------------------------------------------------- public API

def init_db(path: str | None = None) -> None:
    """Create tables if absent. Safe to call repeatedly."""
    path = path or config.DB_PATH
    try:
        with open(config.SCHEMA_SQL) as fh:
            ddl = fh.read()
    except OSError:
        return
    con = _connect(path)
    try:
        con.executescript(ddl)
        con.commit()
    finally:
        con.close()
    os.makedirs(config.AUDIO_DIR, exist_ok=True)


def save_episode(ep: dict, path: str | None = None) -> int:
    """Insert an Episode (partial is fine) and return its new id. 0 on failure.

    transcript / interventions / outcome may be absent and filled in later via
    update_episode - that is how product workstream attaches them after the caregiver answers.
    Recomputes the subject's fallback baseline on every insert.
    """
    if not ep or not ep.get("subject_id"):
        return 0
    row = {
        "subject_id":    ep.get("subject_id"),
        "started_at":    ep.get("started_at") or _now(),
        "duration_s":    ep.get("duration_s"),
        "audio_path":    ep.get("audio_path"),
        "fingerprint":   _to_blob(ep.get("fingerprint")),
        "transcript":    ep.get("transcript") or "",
        "interventions": json.dumps(ep.get("interventions") or []),
        "outcome":       ep.get("outcome"),
        "outcome_src":   ep.get("outcome_src"),
        "worked":        None if ep.get("worked") is None else int(bool(ep["worked"])),
        "context":       json.dumps(ep.get("context") or {}),
    }
    init_db(path)
    con = _connect(path)
    try:
        cur = con.execute(
            f"INSERT INTO episode ({','.join(_FIELDS)}) "
            f"VALUES ({','.join('?' * len(_FIELDS))})",
            [row[f] for f in _FIELDS],
        )
        con.commit()
        new_id = int(cur.lastrowid)
    except sqlite3.Error:
        return 0
    finally:
        con.close()
    recompute_baseline(row["subject_id"], path)
    return new_id


def update_episode(episode_id: int, path: str | None = None, **fields) -> None:
    """Patch any Episode field. Unknown keys are ignored rather than raising."""
    sets, vals = [], []
    for k, v in fields.items():
        if k not in _FIELDS:
            continue
        if k in _JSON_FIELDS:
            v = json.dumps(v or ([] if k == "interventions" else {}))
        elif k == "fingerprint":
            v = _to_blob(v)
        elif k == "worked" and v is not None:
            v = int(bool(v))
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return
    con = _connect(path)
    try:
        con.execute(f"UPDATE episode SET {','.join(sets)} WHERE id=?", vals + [episode_id])
        con.commit()
    except sqlite3.Error:
        return
    finally:
        con.close()


def get_episode(episode_id: int, path: str | None = None) -> dict | None:
    con = _connect(path)
    try:
        row = con.execute("SELECT * FROM episode WHERE id=?", (episode_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return _row_to_episode(row) if row else None


def list_episodes(subject_id: str, path: str | None = None) -> list[dict]:
    """All episodes for a subject, newest first."""
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT * FROM episode WHERE subject_id=? ORDER BY started_at DESC, id DESC",
            (subject_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [_row_to_episode(r) for r in rows]


def latest_episode(subject_id: str, path: str | None = None) -> dict | None:
    eps = list_episodes(subject_id, path)
    return eps[0] if eps else None


def delete_episode(episode_id: int, path: str | None = None) -> bool:
    """Task 2.10 - deletion must ACTUALLY delete: audio file, row, and baseline.

    docs/LIABILITY.md §4. Returns True if a row was removed.
    """
    ep = get_episode(episode_id, path)
    if not ep:
        return False
    audio = ep.get("audio_path")
    if audio and os.path.exists(audio) and os.path.abspath(audio).startswith(
            os.path.abspath(config.AUDIO_DIR)):
        try:
            os.remove(audio)
        except OSError:
            pass
    con = _connect(path)
    try:
        con.execute("DELETE FROM episode WHERE id=?", (episode_id,))
        con.commit()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    recompute_baseline(ep["subject_id"], path)
    return True


# -------------------------------------------------------------- baselines
# Normalization baseline (mu, sd). See retrieve.py for why this exists and
# docs/FINDINGS.md §5 for what happens without it.

def save_baseline(subject_id: str, mu, sd, n: int, path: str | None = None) -> None:
    init_db(path)
    con = _connect(path)
    try:
        con.execute(
            "INSERT INTO baseline (subject_id, n, mu, sd, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(subject_id) DO UPDATE SET n=excluded.n, mu=excluded.mu, "
            "sd=excluded.sd, updated_at=excluded.updated_at",
            (subject_id, int(n), _to_blob(mu), _to_blob(sd), _now()),
        )
        con.commit()
    except sqlite3.Error:
        return
    finally:
        con.close()


def get_baseline(subject_id: str, path: str | None = None) -> dict | None:
    """Returns {'mu': [...], 'sd': [...], 'n': int} or None."""
    con = _connect(path)
    try:
        row = con.execute(
            "SELECT n, mu, sd FROM baseline WHERE subject_id=?", (subject_id,)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row:
        return None
    return {"n": int(row["n"]), "mu": _from_blob(row["mu"]), "sd": _from_blob(row["sd"])}


def recompute_baseline(subject_id: str, path: str | None = None) -> None:
    """Refresh a subject's fallback baseline from their own stored fingerprints.

    Only used when no population baseline exists - a handful of episodes is far too few
    for stable per-subject statistics. Build the population baseline with
    tools/build_baseline.py.
    """
    fps = [ep["fingerprint"] for ep in list_episodes(subject_id, path)
           if ep.get("fingerprint")]
    if len(fps) < 2:
        if subject_id == config.POPULATION_KEY:
            return
        con = _connect(path)
        try:
            con.execute(
                "DELETE FROM baseline WHERE subject_id=?",
                (subject_id,),
            )
            con.commit()
        except sqlite3.Error:
            return
        finally:
            con.close()
        return
    X = np.asarray(fps, dtype=np.float32)
    save_baseline(subject_id, X.mean(0), X.std(0), len(fps), path)
