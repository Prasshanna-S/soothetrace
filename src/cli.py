"""Operator CLI for the interaction-memory prototype."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from . import diary, render, retrieve, session, store
except ImportError:
    import diary
    import render
    import retrieve
    import session
    import store

logger = logging.getLogger(__name__)


def _has_recording_consent(subject_id: str) -> bool:
    """Require explicit consent before this subject's first audio recording."""
    if store.list_episodes(subject_id):
        return True
    try:
        answer = input(
            "Audio only; this app never records video. Do all audible adults "
            "consent to this recording? [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().casefold() in {"y", "yes"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="interaction-memory")
    subcommands = parser.add_subparsers(dest="command", required=True)

    record_parser = subcommands.add_parser("record", help="capture a new audio episode")
    record_parser.add_argument("subject_id")
    record_parser.add_argument("--seconds", type=float)

    finish_parser = subcommands.add_parser("finish", help="finalize a recorded episode")
    finish_parser.add_argument("subject_id")
    finish_parser.add_argument("audio_path")
    finish_parser.add_argument("--answer")

    history_parser = subcommands.add_parser("history", help="show prior episodes")
    history_parser.add_argument("subject_id")

    diary_parser = subcommands.add_parser("diary", help="generate a printable cry diary")
    diary_parser.add_argument("subject_id")
    diary_parser.add_argument("--output", help="write Markdown to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and return a process exit code."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "record":
            if not _has_recording_consent(args.subject_id):
                print(
                    "Explicit audio-recording consent is required.",
                    file=sys.stderr,
                )
                return 1
            path = session.record(args.subject_id, seconds=args.seconds)
            if not path:
                print("Recording failed.", file=sys.stderr)
                return 1
            print(path)
            return 0
        if args.command == "finish":
            answer = args.answer
            if answer is None:
                try:
                    answer = input("What stopped it? (Enter to skip): ").strip() or None
                except EOFError:
                    answer = None
            episode = session.finish(args.subject_id, args.audio_path, answer)
            if not episode or not episode.get("id"):
                print("Episode could not be finalized.", file=sys.stderr)
                return 1
            print(f"Saved episode #{episode['id']}.")
            matches = retrieve.find_similar(
                args.subject_id,
                episode.get("fingerprint") or [],
                exclude_episode_id=episode["id"],
            )
            count = retrieve.episode_count(args.subject_id)
            print(render.recall_card(matches, count))
            guidance = render.caregiver_guidance(
                store.list_episodes(args.subject_id)
            )
            if guidance:
                print(f"\n{guidance}")
            return 0
        if args.command == "history":
            episodes = store.list_episodes(args.subject_id)
            if not episodes:
                print("No episodes recorded yet.")
                return 0
            for episode in episodes:
                source = (
                    "synthetic seed"
                    if episode.get("outcome_src") == "seed"
                    else episode.get("outcome_src") or "no outcome supplied"
                )
                outcome = episode.get("outcome") or "No outcome recorded"
                worked = episode.get("worked")
                status = "worked" if worked is True else "did not work" if worked is False else ""
                print(
                    f"#{episode.get('id')} {episode.get('started_at', '')} - "
                    f"{outcome} ({source}{', ' + status if status else ''})"
                )
            return 0
        if args.command == "diary":
            markdown = diary.render_markdown(args.subject_id)
            if args.output:
                output_path = Path(args.output).expanduser()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(markdown, encoding="utf-8")
                print(output_path)
            else:
                print(markdown)
            return 0
    except Exception:
        logger.exception("Command failed")
        print("Command failed safely; no data was lost.", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
