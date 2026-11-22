"""
Command line runner for the Music Recommender Simulation.

Run from the project root:
    python -m src.main                                        # example profile: pop / happy / 0.8
    python -m src.main --genre lofi --mood chill --energy 0.35 --acoustic
    python -m src.main --genre rock --mood intense --energy 0.9 --no-acoustic --k 3

Invalid input prints an error and exits with code 2.
"""

import argparse
import logging
import os
import sys
from typing import Optional, Sequence

from src.logging_config import setup_logging
from src.recommender import (
    LOW_CONFIDENCE_THRESHOLD,
    confidence,
    is_low_confidence,
    load_songs,
    profile_warnings,
    recommend_songs,
    weights_summary,
)

# Resolve data path relative to this file so the script works from any directory
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "songs.csv")

logger = logging.getLogger(__name__)


DEFAULT_PREFS = {"genre": "pop", "mood": "happy", "energy": 0.8}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend songs for a listener profile.")
    parser.add_argument("--genre", help="favorite genre, e.g. pop, lofi, rock")
    parser.add_argument("--mood", help="mood, e.g. happy, chill, intense, melancholic")
    parser.add_argument("--energy", help="target energy from 0 (calm) to 1 (intense)")
    parser.add_argument("--acoustic", action=argparse.BooleanOptionalAction, default=None,
                        help="--acoustic to prefer acoustic songs, --no-acoustic to prefer produced ones")
    parser.add_argument("--k", type=int, default=5, help="number of recommendations (default 5)")
    return parser.parse_args(argv)


def build_prefs(args: argparse.Namespace) -> dict:
    """Profile from the command line, or the example profile if none was given."""
    prefs = {}
    if args.genre is not None:
        prefs["genre"] = args.genre
    if args.mood is not None:
        prefs["mood"] = args.mood
    if args.energy is not None:
        try:
            prefs["energy"] = float(args.energy)
        except ValueError:
            prefs["energy"] = args.energy  # let the recommender's validation explain the problem
    if args.acoustic is not None:
        prefs["likes_acoustic"] = args.acoustic
    return prefs or dict(DEFAULT_PREFS)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    # Warnings are printed below as "Note:" lines, so the console log handler stays quiet;
    # everything is still written to logs/recommender.log.
    setup_logging(console_level=logging.CRITICAL)
    logger.info("Run started with weights %s", weights_summary())

    user_prefs = build_prefs(args)
    try:
        songs = load_songs(DATA_PATH)
        print(f"Loaded songs: {len(songs)}")
        recommendations = recommend_songs(user_prefs, songs, k=args.k)
    except ValueError as error:
        logger.error("Rejected input %s: %s", user_prefs, error)
        print(f"Error: {error}", file=sys.stderr)
        return 2

    print_recommendations(user_prefs, recommendations, profile_warnings(user_prefs, songs))
    return 0


def print_recommendations(user_prefs: dict, recommendations: list, warnings: list = ()) -> None:
    """Prints ranked recommendations with their score, confidence and the reasons behind it."""
    width = 60
    profile = " | ".join(f"{key}: {value}" for key, value in user_prefs.items())

    print()
    print("=" * width)
    print(f" Top {len(recommendations)} Recommendations")
    print(f" Profile -> {profile}")
    print("=" * width)

    for warning in warnings:
        print(f" Note: {warning}")
    if is_low_confidence(recommendations, user_prefs):
        print(
            f" Note: no strong matches (best match is under {LOW_CONFIDENCE_THRESHOLD:.0%} "
            "of a perfect score). Showing the closest songs."
        )

    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        print()
        print(f" {rank}. {song['title']}  ({song['artist']})")
        print(f"    Score: {score:.2f}  (match: {confidence(score, user_prefs):.0%})")
        print("    Reasons:")
        for reason in explanation.split("; "):
            print(f"      - {reason}")

    print()
    print("=" * width)


if __name__ == "__main__":
    sys.exit(main())
