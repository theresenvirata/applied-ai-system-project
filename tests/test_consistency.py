"""Consistency tests: the recommender must give the same answer to the same question."""

import os
import random

import pytest

from src import evaluate
from src.recommender import load_songs, rank_songs, recommend_songs

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "songs.csv")


@pytest.fixture(scope="module")
def songs():
    return load_songs(DATA_PATH)


@pytest.fixture(scope="module")
def profiles(songs):
    return evaluate.build_profiles(songs)


def test_same_input_gives_same_output(songs):
    prefs = {"genre": "rock", "mood": "intense", "energy": 0.9, "likes_acoustic": False}
    first = recommend_songs(prefs, songs, k=5)
    for _ in range(5):
        assert recommend_songs(prefs, songs, k=5) == first


def test_catalog_order_does_not_change_results(songs):
    prefs = {"genre": "folk", "mood": "nostalgic", "energy": 0.4, "likes_acoustic": True}
    expected = [s["id"] for s, _, _ in recommend_songs(prefs, songs, k=5)]
    rng = random.Random(0)
    for _ in range(10):
        shuffled = list(songs)
        rng.shuffle(shuffled)
        assert [s["id"] for s, _, _ in recommend_songs(prefs, shuffled, k=5)] == expected


def test_ties_are_broken_by_song_id():
    twins = [
        {"id": 7, "title": "B", "artist": "X", "genre": "pop", "mood": "happy", "energy": 0.5, "acousticness": 0.5},
        {"id": 3, "title": "A", "artist": "Y", "genre": "pop", "mood": "happy", "energy": 0.5, "acousticness": 0.5},
    ]
    assert [s["id"] for s, _, _ in rank_songs({"genre": "pop"}, twins)] == [3, 7]


def test_recommending_does_not_modify_the_catalog(songs):
    before = [dict(s) for s in songs]
    recommend_songs({"genre": "pop", "energy": 0.8}, songs, k=5)
    assert songs == before


def test_fingerprint_is_stable_across_runs_and_reloads(songs, profiles):
    first = evaluate.fingerprint(profiles, songs)
    assert evaluate.fingerprint(profiles, songs) == first
    assert evaluate.fingerprint(profiles, load_songs(DATA_PATH)) == first


@pytest.mark.parametrize(
    "check",
    [
        lambda p, s: evaluate.check_repeat_runs(p, s),
        lambda p, s: evaluate.check_order_independence(p, s),
        lambda p, s: evaluate.check_reload(p, s, DATA_PATH),
        lambda p, s: evaluate.check_input_normalization(p, s),
    ],
    ids=["repeat_runs", "order_independence", "reload", "input_normalization"],
)
def test_evaluator_consistency_checks_pass(check, profiles, songs):
    result = check(profiles, songs)
    assert result["passed"], result["detail"]
