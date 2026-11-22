"""Guardrail tests: bad input, bad data, and output rules."""

import math
import os

import pytest

from src.recommender import (
    LOW_CONFIDENCE_THRESHOLD,
    confidence,
    is_low_confidence,
    load_songs,
    max_possible_score,
    profile_warnings,
    recommend_songs,
    score_song,
    validate_prefs,
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "songs.csv")
HEADER = "id,title,artist,genre,mood,energy,tempo_bpm,valence,danceability,acousticness\n"
GOOD_ROW = "1,Song A,Artist A,pop,happy,0.8,120,0.8,0.8,0.2\n"


@pytest.fixture(scope="module")
def songs():
    return load_songs(DATA_PATH)


def write_csv(tmp_path, text):
    path = tmp_path / "songs.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


# --- Input guardrails -------------------------------------------------------

@pytest.mark.parametrize("energy", [-0.1, 1.5, 5.0])
def test_rejects_energy_out_of_range(energy):
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_prefs({"genre": "pop", "energy": energy})


@pytest.mark.parametrize("energy", ["high", True, math.nan, [0.5]])
def test_rejects_energy_that_is_not_a_number(energy):
    with pytest.raises(ValueError):
        validate_prefs({"energy": energy})


def test_rejects_non_bool_likes_acoustic():
    with pytest.raises(ValueError, match="likes_acoustic"):
        validate_prefs({"genre": "pop", "likes_acoustic": "yes"})


@pytest.mark.parametrize("prefs", [{}, {"genre": "   "}, {"color": "blue"}])
def test_rejects_profile_with_no_usable_preferences(prefs):
    with pytest.raises(ValueError, match="no usable preferences"):
        validate_prefs(prefs)


def test_rejects_non_dict_profile():
    with pytest.raises(ValueError):
        validate_prefs("pop")


def test_normalizes_case_and_whitespace():
    assert validate_prefs({"genre": "  Indie   POP ", "mood": "Happy"}) == {"genre": "indie pop", "mood": "happy"}


def test_accepts_userprofile_style_keys_and_short_keys_win():
    clean = validate_prefs({"favorite_genre": "rock", "genre": "pop", "target_energy": 0.5})
    assert clean == {"genre": "pop", "energy": 0.5}


def test_messy_input_scores_the_same_as_clean_input(songs):
    clean = score_song({"genre": "pop", "mood": "happy", "energy": 0.8}, songs[0])
    messy = score_song({"genre": " Pop ", "mood": "HAPPY", "energy": 0.8}, songs[0])
    assert clean == messy


@pytest.mark.parametrize("k", [0, -1, 2.5, True, "5"])
def test_rejects_invalid_k(songs, k):
    with pytest.raises(ValueError, match="k must be"):
        recommend_songs({"genre": "pop"}, songs, k=k)


def test_k_larger_than_catalog_is_capped(songs):
    results = recommend_songs({"genre": "pop"}, songs, k=1000, max_per_artist=None)
    assert len(results) == len(songs)


def test_rejects_empty_catalog():
    with pytest.raises(ValueError, match="empty"):
        recommend_songs({"genre": "pop"}, [], k=5)


def test_warns_about_unknown_genre_and_mood(songs):
    warnings = profile_warnings({"genre": "polka", "mood": "sad", "energy": 0.5}, songs)
    assert any("polka" in w for w in warnings)
    assert any("sad" in w for w in warnings)


def test_no_warnings_for_a_fully_known_profile(songs):
    assert profile_warnings({"genre": "pop", "mood": "happy", "energy": 0.8}, songs) == []


def test_unknown_genre_still_returns_results(songs):
    assert len(recommend_songs({"genre": "polka", "energy": 0.5}, songs, k=5)) == 5


# --- Data guardrails ---------------------------------------------------------

def test_load_rejects_missing_column(tmp_path):
    path = write_csv(tmp_path, "id,title,artist,genre,mood,energy\n1,A,B,pop,happy,0.5\n")
    with pytest.raises(ValueError, match="missing required column"):
        load_songs(path)


def test_load_reports_row_number_for_bad_number(tmp_path):
    path = write_csv(tmp_path, HEADER + GOOD_ROW + "2,Song B,Artist B,rock,intense,loud,120,0.5,0.5,0.1\n")
    with pytest.raises(ValueError, match=r"row 3: 'energy' is not a number"):
        load_songs(path)


def test_load_rejects_value_outside_zero_to_one(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,Song A,Artist A,pop,happy,0.8,120,0.8,0.8,1.7\n")
    with pytest.raises(ValueError, match="acousticness"):
        load_songs(path)


def test_load_rejects_duplicate_ids(tmp_path):
    path = write_csv(tmp_path, HEADER + GOOD_ROW + GOOD_ROW)
    with pytest.raises(ValueError, match="duplicate song id 1"):
        load_songs(path)


def test_load_rejects_empty_text_field(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,Song A,Artist A,  ,happy,0.8,120,0.8,0.8,0.2\n")
    with pytest.raises(ValueError, match="'genre' is empty"):
        load_songs(path)


def test_load_rejects_file_with_no_songs(tmp_path):
    with pytest.raises(ValueError, match="no songs"):
        load_songs(write_csv(tmp_path, HEADER))


# --- Output guardrails -------------------------------------------------------

def test_no_artist_appears_twice_by_default(songs):
    for prefs in ({"genre": "lofi", "mood": "chill", "energy": 0.4}, {"genre": "pop", "energy": 0.8}):
        artists = [song["artist"] for song, _, _ in recommend_songs(prefs, songs, k=5)]
        assert len(artists) == len(set(artists))


def test_artist_cap_backfills_when_catalog_has_too_few_artists():
    one_artist = [
        {"id": i, "title": f"S{i}", "artist": "Solo", "genre": "pop", "mood": "happy",
         "energy": 0.5, "acousticness": 0.5}
        for i in range(1, 4)
    ]
    assert len(recommend_songs({"genre": "pop"}, one_artist, k=3)) == 3


def test_genre_cap_limits_songs_per_genre(songs):
    results = recommend_songs({"genre": "lofi", "mood": "chill", "energy": 0.4}, songs, k=5, max_per_genre=1)
    genres = [song["genre"] for song, _, _ in results]
    assert len(genres) == len(set(genres))


def test_scores_stay_within_zero_and_max(songs):
    prefs = {"genre": "jazz", "mood": "relaxed", "energy": 0.4, "likes_acoustic": True}
    best = max_possible_score(prefs)
    for song in songs:
        score, _ = score_song(prefs, song)
        assert 0 <= score <= best


def test_reason_points_add_up_to_score(songs):
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.8, "likes_acoustic": False}
    for song in songs:
        score, reasons = score_song(prefs, song)
        listed = sum(float(r.rsplit("(+", 1)[1].rstrip(")")) for r in reasons)
        assert listed == pytest.approx(score, abs=0.01 * len(reasons))


def test_low_confidence_flag_for_unservable_profile(songs):
    prefs = {"genre": "polka", "mood": "sad"}  # nothing can score
    results = recommend_songs(prefs, songs, k=5)
    assert is_low_confidence(results, prefs)


def test_no_low_confidence_flag_for_a_strong_match(songs):
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}
    results = recommend_songs(prefs, songs, k=5)
    assert confidence(results[0][1], prefs) >= LOW_CONFIDENCE_THRESHOLD
    assert not is_low_confidence(results, prefs)
