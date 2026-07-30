#!/usr/bin/env python3
"""Replace typographic punctuation with plain ASCII across tracked text files.

WHY THIS EXISTS
The owner requires that no em dash appears anywhere in this project. Enforcing that by hand
does not hold, because every new doc reintroduces them. This is idempotent and safe to run
repeatedly, and it is the check to run before any handoff.

It also normalises smart quotes, en dashes, the Unicode minus and the ellipsis, all of which
cause the same class of problem: they render inconsistently in terminals, they break naive
greps, and in a code comment they carry no meaning a hyphen does not.

WHAT IT DELIBERATELY LEAVES ALONE
  * Arrows and box-drawing characters. Those are structural in the ASCII pipeline diagrams,
    where they carry meaning rather than typography.
  * Anything not tracked by git, and any binary or audio file.
  * Files owned by the other workstream, unless --all is passed. Rewriting a file that the
    other agent is editing right now produces a merge conflict for no benefit, so that agent
    runs this on its own files when it is between tasks.

USAGE
    python3 tools/scrub_dashes.py            # report only, changes nothing
    python3 tools/scrub_dashes.py --apply    # rewrite the files this workstream owns
    python3 tools/scrub_dashes.py --apply --all
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Straight replacements. Order matters only in that the em dash rule below runs first, since a
# spaced em dash becomes " - " while a bare one becomes "-".
SIMPLE = {
    "\u2013": "-",   # en dash, e.g. a "6-12 episodes" range
    "\u2212": "-",   # Unicode minus, which appears in the dB figures
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",   # non-breaking space, invisible and it breaks greps
}
EM_DASH = "\u2014"

# Owned by the other workstream. See AGENTS.md: these are never edited from this side.
SKIP = {
    "src/speech.py",
    "src/session.py",
    "src/cli.py",
    "src/render.py",
    "src/diary.py",
    "web/app.js",                  # the web client behaviour belongs to the other workstream
    "tools/scrub_dashes.py",       # the table above would rewrite itself
    "tools/anonymize_history.sh",
}
SKIP_PREFIX = ("spikes/", "tests/test_product_", "docs/ACCEPTANCE")

TEXT_SUFFIX = {".py", ".md", ".html", ".css", ".js", ".sql", ".txt", ".json", ".sh", ".yml"}


def tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.splitlines() if Path(p).suffix in TEXT_SUFFIX]


def scrub_line(line: str) -> str:
    # A spaced em dash is nearly always an appositive break, so a spaced hyphen preserves the
    # sentence. A bare one is either a table placeholder or a compound, where a hyphen is right.
    out = re.sub(rf"[ \t]*{EM_DASH}[ \t]*", " - ", line)
    out = out.replace(EM_DASH, "-")
    # The rule above can leave " - " flush against the left margin, which in Markdown reads as a
    # list bullet and silently changes the document structure. Only reachable on a line that
    # actually held an em dash, which is why this is applied per line rather than to the whole
    # file: a genuine nested list item is also written " - " and must not be de-indented.
    return re.sub(r"^ - ", "- ", out)


def scrub(text: str) -> str:
    text = "\n".join(
        scrub_line(ln) if EM_DASH in ln else ln
        for ln in text.split("\n")
    )
    for bad, good in SIMPLE.items():
        text = text.replace(bad, good)
    return text


def main() -> int:
    apply = "--apply" in sys.argv
    every = "--all" in sys.argv

    changed, skipped = [], []
    for rel in tracked_text_files():
        if not every and (rel in SKIP or rel.startswith(SKIP_PREFIX)):
            path = REPO / rel
            try:
                if any(ord(c) > 127 for c in io.open(path, encoding="utf-8").read()):
                    skipped.append(rel)
            except (UnicodeDecodeError, OSError):
                pass
            continue

        path = REPO / rel
        try:
            original = io.open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue

        cleaned = scrub(original)
        if cleaned == original:
            continue
        changed.append(rel)
        if apply:
            io.open(path, "w", encoding="utf-8").write(cleaned)

    verb = "rewrote" if apply else "would rewrite"
    print(f"{verb} {len(changed)} file(s)")
    for rel in changed:
        print(f"  {rel}")
    if skipped:
        print(f"\nleft for the other workstream ({len(skipped)}); run with --all to include them:")
        for rel in skipped:
            print(f"  {rel}")
    if not apply and changed:
        print("\nreport only. re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
