"""Auto-generated cry diary - task 2.8. Owned by acoustics workstream.

WHY THIS IS THE T2 DELIVERABLE: a cry/fuss diary is currently a **manual paper instrument**
in colic assessment - the parent writes down every episode by hand, for days, while
exhausted. Nobody generates it automatically. This is the "health over time" payload and the
single most obviously useful artifact the system can hand to a clinician
(docs/POSITIONING.md §T2, docs/RESEARCH.md §3d).

It is also pure arithmetic over what the caregiver reported. Nothing here is inferred, so
nothing here can hallucinate.

⚠️ LIABILITY CONSTRAINTS BAKED IN (docs/LIABILITY.md §1):
  * No cause labels. Ever. We report what she said, not what it meant.
  * No verdict against population norms. Published ranges are shown as clearly-attributed
    CONTEXT with no comparison computed, because "your baby cries more than normal" is a
    disease-adjacent claim and we are a general wellness product.
  * `outcome_src` is always surfaced, and 'seed' is rendered as visibly synthetic.

No network calls (docs/CONTRACTS.md rule 7).
"""
from __future__ import annotations

import collections
from datetime import datetime

try:
    from . import retrieve, store
except ImportError:
    import retrieve
    import store

# Published reference context, shown WITHOUT any comparison or verdict.
# Meta-analysis of 28 diary studies (J Pediatrics) - see docs/RESEARCH.md §1.
NORM_NOTE = (
    "For context only, not a comparison: a meta-analysis of 28 diary studies found mean "
    "fuss/cry duration of 117-133 min/day over the first six weeks, falling to about "
    "68 min/day by 10-12 weeks."
)

_SRC_LABEL = {
    "caregiver": "you told us",
    "inferred": "inferred from the recording",
    "seed": "SYNTHETIC DEMO DATA",
}


def _parse(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def daily_summary(subject_id: str, db_path: str | None = None) -> list[dict]:
    """One row per calendar day, oldest first.

    Returns [{date, episodes, total_minutes, resolved, unresolved, hours: [int]}]
    """
    days: dict[str, dict] = {}
    for ep in store.list_episodes(subject_id, db_path):
        dt = _parse(ep.get("started_at") or "")
        if dt is None:
            continue
        key = dt.date().isoformat()
        d = days.setdefault(key, {"date": key, "episodes": 0, "total_minutes": 0.0,
                                  "resolved": 0, "unresolved": 0, "hours": []})
        d["episodes"] += 1
        d["total_minutes"] += (ep.get("duration_s") or 0.0) / 60.0
        d["hours"].append(dt.hour)
        if ep.get("worked"):
            d["resolved"] += 1
        elif ep.get("worked") is not None:
            d["unresolved"] += 1
    return [days[k] for k in sorted(days)]


def hourly_distribution(subject_id: str, db_path: str | None = None) -> list[int]:
    """Episode counts by hour of day, 0-23.

    Infant crying has a documented circadian component with an evening peak around 7-8pm
    (docs/RESEARCH.md §1), so this is the view most likely to show a real pattern - and it
    only exists longitudinally, which is the point of the track.
    """
    counts = [0] * 24
    for ep in store.list_episodes(subject_id, db_path):
        dt = _parse(ep.get("started_at") or "")
        if dt is not None:
            counts[dt.hour] += 1
    return counts


def _sparkline(counts: list[int]) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    hi = max(counts) or 1
    return "".join(blocks[min(len(blocks) - 1, round(c / hi * (len(blocks) - 1)))]
                   for c in counts)


def render_markdown(subject_id: str, db_path: str | None = None) -> str:
    """The diary, as markdown. Safe to print, save, or hand to a clinician."""
    eps = store.list_episodes(subject_id, db_path)
    if not eps:
        return f"# Cry diary - {subject_id}\n\nNo episodes recorded yet.\n"

    days = daily_summary(subject_id, db_path)
    hours = hourly_distribution(subject_id, db_path)
    tally = retrieve.intervention_tally(subject_id, db_path)
    srcs = {ep.get("outcome_src") for ep in eps if ep.get("outcome_src")}

    L = [f"# Cry diary - {subject_id}", ""]
    if "seed" in srcs:
        L += ["> ⚠️ **This diary contains synthetic demo data** (`outcome_src=seed`). "
              "It is not a record of real events.", ""]
    L += [f"{len(eps)} episodes across {len(days)} days "
          f"({days[0]['date']} → {days[-1]['date']}).", ""]

    L += ["## By day", "",
          "| Date | Episodes | Recorded min | Settled | Did not settle |",
          "|---|---|---|---|---|"]
    for d in days:
        L.append(f"| {d['date']} | {d['episodes']} | {d['total_minutes']:.1f} | "
                 f"{d['resolved']} | {d['unresolved']} |")
    L += ["",
          "*\"Recorded min\" is time the microphone was running, which is not the same as "
          "total time spent crying - only episodes the caregiver chose to record appear here.*",
          ""]

    L += ["## By hour of day", "",
          "```",
          "00              06              12              18            23",
          _sparkline(hours),
          "```",
          ""]
    peak = max(range(24), key=lambda h: hours[h])
    if hours[peak]:
        L += [f"Most recorded episodes begin around **{peak:02d}:00** "
              f"({hours[peak]} of {len(eps)}).", ""]

    if tally:
        L += ["## What was tried, and what settled things", "",
              "| Action | Times tried | Times it settled |", "|---|---|---|"]
        for t in tally:
            L.append(
                f"| {t['action']} | {t['tried']} | {t['worked_last']} |"
            )
        L += ["",
              "*Counts come from what the caregiver reported after each recording. When an "
              "episode settled, only the final action is credited because that is where the "
              "sequence stopped. This is not causal proof; only repetition can reveal a "
              "useful personal pattern.*",
              ""]

    L += ["## Provenance", ""]
    for s in sorted(srcs):
        L.append(f"- Outcomes recorded as **{s}** - {_SRC_LABEL.get(s, s)}")
    L += ["", "## Context", "", NORM_NOTE, "",
          "---", "",
          "This diary is a record of what you observed and did. It does not identify why "
          "your baby was crying, and it is not a diagnosis. If you are worried about your "
          "baby's crying, consider sharing this with your pediatrician.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    subject = sys.argv[1] if len(sys.argv) > 1 else "baby-demo"
    out = render_markdown(subject)
    print(out)
    if "--save" in sys.argv:
        path = f"data/diary-{subject}.md"
        with open(path, "w") as fh:
            fh.write(out)
        print(f"\nsaved -> {path}", file=sys.stderr)
