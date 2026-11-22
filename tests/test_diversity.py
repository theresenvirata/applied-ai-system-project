"""
Tests for the diversity and fairness metrics themselves, plus the catalog balance rule.

These check that the measuring tools are correct. Whether the recommender *passes*
the diversity thresholds is reported by `python -m src.evaluate`, not asserted here.
"""

import os
from collections import Counter

import pytest

from src import evaluate
from src.recommender import load_songs

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "songs.csv")


def song(i, genre, artist="A", energy=0.5):
    return {"id": i, "title": f"S{i}", "artist": artist, "genre": genre, "mood": "happy",
            "energy": energy, "acousticness": 0.5}


SAME = [song(i, "pop", artist="A") for i in range(1, 6)]
MIXED = [song(i, g, artist=f"A{i}") for i, g in enumerate(["pop", "rock", "jazz", "folk", "edm"], start=1)]


@pytest.fixture(scope="module")
def songs():
    return load_songs(DATA_PATH)


def test_every_genre_has_at_least_three_songs(songs):
    counts = Counter(s["genre"] for s in songs)
    thin = {genre: n for genre, n in counts.items() if n < 3}
    assert not thin, f"genres with fewer than 3 songs: {thin}"


def test_unique_genre_ratio():
    assert evaluate.unique_genre_ratio(SAME) == 0.2
    assert evaluate.unique_genre_ratio(MIXED) == 1.0


def test_artist_repeats():
    assert evaluate.artist_repeats(SAME) == 4
    assert evaluate.artist_repeats(MIXED) == 0


def test_genre_entropy_ranges_from_zero_to_one():
    assert evaluate.genre_entropy(SAME) == pytest.approx(0.0)
    assert evaluate.genre_entropy(MIXED) == pytest.approx(1.0)


def test_intra_list_distance_counts_genre_and_energy():
    assert evaluate.intra_list_distance(SAME) == 0.0
    assert evaluate.intra_list_distance([song(1, "pop", energy=0.0), song(2, "rock", energy=1.0)]) == 1.0


def test_gini():
    assert evaluate.gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert evaluate.gini([0, 0, 0, 10]) == pytest.approx(0.75)


def test_exposure_ratio_is_one_when_exposure_matches_catalog():
    catalog = [song(1, "pop"), song(2, "rock")]
    # Each genre is ranked #1 exactly once, so exposure matches the 50/50 catalog
    ratios = evaluate.genre_exposure_ratios([[catalog[0], catalog[1]], [catalog[1], catalog[0]]], catalog)
    assert ratios == pytest.approx({"pop": 1.0, "rock": 1.0})


def test_catalog_coverage():
    catalog = MIXED
    assert evaluate.catalog_coverage([catalog[:2], catalog[1:3]], catalog) == pytest.approx(0.6)


def test_profile_grid_covers_every_genre(songs):
    profiles = evaluate.build_profiles(songs)
    assert {p["genre"] for p in profiles} == {s["genre"] for s in songs}
    assert len(profiles) == len({s["genre"] for s in songs}) * 4 * 3 * 2


def test_random_baseline_is_reproducible(songs):
    profiles = evaluate.build_profiles(songs)[:20]
    first = evaluate.random_baseline(profiles, songs)
    assert evaluate.random_baseline(profiles, songs) == first


def test_full_evaluation_report_has_expected_shape(songs):
    report = evaluate.run_evaluation(songs, csv_path=DATA_PATH)
    assert set(report["systems"]) == {"guardrailed", "raw_ranking", "random_baseline"}
    assert set(report["genre_exposure_ratio"]) == {s["genre"] for s in songs}
    assert 0.0 <= report["systems"]["guardrailed"]["catalog_coverage"] <= 1.0
    assert len(report["fingerprint"]) == 64
    # The artist guardrail must hold even if other checks fail
    assert report["systems"]["guardrailed"]["max_artist_repeats"] == 0
