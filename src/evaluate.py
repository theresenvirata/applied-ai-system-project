"""
Reliability, diversity and consistency evaluation for the music recommender.

Run from the project root:
    python -m src.evaluate                 # print the report
    python -m src.evaluate --json logs/eval_report.json   # also save it as JSON

What it does:
  1. Builds a fixed grid of user profiles (every genre x one mood per mood family x
     3 energy levels x acoustic yes/no = 360 profiles). No randomness, no hand-picking.
  2. Measures diversity inside each top-k list and exposure across all users.
  3. Measures fairness: do fans of every genre get served equally well?
  4. Compares against a random recommender (fixed seed) and against the raw ranking
     without the diversity guardrail.
  5. Checks consistency: repeated runs, shuffled catalog order, reloading the CSV,
     differently formatted input, and small changes to energy.
  6. Applies pass/fail thresholds. Exits with code 1 if any check fails.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import random
import sys
from collections import Counter
from typing import Dict, List, Sequence

from src.logging_config import setup_logging
from src.recommender import (
    MOOD_FAMILIES,
    confidence,
    load_songs,
    recommend_songs,
    score_song,
    weights_summary,
)

logger = logging.getLogger(__name__)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "songs.csv")

K = 5
SEED = 42                      # fixed seed for the random baseline and catalog shuffles
ENERGY_LEVELS = (0.2, 0.5, 0.8)
MOOD_PROBES = ("chill", "intense", "happy", "nostalgic")  # one mood from each family
SHUFFLE_RUNS = 5
REPEAT_RUNS = 3
ENERGY_NUDGE = 0.02

# Pass/fail thresholds. These were set before looking at results, not tuned to pass.
THRESHOLDS = {
    "max_artist_repeats": 0,         # no artist twice in one list
    "min_unique_genre_ratio": 0.60,  # on average at least 3 of 5 songs from different genres
    "min_catalog_coverage": 0.80,    # at least 80% of songs are recommended to someone
    "exposure_ratio_range": (0.5, 2.0),  # no genre over- or under-exposed by more than 2x
    "min_genre_hit_rate": 0.50,      # every genre's fans see their genre in at least half their lists
    "min_stability_overlap": 0.80,   # nudging energy by 0.02 keeps 4 of 5 songs on average
}

assert all(mood in set().union(*MOOD_FAMILIES.values()) for mood in MOOD_PROBES)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def build_profiles(songs: List[Dict]) -> List[Dict]:
    """Every genre in the catalog x one mood per family x energy levels x acoustic preference."""
    genres = sorted({song["genre"] for song in songs})
    return [
        {"genre": genre, "mood": mood, "energy": energy, "likes_acoustic": acoustic}
        for genre in genres
        for mood in MOOD_PROBES
        for energy in ENERGY_LEVELS
        for acoustic in (True, False)
    ]


def run_all(profiles: List[Dict], songs: List[Dict], k: int = K, **kwargs) -> List[List[Dict]]:
    """Returns the recommended songs (without scores) for every profile."""
    return [[song for song, _, _ in recommend_songs(p, songs, k=k, **kwargs)] for p in profiles]


# ---------------------------------------------------------------------------
# Diversity within one list
# ---------------------------------------------------------------------------

def unique_genre_ratio(rec: Sequence[Dict]) -> float:
    """Distinct genres / list length. 1.0 = every song from a different genre."""
    return len({s["genre"] for s in rec}) / len(rec) if rec else 0.0


def artist_repeats(rec: Sequence[Dict]) -> int:
    """How many songs share an artist with a higher-ranked song in the same list."""
    return len(rec) - len({s["artist"] for s in rec})


def genre_entropy(rec: Sequence[Dict]) -> float:
    """Shannon entropy of the genres in the list, scaled to 0-1 (1 = perfectly even spread)."""
    if len(rec) < 2:
        return 0.0
    counts = Counter(s["genre"] for s in rec)
    total = len(rec)
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values())
    return entropy / math.log(total)


def intra_list_distance(rec: Sequence[Dict]) -> float:
    """
    Average difference between every pair of songs in the list (0-1).
    Half is genre (different = 1), half is energy gap, so it rewards songs that
    differ in sound, not only in label.
    """
    pairs = [(a, b) for i, a in enumerate(rec) for b in rec[i + 1:]]
    if not pairs:
        return 0.0
    return sum(
        0.5 * (a["genre"] != b["genre"]) + 0.5 * abs(a["energy"] - b["energy"]) for a, b in pairs
    ) / len(pairs)


def list_metrics(all_recs: List[List[Dict]]) -> Dict[str, float]:
    n = len(all_recs)
    return {
        "avg_unique_genre_ratio": sum(map(unique_genre_ratio, all_recs)) / n,
        "avg_genre_entropy": sum(map(genre_entropy, all_recs)) / n,
        "avg_intra_list_distance": sum(map(intra_list_distance, all_recs)) / n,
        "avg_artist_repeats": sum(map(artist_repeats, all_recs)) / n,
        "max_artist_repeats": max(map(artist_repeats, all_recs)),
        "lists_with_artist_repeat": sum(artist_repeats(r) > 0 for r in all_recs) / n,
    }


# ---------------------------------------------------------------------------
# Exposure across all users
# ---------------------------------------------------------------------------

def position_weight(rank: int) -> float:
    """Rank 1 counts most: 1.0, 0.63, 0.5, 0.43, 0.39, ..."""
    return 1 / math.log2(rank + 1)


def catalog_coverage(all_recs: List[List[Dict]], songs: List[Dict]) -> float:
    shown = {s["id"] for rec in all_recs for s in rec}
    return len(shown) / len(songs)


def genre_exposure_ratios(all_recs: List[List[Dict]], songs: List[Dict]) -> Dict[str, float]:
    """
    Position-weighted share of recommendations for each genre, divided by that genre's
    share of the catalog. 1.0 = fair; >1 = over-recommended; <1 = under-recommended.
    """
    exposure: Counter = Counter()
    for rec in all_recs:
        for rank, song in enumerate(rec, start=1):
            exposure[song["genre"]] += position_weight(rank)
    total_exposure = sum(exposure.values())
    catalog = Counter(s["genre"] for s in songs)
    return {
        genre: (exposure[genre] / total_exposure) / (count / len(songs))
        for genre, count in sorted(catalog.items())
    }


def gini(values: Sequence[float]) -> float:
    """0 = every song shown equally often; close to 1 = a few songs get almost all exposure."""
    values = sorted(values)
    n, total = len(values), sum(values)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(values))
    return (2 * weighted) / (n * total) - (n + 1) / n


def song_appearances(all_recs: List[List[Dict]], songs: List[Dict]) -> Counter:
    counts = Counter({s["id"]: 0 for s in songs})
    counts.update(s["id"] for rec in all_recs for s in rec)
    return counts


# ---------------------------------------------------------------------------
# Fairness by favorite genre
# ---------------------------------------------------------------------------

def fairness_by_genre(profiles: List[Dict], songs: List[Dict], k: int = K) -> Dict[str, Dict[str, float]]:
    """
    For the fans of each genre:
      avg_top1_match  - average #1 score as a share of the best possible score
      genre_hit_rate  - share of their lists with at least one song in their genre
    """
    stats: Dict[str, Dict[str, list]] = {}
    for profile in profiles:
        results = recommend_songs(profile, songs, k=k)
        row = stats.setdefault(profile["genre"], {"top1": [], "hit": []})
        row["top1"].append(confidence(results[0][1], profile))
        row["hit"].append(any(song["genre"] == profile["genre"] for song, _, _ in results))
    return {
        genre: {
            "avg_top1_match": sum(row["top1"]) / len(row["top1"]),
            "genre_hit_rate": sum(row["hit"]) / len(row["hit"]),
        }
        for genre, row in sorted(stats.items())
    }


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def random_baseline(profiles: List[Dict], songs: List[Dict], k: int = K, seed: int = SEED) -> List[List[Dict]]:
    """A recommender that ignores the profile. Fixed seed, so it is reproducible too."""
    rng = random.Random(seed)
    return [rng.sample(songs, k) for _ in profiles]


def avg_match(profiles: List[Dict], all_recs: List[List[Dict]]) -> float:
    """Average match (score / best possible) of every recommended song. Higher = more relevant."""
    values = [
        confidence(score_song(p, s)[0], p) for p, rec in zip(profiles, all_recs) for s in rec
    ]
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# Consistency
# ---------------------------------------------------------------------------

def fingerprint(profiles: List[Dict], songs: List[Dict], k: int = K) -> str:
    """
    SHA-256 of every profile's results (song ids and rounded scores). Two runs with the
    same fingerprint gave exactly the same answers. Compare it across machines or commits.
    """
    payload = []
    for profile in profiles:
        results = recommend_songs(profile, songs, k=k)
        payload.append([profile, [[s["id"], round(score, 6)] for s, score, _ in results]])
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def check_repeat_runs(profiles, songs, runs: int = REPEAT_RUNS) -> Dict:
    prints = {fingerprint(profiles, songs) for _ in range(runs)}
    return {"passed": len(prints) == 1, "detail": f"{runs} runs, {len(prints)} distinct result set(s)"}


def check_order_independence(profiles, songs, shuffles: int = SHUFFLE_RUNS, seed: int = SEED) -> Dict:
    expected = fingerprint(profiles, songs)
    rng = random.Random(seed)
    mismatches = 0
    for _ in range(shuffles):
        shuffled = list(songs)
        rng.shuffle(shuffled)
        mismatches += fingerprint(profiles, shuffled) != expected
    return {"passed": mismatches == 0, "detail": f"{shuffles} shuffled catalogs, {mismatches} differed"}


def check_reload(profiles, songs, csv_path: str) -> Dict:
    same = fingerprint(profiles, load_songs(csv_path)) == fingerprint(profiles, songs)
    return {"passed": same, "detail": "reloaded CSV gives identical results" if same else "results changed after reload"}


def input_variants(profile: Dict) -> List[Dict]:
    """The same request written differently: case, spaces, and UserProfile-style keys."""
    return [
        {**profile, "genre": profile["genre"].upper(), "mood": profile["mood"].title()},
        {**profile, "genre": f"  {profile['genre']} ", "mood": f" {profile['mood']}  "},
        {
            "favorite_genre": profile["genre"],
            "favorite_mood": profile["mood"],
            "target_energy": profile["energy"],
            "likes_acoustic": profile["likes_acoustic"],
        },
    ]


def check_input_normalization(profiles, songs, k: int = K) -> Dict:
    def ids(p):
        return [s["id"] for s, _, _ in recommend_songs(p, songs, k=k)]

    total = failures = 0
    for profile in profiles:
        expected = ids(profile)
        for variant in input_variants(profile):
            total += 1
            failures += ids(variant) != expected
    return {"passed": failures == 0, "detail": f"{total} reformatted inputs, {failures} gave different results"}


def check_stability(profiles, songs, k: int = K, nudge: float = ENERGY_NUDGE) -> Dict:
    """Small changes to energy should not reshuffle the whole list."""
    def ids(p):
        return {s["id"] for s, _, _ in recommend_songs(p, songs, k=k)}

    overlaps = []
    for profile in profiles:
        base = ids(profile)
        for delta in (-nudge, nudge):
            energy = min(1.0, max(0.0, profile["energy"] + delta))
            overlaps.append(len(base & ids({**profile, "energy": energy})) / k)
    avg = sum(overlaps) / len(overlaps)
    passed = avg >= THRESHOLDS["min_stability_overlap"]
    return {
        "passed": passed,
        "value": avg,
        "detail": f"energy +/-{nudge}: avg {avg:.0%} of songs kept, worst case {min(overlaps):.0%}",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def run_evaluation(songs: List[Dict], csv_path: str = DATA_PATH, k: int = K) -> Dict:
    profiles = build_profiles(songs)
    logger.info("Evaluation started: %d profiles, k=%d, weights %s", len(profiles), k, weights_summary())

    guarded = run_all(profiles, songs, k)
    raw = run_all(profiles, songs, k, max_per_artist=None)
    rand = random_baseline(profiles, songs, k)

    systems = {}
    for name, recs in (("guardrailed", guarded), ("raw_ranking", raw), ("random_baseline", rand)):
        metrics = list_metrics(recs)
        metrics["catalog_coverage"] = catalog_coverage(recs, songs)
        metrics["gini_song_exposure"] = gini(list(song_appearances(recs, songs).values()))
        metrics["avg_match"] = avg_match(profiles, recs)
        systems[name] = metrics

    exposure = genre_exposure_ratios(guarded, songs)
    fairness = fairness_by_genre(profiles, songs, k)
    appearances = song_appearances(guarded, songs)
    by_id = {s["id"]: s for s in songs}
    never_shown = sorted(by_id[i]["title"] for i, n in appearances.items() if n == 0)
    most_shown = [
        {"title": by_id[i]["title"], "share_of_users": n / len(profiles)}
        for i, n in sorted(appearances.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]

    consistency = {
        "repeat_runs": check_repeat_runs(profiles, songs),
        "catalog_order_independence": check_order_independence(profiles, songs),
        "reload_from_disk": check_reload(profiles, songs, csv_path),
        "input_normalization": check_input_normalization(profiles, songs, k),
        "small_input_stability": check_stability(profiles, songs, k),
    }

    g = systems["guardrailed"]
    low, high = THRESHOLDS["exposure_ratio_range"]
    min_hit_genre = min(fairness, key=lambda genre: fairness[genre]["genre_hit_rate"])
    checks = [
        ("No artist repeats in any list", g["max_artist_repeats"] <= THRESHOLDS["max_artist_repeats"],
         f"max repeats = {g['max_artist_repeats']}"),
        ("Genre variety per list", g["avg_unique_genre_ratio"] >= THRESHOLDS["min_unique_genre_ratio"],
         f"avg unique-genre ratio = {g['avg_unique_genre_ratio']:.2f} (need >= {THRESHOLDS['min_unique_genre_ratio']})"),
        ("Catalog coverage", g["catalog_coverage"] >= THRESHOLDS["min_catalog_coverage"],
         f"{g['catalog_coverage']:.0%} of songs shown (need >= {THRESHOLDS['min_catalog_coverage']:.0%})"),
        ("Balanced genre exposure", all(low <= r <= high for r in exposure.values()),
         f"ratios {min(exposure.values()):.2f}-{max(exposure.values()):.2f} (need {low}-{high})"),
        ("Every genre's fans served", fairness[min_hit_genre]["genre_hit_rate"] >= THRESHOLDS["min_genre_hit_rate"],
         f"lowest genre hit rate = {fairness[min_hit_genre]['genre_hit_rate']:.0%} ({min_hit_genre}) "
         f"(need >= {THRESHOLDS['min_genre_hit_rate']:.0%})"),
    ]
    checks += [(f"Consistency: {name.replace('_', ' ')}", c["passed"], c["detail"]) for name, c in consistency.items()]

    report = {
        "settings": {"profiles": len(profiles), "k": k, "songs": len(songs), "seed": SEED, "weights": weights_summary()},
        "fingerprint": fingerprint(profiles, songs, k),
        "systems": systems,
        "genre_exposure_ratio": exposure,
        "fairness_by_genre": fairness,
        "most_shown": most_shown,
        "never_shown": never_shown,
        "consistency": consistency,
        "checks": [{"name": n, "passed": bool(p), "detail": d} for n, p, d in checks],
    }
    report["all_passed"] = all(c["passed"] for c in report["checks"])

    for check in report["checks"]:
        log = logger.info if check["passed"] else logger.warning
        log("Check %s: %s (%s)", "PASS" if check["passed"] else "FAIL", check["name"], check["detail"])
    logger.info("Evaluation finished: fingerprint %s, all passed = %s", report["fingerprint"], report["all_passed"])
    return report


def print_report(report: Dict) -> None:
    width = 72
    s = report["settings"]
    print("=" * width)
    print(" Recommender Evaluation Report")
    print(f" {s['profiles']} profiles | {s['songs']} songs | top {s['k']} | seed {s['seed']}")
    print(f" Weights: {s['weights']}")
    print("=" * width)

    print("\n Diversity and relevance (averaged over all profiles)")
    rows = [
        ("Unique-genre ratio (1 = all different)", "avg_unique_genre_ratio", "{:.2f}"),
        ("Genre entropy (1 = even spread)", "avg_genre_entropy", "{:.2f}"),
        ("Intra-list distance (0-1)", "avg_intra_list_distance", "{:.2f}"),
        ("Lists with a repeated artist", "lists_with_artist_repeat", "{:.0%}"),
        ("Catalog coverage", "catalog_coverage", "{:.0%}"),
        ("Gini of song exposure (0 = equal)", "gini_song_exposure", "{:.2f}"),
        ("Avg match of recommended songs", "avg_match", "{:.0%}"),
    ]
    names = ("guardrailed", "raw_ranking", "random_baseline")
    print(f"   {'Metric':<40}{'Guarded':>10}{'Raw':>10}{'Random':>10}")
    for label, key, fmt in rows:
        values = "".join(f"{fmt.format(report['systems'][n][key]):>10}" for n in names)
        print(f"   {label:<40}{values}")

    print("\n Genre exposure ratio (1.0 = fair share, position-weighted)")
    for genre, ratio in sorted(report["genre_exposure_ratio"].items(), key=lambda item: -item[1]):
        bar = "#" * round(ratio * 10)
        print(f"   {genre:<12}{ratio:5.2f}  {bar}")

    print("\n Fairness by favorite genre")
    print(f"   {'Genre':<12}{'Top-1 match':>12}{'Genre hit rate':>16}")
    for genre, row in report["fairness_by_genre"].items():
        print(f"   {genre:<12}{row['avg_top1_match']:>12.0%}{row['genre_hit_rate']:>16.0%}")

    print("\n Most recommended songs")
    for item in report["most_shown"]:
        print(f"   {item['title']:<28} top {s['k']} for {item['share_of_users']:.0%} of profiles")
    print(f"   Never recommended: {', '.join(report['never_shown']) or 'none'}")

    print("\n Checks")
    for check in report["checks"]:
        print(f"   [{'PASS' if check['passed'] else 'FAIL'}] {check['name']}: {check['detail']}")

    print(f"\n Result fingerprint: {report['fingerprint'][:16]}...")
    print(f" Overall: {'ALL CHECKS PASSED' if report['all_passed'] else 'SOME CHECKS FAILED'}")
    print("=" * width)


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate recommender diversity, fairness and consistency.")
    parser.add_argument("--data", default=DATA_PATH, help="path to songs.csv")
    parser.add_argument("--k", type=int, default=K, help="recommendations per profile (default 5)")
    parser.add_argument("--json", help="also write the full report to this JSON file")
    args = parser.parse_args(argv)

    setup_logging()
    songs = load_songs(args.data)
    report = run_evaluation(songs, csv_path=args.data, k=args.k)
    print_report(report)

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f" Full report saved to {args.json}")

    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
