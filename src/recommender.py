import csv
import logging
import math
from dataclasses import asdict, dataclass
from typing import Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# Point weights (max 5.25 points)
# Experiment "Weight Shift": genre halved (was 1.5 / 0.75), energy doubled (was 1.5)
GENRE_MATCH_POINTS = 0.75
GENRE_RELATED_POINTS = 0.375
MOOD_MATCH_POINTS = 1.0
MOOD_FAMILY_POINTS = 0.5
ENERGY_MAX_POINTS = 3.0
ACOUSTIC_MAX_POINTS = 0.5

# Moods in the same family earn partial credit
MOOD_FAMILIES = {
    "calm": {"chill", "relaxed", "peaceful", "focused"},
    "high energy": {"intense", "angry", "euphoric", "confident"},
    "upbeat": {"happy", "carefree", "romantic"},
    "reflective": {"moody", "nostalgic", "melancholic"},
}

# Guardrail settings
LOW_CONFIDENCE_THRESHOLD = 0.40   # top score below 40% of the max possible -> "no strong match"
DEFAULT_MAX_PER_ARTIST = 1        # at most one song per artist in a recommendation list
DEFAULT_MAX_PER_GENRE = None      # optional genre cap (None = no cap)

REQUIRED_COLUMNS = (
    "id", "title", "artist", "genre", "mood",
    "energy", "tempo_bpm", "valence", "danceability", "acousticness",
)
INT_FIELDS = ("id",)
FLOAT_FIELDS = ("energy", "tempo_bpm", "valence", "danceability", "acousticness")
UNIT_FIELDS = ("energy", "valence", "danceability", "acousticness")  # must be within 0-1
TEXT_FIELDS = ("title", "artist", "genre", "mood")

# Accept both the short keys used in main.py and the UserProfile field names
PREF_ALIASES = {
    "favorite_genre": "genre",
    "favorite_mood": "mood",
    "target_energy": "energy",
}
KNOWN_PREF_KEYS = {"genre", "mood", "energy", "likes_acoustic"}


@dataclass
class Song:
    """
    Represents a song and its attributes.
    Required by tests/test_recommender.py
    """
    id: int
    title: str
    artist: str
    genre: str
    mood: str
    energy: float
    tempo_bpm: float
    valence: float
    danceability: float
    acousticness: float


@dataclass
class UserProfile:
    """
    Represents a user's taste preferences.
    Required by tests/test_recommender.py
    """
    favorite_genre: str
    favorite_mood: str
    target_energy: float
    likes_acoustic: bool


def profile_to_prefs(user: UserProfile) -> Dict:
    """Converts a UserProfile into the preference dict used by the scoring functions."""
    return {
        "genre": user.favorite_genre,
        "mood": user.favorite_mood,
        "energy": user.target_energy,
        "likes_acoustic": user.likes_acoustic,
    }


class Recommender:
    """
    OOP implementation of the recommendation logic.
    Required by tests/test_recommender.py
    """
    def __init__(self, songs: List[Song]):
        self.songs = songs

    def recommend(self, user: UserProfile, k: int = 5) -> List[Song]:
        song_dicts = [asdict(song) for song in self.songs]
        by_id = {song.id: song for song in self.songs}
        results = recommend_songs(profile_to_prefs(user), song_dicts, k=k)
        return [by_id[song["id"]] for song, _, _ in results]

    def explain_recommendation(self, user: UserProfile, song: Song) -> str:
        _, reasons = score_song(profile_to_prefs(user), asdict(song))
        return "; ".join(reasons) if reasons else "no preferences matched this song"


# ---------------------------------------------------------------------------
# Data guardrails
# ---------------------------------------------------------------------------

def load_songs(csv_path: str) -> List[Dict]:
    """
    Reads songs from a CSV file into dicts, converting numeric columns to int/float.

    Guardrails: fails early with the row number if a column is missing, a number
    doesn't parse, a 0-1 feature is out of range, a text field is empty, or an id repeats.
    """
    songs: List[Dict] = []
    seen_ids = set()

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [col for col in REQUIRED_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{csv_path}: missing required column(s): {', '.join(missing)}")

        # Row 1 is the header, so the first song is on line 2
        for line_no, row in enumerate(reader, start=2):
            where = f"{csv_path} row {line_no}"

            for field in TEXT_FIELDS:
                row[field] = (row[field] or "").strip()
                if not row[field]:
                    raise ValueError(f"{where}: '{field}' is empty")

            try:
                for field in INT_FIELDS:
                    row[field] = int(row[field])
                for field in FLOAT_FIELDS:
                    row[field] = float(row[field])
            except (TypeError, ValueError):
                raise ValueError(f"{where}: '{field}' is not a number (got {row[field]!r})") from None

            for field in UNIT_FIELDS:
                if not 0.0 <= row[field] <= 1.0:
                    raise ValueError(f"{where}: '{field}' must be between 0 and 1 (got {row[field]})")
            if row["tempo_bpm"] <= 0:
                raise ValueError(f"{where}: 'tempo_bpm' must be positive (got {row['tempo_bpm']})")

            if row["id"] in seen_ids:
                raise ValueError(f"{where}: duplicate song id {row['id']}")
            seen_ids.add(row["id"])

            songs.append(row)

    if not songs:
        raise ValueError(f"{csv_path}: no songs found")

    logger.info("Loaded %d songs from %s", len(songs), csv_path)
    return songs


# ---------------------------------------------------------------------------
# Input guardrails
# ---------------------------------------------------------------------------

def validate_prefs(user_prefs: Mapping) -> Dict:
    """
    Cleans and checks a user profile. Returns a new dict with short keys
    (genre, mood, energy, likes_acoustic). Raises ValueError for unusable input.
    """
    if not isinstance(user_prefs, Mapping):
        raise ValueError(f"user preferences must be a dict, got {type(user_prefs).__name__}")

    # Short keys win; an alias (e.g. "favorite_genre") is used only when the short key is absent
    clean: Dict = {key: user_prefs[key] for key in KNOWN_PREF_KEYS if key in user_prefs}
    for alias, key in PREF_ALIASES.items():
        if alias in user_prefs and clean.get(key) is None:
            clean[key] = user_prefs[alias]
    unknown = set(user_prefs) - KNOWN_PREF_KEYS - set(PREF_ALIASES)
    if unknown:
        logger.debug("Ignoring unknown preference key(s): %s", ", ".join(sorted(map(str, unknown))))

    # Text: normalize case and whitespace; empty text counts as "no preference"
    for key in ("genre", "mood"):
        if key not in clean or clean[key] is None:
            clean.pop(key, None)
            continue
        if not isinstance(clean[key], str):
            raise ValueError(f"{key} must be text, got {clean[key]!r}")
        clean[key] = " ".join(clean[key].split()).lower()
        if not clean[key]:
            del clean[key]

    # Energy: a real number from 0 to 1 (bool is rejected even though it is an int in Python)
    if clean.get("energy") is None:
        clean.pop("energy", None)
    else:
        energy = clean["energy"]
        if isinstance(energy, bool) or not isinstance(energy, (int, float)) or math.isnan(energy):
            raise ValueError(f"energy must be a number between 0 and 1, got {energy!r}")
        if not 0.0 <= energy <= 1.0:
            raise ValueError(f"energy must be between 0 and 1, got {energy}")
        clean["energy"] = float(energy)

    # Acoustic preference: True, False, or not given
    if clean.get("likes_acoustic") is None:
        clean.pop("likes_acoustic", None)
    elif not isinstance(clean["likes_acoustic"], bool):
        raise ValueError(f"likes_acoustic must be True or False, got {clean['likes_acoustic']!r}")

    if not clean:
        raise ValueError("user profile has no usable preferences (genre, mood, energy, likes_acoustic)")

    return clean


def _known_moods(songs: List[Dict]) -> set:
    moods = {song["mood"].lower() for song in songs}
    for family in MOOD_FAMILIES.values():
        moods |= family
    return moods


def profile_warnings(user_prefs: Mapping, songs: List[Dict]) -> List[str]:
    """Returns plain-language warnings about a profile the catalog can't fully serve."""
    prefs = validate_prefs(user_prefs)
    warnings = []

    genre = prefs.get("genre")
    if genre:
        genres = {song["genre"].lower() for song in songs}
        related = {g for g in genres if genre in g or g in genre}
        if not related:
            warnings.append(f"genre '{genre}' is not in the catalog, so no song earns genre points")

    mood = prefs.get("mood")
    if mood and mood not in _known_moods(songs):
        warnings.append(f"mood '{mood}' is unknown, so no song earns mood points")

    skipped = [name for name in ("genre", "mood", "energy") if name not in prefs]
    if skipped:
        warnings.append(f"not scored (no preference given): {', '.join(skipped)}")

    return warnings


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def max_possible_score(user_prefs: Mapping) -> float:
    """The best score any song could earn for this profile (only stated preferences count)."""
    prefs = validate_prefs(user_prefs)
    total = 0.0
    if "genre" in prefs:
        total += GENRE_MATCH_POINTS
    if "mood" in prefs:
        total += MOOD_MATCH_POINTS
    if "energy" in prefs:
        total += ENERGY_MAX_POINTS
    if "likes_acoustic" in prefs:
        total += ACOUSTIC_MAX_POINTS
    return total


def confidence(score: float, user_prefs: Mapping) -> float:
    """Score as a fraction (0-1) of the best possible score for this profile."""
    best = max_possible_score(user_prefs)
    return score / best if best else 0.0


def is_low_confidence(recommendations: List[Tuple[Dict, float, str]], user_prefs: Mapping) -> bool:
    """True when even the #1 recommendation is a weak match."""
    if not recommendations:
        return True
    return confidence(recommendations[0][1], user_prefs) < LOW_CONFIDENCE_THRESHOLD


def score_song(user_prefs: Mapping, song: Dict) -> Tuple[float, List[str]]:
    """Scores one song against user preferences and returns (score, list of reasons)."""
    prefs = validate_prefs(user_prefs)
    score = 0.0
    reasons = []

    fav_genre = prefs.get("genre", "")
    fav_mood = prefs.get("mood", "")
    target_energy = prefs.get("energy")
    likes_acoustic = prefs.get("likes_acoustic")

    # Genre: exact match, or partial credit when one name contains the other (e.g. "indie pop" / "pop")
    song_genre = song["genre"].lower()
    if fav_genre and song_genre == fav_genre:
        score += GENRE_MATCH_POINTS
        reasons.append(f"genre match: {song_genre} (+{GENRE_MATCH_POINTS:.2f})")
    elif fav_genre and (fav_genre in song_genre or song_genre in fav_genre):
        score += GENRE_RELATED_POINTS
        reasons.append(f"related genre: {song_genre} (+{GENRE_RELATED_POINTS:.2f})")

    # Mood: exact match, or partial credit for a mood in the same family
    song_mood = song["mood"].lower()
    if fav_mood and song_mood == fav_mood:
        score += MOOD_MATCH_POINTS
        reasons.append(f"mood match: {song_mood} (+{MOOD_MATCH_POINTS:.2f})")
    elif fav_mood and any(fav_mood in family and song_mood in family for family in MOOD_FAMILIES.values()):
        score += MOOD_FAMILY_POINTS
        reasons.append(f"similar mood: {song_mood} (+{MOOD_FAMILY_POINTS:.2f})")

    # Energy: reward closeness to the target, not just high energy
    if target_energy is not None:
        energy_points = ENERGY_MAX_POINTS * (1 - abs(song["energy"] - target_energy))
        score += energy_points
        reasons.append(f"energy {song['energy']:.2f} close to target {target_energy:.2f} (+{energy_points:.2f})")

    # Acoustic: tie-breaker, only scored when the user stated a preference
    if likes_acoustic is not None:
        if likes_acoustic:
            acoustic_points = ACOUSTIC_MAX_POINTS * song["acousticness"]
            label = "acoustic sound"
        else:
            acoustic_points = ACOUSTIC_MAX_POINTS * (1 - song["acousticness"])
            label = "produced/electronic sound"
        score += acoustic_points
        reasons.append(f"{label} (+{acoustic_points:.2f})")

    return score, reasons


def rank_songs(user_prefs: Mapping, songs: List[Dict]) -> List[Tuple[Dict, float, List[str]]]:
    """
    Scores every song and sorts them, highest first.

    Ties are broken by song id, so the ranking never depends on the order of the CSV.
    Scores are rounded for sorting so tiny floating-point noise can't reorder equal songs.
    """
    prefs = validate_prefs(user_prefs)
    scored = [(song, *score_song(prefs, song)) for song in songs]
    return sorted(scored, key=lambda item: (-round(item[1], 9), item[0]["id"]))


# ---------------------------------------------------------------------------
# Recommendation (with output guardrails)
# ---------------------------------------------------------------------------

def _apply_diversity_caps(
    ranked: List[Tuple[Dict, float, List[str]]],
    k: int,
    max_per_artist: Optional[int],
    max_per_genre: Optional[int],
) -> List[Tuple[Dict, float, List[str]]]:
    """
    Walks the ranking and skips songs that would break the artist/genre caps.
    If the caps leave fewer than k songs, the best skipped songs fill the gaps
    (so the user always gets k results), and that is logged.
    """
    picked, skipped = [], []
    artist_counts: Dict[str, int] = {}
    genre_counts: Dict[str, int] = {}

    for item in ranked:
        if len(picked) == k:
            break
        song = item[0]
        artist, genre = song["artist"].lower(), song["genre"].lower()
        if max_per_artist is not None and artist_counts.get(artist, 0) >= max_per_artist:
            skipped.append(item)
            continue
        if max_per_genre is not None and genre_counts.get(genre, 0) >= max_per_genre:
            skipped.append(item)
            continue
        picked.append(item)
        artist_counts[artist] = artist_counts.get(artist, 0) + 1
        genre_counts[genre] = genre_counts.get(genre, 0) + 1

    if len(picked) < k and skipped:
        needed = k - len(picked)
        logger.info("Diversity caps left %d slot(s) empty; filling with the best skipped songs", needed)
        picked.extend(skipped[:needed])
        picked.sort(key=lambda item: (-round(item[1], 9), item[0]["id"]))

    return picked


def recommend_songs(
    user_prefs: Mapping,
    songs: List[Dict],
    k: int = 5,
    max_per_artist: Optional[int] = DEFAULT_MAX_PER_ARTIST,
    max_per_genre: Optional[int] = DEFAULT_MAX_PER_GENRE,
) -> List[Tuple[Dict, float, str]]:
    """
    Scores every song and returns the top k as (song, score, explanation), highest first.

    Guardrails: validates the profile and k, caps k at the catalog size, limits repeats of
    one artist (and optionally one genre), and logs warnings for profiles the catalog can't serve.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k must be a whole number of at least 1, got {k!r}")
    if not songs:
        raise ValueError("cannot recommend from an empty song list")
    for name, cap in (("max_per_artist", max_per_artist), ("max_per_genre", max_per_genre)):
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
            raise ValueError(f"{name} must be None or a whole number of at least 1, got {cap!r}")

    prefs = validate_prefs(user_prefs)
    if k > len(songs):
        logger.warning("k=%d is larger than the catalog (%d songs); returning all songs", k, len(songs))
        k = len(songs)

    for warning in profile_warnings(prefs, songs):
        logger.warning("Profile %s: %s", prefs, warning)

    ranked = rank_songs(prefs, songs)
    picked = _apply_diversity_caps(ranked, k, max_per_artist, max_per_genre)
    results = [(song, score, "; ".join(reasons)) for song, score, reasons in picked]

    logger.info(
        "Profile %s -> %s",
        prefs,
        ", ".join(f"{song['title']} ({score:.2f})" for song, score, _ in results),
    )
    if is_low_confidence(results, prefs):
        logger.warning(
            "Low confidence for %s: top score is under %d%% of the best possible",
            prefs, int(LOW_CONFIDENCE_THRESHOLD * 100),
        )

    return results


def weights_summary() -> Dict[str, float]:
    """The current scoring weights, logged with each run so results can be reproduced."""
    return {
        "genre_match": GENRE_MATCH_POINTS,
        "genre_related": GENRE_RELATED_POINTS,
        "mood_match": MOOD_MATCH_POINTS,
        "mood_family": MOOD_FAMILY_POINTS,
        "energy_max": ENERGY_MAX_POINTS,
        "acoustic_max": ACOUSTIC_MAX_POINTS,
    }
