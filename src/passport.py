"""Communication Passport export - task 3.2. Owned by the acoustics workstream.

WHY THIS IS THE DIFFERENTIATOR ARTIFACT
A **Communication Passport** is a real, established instrument in AAC practice: a portable
document that carries what one individual's idiosyncratic signals mean, and what helps, from
one caregiver to the next. Same idea as a caregiver-authored "gesture dictionary" for a
non-symbolic communicator (ASHA/NJC; UNL AAC), and there are formal templates and services
for it (communicationpassports.org.uk, PAMIS Digital Passports).

Every one of them is hand-written and static. Nobody generates one automatically from
recorded interactions. That gap is the strongest novelty claim this project has, and it is
documented in docs/RESEARCH.md section 3d.

This module is the automatic generation. It is also, deliberately, pure arithmetic over what
a caregiver actually reported. Nothing here is inferred, so nothing here can hallucinate.

HOW THIS DIFFERS FROM src/diary.py, which looks superficially similar:
  * `diary` is chronological and clinical. It answers "what happened, day by day", and its
    reader is a clinician who wants the pattern over time.
  * `passport` is portable and practical. It answers "if you are looking after this person
    tonight and I am not there, what does the record say helped", and its reader is the next
    caregiver. It is ordered by what worked, not by when it happened.
Both read the same episodes through the same tally, so they cannot disagree.

WRITTEN IN THE THIRD PERSON, ON PURPOSE
Real passports are conventionally written in the first person ("I like it when you..."), which
is a dignity practice: it centres the person rather than the professional. This generator does
NOT do that, and the reason is not a shortcut. A first-person passport asserts an inner state
("I get upset when...") that we have no access to. For a pre-verbal infant, or anyone who
cannot confirm or correct the text, generating that voice automatically means inventing it.
So every line here is third person and attributive: what was recorded, who reported it, how
often. A human facilitator can rewrite it in the first person with the person present, which
is how the instrument is supposed to be authored anyway.

LIABILITY CONSTRAINTS BAKED IN (docs/LIABILITY.md sections 1 and 7):
  * No cause labels, ever. "Feeding was the last thing tried before the crying stopped 3
    times" is a count. "The baby was hungry" is a diagnosis, and we never write it.
  * No advice, and no imperatives. The document reports what a caregiver did. It never
    instructs the next one, because an instruction is a clinical recommendation.
  * No comparison against population norms, because "cries more than normal" is
    disease-adjacent and this is a general wellness product.
  * `outcome_src` is always surfaced, and 'seed' is rendered as visibly synthetic. A passport
    containing any synthetic episode is stamped as such at the top, not in a footnote.
  * A thin record produces a document that says it is thin. It never produces a confident
    short document, because the failure mode of this artifact is being believed.

No network calls (docs/CONTRACTS.md rule 7).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

try:
    from . import retrieve, store
except ImportError:  # direct-script execution
    import retrieve
    import store

# Below this many usable episodes the document is marked provisional. Three is not a
# statistical threshold and is not presented as one: it is the point at which "it worked once"
# stops being the only thing the record can say. One episode cannot distinguish a repeatable
# response from a coincidence, and two cannot either.
MIN_EPISODES_FOR_PASSPORT = 3

STATUS_EMPTY = "empty"
STATUS_PROVISIONAL = "provisional"
STATUS_READY = "ready"

_SRC_LABEL = {
    "caregiver": "reported by a caregiver",
    "inferred": "inferred from the recording, not reported",
    "seed": "SYNTHETIC DEMO DATA, not a real report",
    None: "no outcome recorded",
}

# Wide, plain buckets. Not clinical windows: these exist so a reader can see "mostly
# evenings" without being handed a number that looks like a finding.
_BUCKETS = (
    ("overnight", range(0, 6)),
    ("morning", range(6, 12)),
    ("afternoon", range(12, 17)),
    ("evening", range(17, 22)),
    ("late evening", range(22, 24)),
)


def _parse(ts: str):
    """Tolerant ISO 8601 parse. Returns None rather than raising on a malformed stamp."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _hour_of(ep: dict):
    """Local hour for an episode.

    Prefers context.hour_local, which is what the capturing client recorded on the device, and
    falls back to the hour in started_at. The fallback is worse: started_at may carry a
    different timezone than the room the recording happened in, and a passport that says
    "evening" about a morning is worse than one that says nothing.
    """
    ctx = ep.get("context") or {}
    if isinstance(ctx, dict) and isinstance(ctx.get("hour_local"), int):
        h = ctx["hour_local"]
        if 0 <= h <= 23:
            return h
    dt = _parse(ep.get("started_at"))
    return dt.hour if dt else None


def _bucket(hour) -> str | None:
    if hour is None:
        return None
    for name, rng in _BUCKETS:
        if hour in rng:
            return name
    return None


def build(subject_id: str, db_path: str | None = None) -> dict:
    """Assemble the passport for one subject as plain data.

    Returns a dict. Rendering is separate so the same structure can go to Markdown now and to
    a print or clinician layout later without the numbers being recomputed differently.
    """
    episodes = store.list_episodes(subject_id, db_path)
    usable = retrieve.episode_count(subject_id, db_path)

    stamps = [_parse(ep.get("started_at")) for ep in episodes]
    stamps = sorted(s for s in stamps if s is not None)
    span_days = None
    if len(stamps) >= 2:
        span_days = max(1, (stamps[-1] - stamps[0]).days + 1)

    provenance: dict[str, int] = {}
    for ep in episodes:
        key = ep.get("outcome_src") if ep.get("outcome_src") in _SRC_LABEL else None
        provenance[str(key)] = provenance.get(str(key), 0) + 1

    tally = retrieve.intervention_tally(subject_id, db_path)
    worked = [t for t in tally if t["worked_last"] > 0]
    unresolved = [t for t in tally if t["worked_last"] == 0 and t["tried"] > 0]

    buckets: dict[str, int] = {}
    for ep in episodes:
        name = _bucket(_hour_of(ep))
        if name:
            buckets[name] = buckets.get(name, 0) + 1
    ranked_buckets = sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))

    if usable == 0:
        status = STATUS_EMPTY
    elif usable < MIN_EPISODES_FOR_PASSPORT:
        status = STATUS_PROVISIONAL
    else:
        status = STATUS_READY

    return {
        "subject_id": subject_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "synthetic": provenance.get("seed", 0) > 0,
        "episodes": {
            "usable": usable,
            "total": len(episodes),
            "first": stamps[0].isoformat() if stamps else None,
            "last": stamps[-1].isoformat() if stamps else None,
            "span_days": span_days,
        },
        "provenance": provenance,
        "what_has_worked": worked,
        "tried_without_recorded_resolution": unresolved,
        "when_recorded": ranked_buckets,
        "limits": _limits(status, usable, provenance),
    }


def _limits(status: str, usable: int, provenance: dict) -> list[str]:
    """The caveats that must travel WITH the document, never in a separate place.

    A passport gets photographed and forwarded. Anything qualifying it has to survive being
    read alone, so these are part of the artifact rather than a UI disclaimer.
    """
    out = [
        "Every line in this document is a count of what a caregiver did and whether the "
        "crying stopped. None of it is a cause, a diagnosis, or a recommendation.",
        "An action listed as having worked is the action that was tried last before the "
        "crying stopped. A caregiver works through things in order and stops when one works, "
        "so the last one is the most likely to have mattered. It is not proof that it did.",
        "This document makes no comparison against what is typical for any age.",
    ]
    if status == STATUS_EMPTY:
        out.insert(0, "There is not one usable recording for this profile yet, so this "
                      "document has no content. It is not a finding of 'nothing works'.")
    elif status == STATUS_PROVISIONAL:
        out.insert(0, "PROVISIONAL: only %d usable recording%s. One or two recordings cannot "
                      "separate something that reliably helps from a coincidence, so treat "
                      "everything below as a note, not a pattern."
                      % (usable, "" if usable == 1 else "s"))
    if provenance.get("seed", 0):
        out.insert(0, "This document contains SYNTHETIC DEMO DATA (%d episode%s marked "
                      "'seed'). Those entries were generated for a demonstration and describe "
                      "nobody. Do not use this document for a real person."
                      % (provenance["seed"], "" if provenance["seed"] == 1 else "s"))
    if provenance.get("inferred", 0):
        out.append("%d outcome%s inferred from the recording rather than reported by a "
                   "caregiver. Inferred outcomes are weaker evidence and are labelled as such "
                   "wherever they appear." % (provenance["inferred"],
                                              " was" if provenance["inferred"] == 1 else "s were"))
    return out


def _plural(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def render_markdown(subject_id: str, db_path: str | None = None,
                    passport: dict | None = None) -> str:
    """Render the passport as Markdown.

    Accepts a prebuilt passport so a caller that already has one does not rebuild it and risk
    two documents in the same session disagreeing.
    """
    p = passport if passport is not None else build(subject_id, db_path)
    eps = p["episodes"]
    L: list[str] = []

    L.append("# Communication Passport: %s" % p["subject_id"])
    L.append("")
    if p["synthetic"]:
        L.append("> **WARNING: THIS DOCUMENT CONTAINS SYNTHETIC DEMO DATA.** It describes "
                 "nobody. Do not use it for a real person.")
        L.append("")
    if p["status"] == STATUS_PROVISIONAL:
        L.append("> **PROVISIONAL.** Built from %s. Too thin to call anything a pattern."
                 % _plural(eps["usable"], "usable recording"))
        L.append("")
    elif p["status"] == STATUS_EMPTY:
        L.append("> **NO USABLE RECORDINGS YET.** This is an empty document, not a finding "
                 "that nothing helps.")
        L.append("")

    L.append("Generated automatically from recorded interactions on %s."
             % p["generated_at"])
    L.append("")
    L.append("## What is recorded")
    L.append("")
    L.append("- Usable recordings: **%d** (of %d captured)" % (eps["usable"], eps["total"]))
    if eps["first"] and eps["last"]:
        L.append("- First recorded: %s" % eps["first"])
        L.append("- Most recent: %s" % eps["last"])
    if eps["span_days"]:
        L.append("- Spanning: %s" % _plural(eps["span_days"], "day"))
    if p["provenance"]:
        parts = ["%d %s" % (n, _SRC_LABEL[None if k == "None" else k])
                 for k, n in sorted(p["provenance"].items())]
        L.append("- Where the outcomes came from: %s" % "; ".join(parts))
    L.append("")

    L.append("## What has settled this person before")
    L.append("")
    if not p["what_has_worked"]:
        L.append("Nothing has been recorded as the last action before the crying stopped. "
                 "That means the record is silent, not that nothing helps.")
    else:
        L.append("Ordered by how often it was the last thing tried before the crying "
                 "stopped. These are counts, not instructions.")
        L.append("")
        L.append("| What the caregiver did | Last action before it stopped | Times tried |")
        L.append("|---|---|---|")
        for t in p["what_has_worked"]:
            L.append("| %s | %d | %d |" % (t["action"], t["worked_last"], t["tried"]))
    L.append("")

    if p["tried_without_recorded_resolution"]:
        L.append("## Tried, with no recorded resolution")
        L.append("")
        L.append("Listed because it is genuinely useful to the next caregiver to know what "
                 "has already been attempted. An entry here is NOT evidence that it does not "
                 "work: it may simply never have been the last thing tried.")
        L.append("")
        for t in p["tried_without_recorded_resolution"]:
            L.append("- %s (tried %d)" % (t["action"], t["tried"]))
        L.append("")

    if p["when_recorded"]:
        L.append("## When these recordings happened")
        L.append("")
        total = sum(n for _, n in p["when_recorded"])
        for name, n in p["when_recorded"]:
            L.append("- %s: %d of %d" % (name, n, total))
        L.append("")
        L.append("Time of day only. No claim is made that the time causes anything.")
        L.append("")

    L.append("## Limits of this document")
    L.append("")
    for line in p["limits"]:
        L.append("- %s" % line)
    L.append("")

    return "\n".join(L)


def _main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m src.passport",
        description="Export a subject's record as a Communication Passport.")
    ap.add_argument("subject_id")
    ap.add_argument("--db", default=None, help="database path (defaults to config)")
    ap.add_argument("--json", action="store_true", help="emit the raw structure instead")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(build(args.subject_id, args.db), indent=2))
    else:
        print(render_markdown(args.subject_id, args.db))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
