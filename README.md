# 🎵 VibeFinder: A Music Recommender You Can Check

VibeFinder recommends songs from a small catalog based on a listener's favorite genre, mood, energy level and taste for acoustic music, and it explains every pick ("mood match: happy (+1.00)"). This final version adds a **reliability layer**: an evaluator that measures genre diversity and fairness across 360 test listeners, consistency checks that prove the same question always gets the same answer, and an **agent gate** that lets an AI coding agent change the recommender only when no test or quality check gets worse.

**Why it matters:** recommenders decide what people see, and small weighting choices can quietly hide whole genres. This project shows how to make those effects measurable, how to keep results reproducible, and how to let AI write code without letting it game the tests.

---

## Original Project (Modules 1–3)

This project builds on my **Music Recommender Simulation (VibeFinder 1.0)**. The original goal was to represent songs and a user's "taste profile" as data, design a points-based scoring rule that ranks songs for that user, and evaluate what the system gets right and wrong. It could load an 18-song catalog, score each song on genre, mood, energy and acousticness, and print a top-5 list with the reasons behind each pick.

**What this version adds**

| Area | Modules 1–3 | Final project |
|---|---|---|
| Catalog | 18 songs, most genres had 1 song | 45 songs, 15 genres with exactly 3 songs each |
| Safety | None | Input and data validation, unknown-word warnings, "no strong match" message, one song per artist |
| Evaluation | Read 7 profiles by hand | Automated report over 360 profiles with 10 PASS/FAIL checks |
| Consistency | Not checked | Repeat runs, shuffled catalog, reworded input, result fingerprint |
| AI workflow | None | Agent gate that accepts or rejects AI-written code changes |
| Demo | One hard-coded profile in `src/main.py` | Command-line options for any profile; clear errors for invalid input |
| Tests | 2 starter tests | 95 tests |

---

## Architecture Overview

Full diagram: [diagrams/system_diagram.md](diagrams/system_diagram.md)

```
songs.csv + user profile (python -m src.main --genre ... --mood ... --energy ...)
        │
        ▼
  Recommender  ── data guardrails → scorer → ranker → artist cap → confidence check
        │
        ▼
  Top k songs with scores, match %, reasons, notes   (+ logs/recommender.log)

  Checked by:  pytest (95 tests)  ·  evaluator (360 profiles, 10 checks)
  Changed by:  AI coding agent → agent gate (runs tests + evaluator) → human review → merge
```

The system has five parts:

1. **Input:** a CSV of 45 songs and a user profile given as command-line options to [src/main.py](src/main.py) (genre, mood, target energy, likes acoustic, number of results).
2. **Recommender** ([src/recommender.py](src/recommender.py)): validates the data and input, scores every song, sorts them with a fixed tie-breaker, limits each artist to one song, and flags weak matches.
3. **Output:** the top songs, each with its score, match percentage and reasons, plus notes for weak or unknown input. Invalid input prints an error instead. Every run is logged.
4. **Automated checks:** pytest checks behavior. The evaluator ([src/evaluate.py](src/evaluate.py)) runs 360 fixed profiles and reports diversity, fairness and consistency against a random baseline.
5. **Agent loop:** an AI coding agent (an outside tool, not code in this repo) may edit only the recommender. The agent gate ([src/agent_gate.py](src/agent_gate.py)) compares its change with a saved baseline, runs the tests and evaluator, rejects regressions and cheating, and sends accepted changes to a **human** for the final review.

People check results in three places: they approve every accepted code change, approve any change to the song data, and read the evaluation report and record its findings in the [model card](model_card.md).

---

## Setup Instructions

Tested with Python 3.14 on Windows. Run every command from the project root (the folder that contains this README).

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # Mac/Linux

# 2. Install pinned dependencies
pip install -r requirements.txt

# 3. Get recommendations (no options = example profile pop / happy / 0.8)
python -m src.main
python -m src.main --genre lofi --mood chill --energy 0.35 --acoustic --k 3
python -m src.main --help          # all options: --genre --mood --energy --acoustic/--no-acoustic --k

# 4. Run all tests (about 25 seconds; add -m "not slow" for about 3 seconds)
pytest

# 5. Run the diversity, fairness and consistency report
python -m src.evaluate
python -m src.evaluate --json logs/eval_report.json   # also save the full report

# 6. Agent gate: snapshot first, then check after any code change
python -m src.agent_gate baseline
python -m src.agent_gate check --goal "what changed" --explain "why results changed"
```

Warnings appear as `Note:` lines in the output. Invalid input prints `Error: ...` and exits with code 2. Every run, including rejected input, is logged to `logs/recommender.log`.

---

## Sample Interactions

Each example shows the exact command and its full, unedited output. Running the same command again always prints the same output (checked by `tests/test_main.py` and the evaluator's consistency checks).

### 1. A typical listener: happy pop, energy 0.8

```
$ python -m src.main
Loaded songs: 45

============================================================
 Top 5 Recommendations
 Profile -> genre: pop | mood: happy | energy: 0.8
============================================================

 1. Sunrise City  (Neon Echo)
    Score: 4.69  (match: 99%)
    Reasons:
      - genre match: pop (+0.75)
      - mood match: happy (+1.00)
      - energy 0.82 close to target 0.80 (+2.94)

 2. Rooftop Lights  (Indigo Parade)
    Score: 4.25  (match: 90%)
    Reasons:
      - related genre: indie pop (+0.38)
      - mood match: happy (+1.00)
      - energy 0.76 close to target 0.80 (+2.88)

 3. Afterglow Drop  (Pulse Theory)
    Score: 3.88  (match: 82%)
    Reasons:
      - mood match: happy (+1.00)
      - energy 0.84 close to target 0.80 (+2.88)

 4. Gravel Road Anthem  (Tess Harlan)
    Score: 3.82  (match: 80%)
    Reasons:
      - mood match: happy (+1.00)
      - energy 0.74 close to target 0.80 (+2.82)

 5. Brass Alley Strut  (The Uptown Six)
    Score: 3.73  (match: 79%)
    Reasons:
      - mood match: happy (+1.00)
      - energy 0.71 close to target 0.80 (+2.73)

============================================================
```

The song that matches all three preferences wins, "indie pop" gets partial genre credit, and every song in the list is happy and close to the requested energy.

### 2. A conflicting request: sad pop at high energy

```
$ python -m src.main --genre pop --mood melancholic --energy 0.9
Loaded songs: 45

============================================================
 Top 5 Recommendations
 Profile -> genre: pop | mood: melancholic | energy: 0.9
============================================================

 1. Paper Hearts  (Lena Brooks)
    Score: 3.97  (match: 84%)
    Reasons:
      - genre match: pop (+0.75)
      - mood match: melancholic (+1.00)
      - energy 0.64 close to target 0.90 (+2.22)

 2. Cathedral of Ash  (Grave Signal)
    Score: 3.97  (match: 84%)
    Reasons:
      - mood match: melancholic (+1.00)
      - energy 0.89 close to target 0.90 (+2.97)

 3. Broken Compass  (Voltline)
    Score: 3.79  (match: 80%)
    Reasons:
      - mood match: melancholic (+1.00)
      - energy 0.83 close to target 0.90 (+2.79)

 4. Gym Hero  (Max Pulse)
    Score: 3.66  (match: 77%)
    Reasons:
      - genre match: pop (+0.75)
      - energy 0.93 close to target 0.90 (+2.91)

 5. Sunrise City  (Neon Echo)
    Score: 3.51  (match: 74%)
    Reasons:
      - genre match: pop (+0.75)
      - energy 0.82 close to target 0.90 (+2.76)

============================================================
```

In the original 18-song version, this listener got upbeat Gym Hero as #1 because no loud sad songs existed. After I filled that gap in the data, the top 3 are all sad songs. Paper Hearts and Cathedral of Ash tie at 3.97 and are ordered by song id, so the result never depends on file order.

### 3. A quiet acoustic listener, top 3 only

```
$ python -m src.main --genre lofi --mood chill --energy 0.35 --acoustic --k 3
Loaded songs: 45

============================================================
 Top 3 Recommendations
 Profile -> genre: lofi | mood: chill | energy: 0.35 | likes_acoustic: True
============================================================

 1. Library Rain  (Paper Lanterns)
    Score: 5.18  (match: 99%)
    Reasons:
      - genre match: lofi (+0.75)
      - mood match: chill (+1.00)
      - energy 0.35 close to target 0.35 (+3.00)
      - acoustic sound (+0.43)

 2. Midnight Coding  (LoRoom)
    Score: 4.89  (match: 93%)
    Reasons:
      - genre match: lofi (+0.75)
      - mood match: chill (+1.00)
      - energy 0.42 close to target 0.35 (+2.79)
      - acoustic sound (+0.35)

 3. Spacewalk Thoughts  (Orbit Bloom)
    Score: 4.25  (match: 81%)
    Reasons:
      - mood match: chill (+1.00)
      - energy 0.28 close to target 0.35 (+2.79)
      - acoustic sound (+0.46)

============================================================
```

With the acoustic preference given, all four checks score, and the acoustic bonus acts as a small tie-breaker. The third pick isn't lofi, but it matches the mood and energy closely.

### 4. Guardrails: words the system doesn't know, and invalid input

```
$ python -m src.main --genre opera --mood sad --acoustic --k 3
Loaded songs: 45

============================================================
 Top 3 Recommendations
 Profile -> genre: opera | mood: sad | likes_acoustic: True
============================================================
 Note: genre 'opera' is not in the catalog, so no song earns genre points
 Note: mood 'sad' is unknown, so no song earns mood points
 Note: not scored (no preference given): energy
 Note: no strong matches (best match is under 40% of a perfect score). Showing the closest songs.

 1. Moonlit Sonata No. 2  (Clara Vance)
    Score: 0.48  (match: 22%)
    Reasons:
      - acoustic sound (+0.48)

 2. Tidepool Drift  (Orbit Bloom)
    Score: 0.47  (match: 21%)
    Reasons:
      - acoustic sound (+0.47)

 3. Letters I Never Sent  (Hollow Pines)
    Score: 0.46  (match: 20%)
    Reasons:
      - acoustic sound (+0.46)

============================================================
```

```
$ python -m src.main --genre pop --energy 5
Loaded songs: 45
Error: energy must be between 0 and 1, got 5.0

$ python -m src.main --genre pop --energy loud
Loaded songs: 45
Error: energy must be a number between 0 and 1, got 'loud'
```

Instead of confidently returning poor matches, VibeFinder says which words it didn't recognize (the catalog uses "melancholic", not "sad"), shows a 22% match, and admits there's no strong match. Invalid energy is rejected with a clear message and exit code 2.

### 5. The agent gate rejecting an AI-written bug

A bug was planted in the energy formula (`1 - abs(...)` changed to `1 + abs(...)`), the kind of mistake an AI agent might make. The gate runs the recommender's tests (it skips its own 29 tests, which copy the project and call the gate), so it counts 66 tests:

```
$ python -m src.agent_gate baseline
$ # ... energy formula changed in src/recommender.py ...
$ python -m src.agent_gate check --goal "planted bug"
========================================================================
 Agent gate: REJECTED  (planted bug)
========================================================================
 Tests passed:      66 -> 64
 Evaluation checks: 8 -> 9 passing

 Problems (must fix):
   - test tests.test_guardrails::test_scores_stay_within_zero_and_max: passed before, now failed
   - test tests.test_main::test_valid_profile_prints_recommendations: passed before, now failed
   - results changed (fingerprint differs) but no --explain was given

 Notes:
   - evaluation check now passes: Every genre's fans served

 Logged to logs/agent_runs.jsonl
========================================================================
```

The bug actually *raised* the evaluation score from 8 to 9 passing checks. An agent judged only on that score would have kept it. The gate rejected it because existing tests broke.

---

## Design Decisions

**A transparent scoring rule instead of a trained model.** Each song earns points for genre, mood, energy closeness and acoustic preference, and every point comes with a written reason. *Trade-off:* it can't learn hidden patterns from listening history, but every result can be checked by hand, which is what made the bias findings below possible.

**Weights chosen by experiment.** I started with genre as the biggest weight (1.5), then ran a "Weight Shift" experiment that halved genre and doubled energy. The current code keeps the experiment's weights:

| Check | Max points | How points are earned |
|---|---|---|
| Genre | 0.75 | Full for an exact match, half for a related genre ("indie pop" vs "pop") |
| Mood | 1.0 | Full for an exact match, half for a mood in the same family (calm, high energy, upbeat, reflective) |
| Energy | 3.0 | `3.0 × (1 − |song energy − target|)`, so closeness wins, not loudness |
| Acoustic | 0.5 | Small tie-breaker, only if the user states a preference |

*Trade-off:* energy now matches the listener's vibe well, but it often outweighs their favorite genre. The evaluator measures exactly that cost (see Testing Summary).

**Equal genre sizes in the data.** I grew the catalog from 18 to 45 songs so that every genre has exactly 3. If one genre then shows up more than another, the cause is the scoring, not the catalog size. *Trade-off:* the songs I added are made up, and 3 per genre is still a small sample.

**One song per artist.** Without this rule, 47% of top-5 lists repeated an artist. With it, 0% do, and the average match stays at 70%. *Trade-off:* an artist's second-best song can be hidden even when it fits well.

**Determinism first.** Ties are broken by song id, scores are rounded before sorting, and the evaluator uses a fixed seed and prints a fingerprint of all 360 results. *Trade-off:* no randomness means no "discovery" shuffle, but any change in results can be traced to a code or data change.

**Thresholds set before looking at results.** The evaluator's pass/fail targets were written down first and are protected from edits by the agent gate. *Trade-off:* the report honestly shows 2 failures instead of a clean 10/10.

**The agent can edit only one file.** The gate lets an AI agent change `src/recommender.py` and nothing else. Tests, thresholds, data and the gate itself are hashed and protected. *Trade-off:* the agent can't fix a real data gap on its own, so a human has to approve data changes with `--allow-data`.

---

## Testing Summary

**What I test**

- **95 pytest tests:** the command-line demo, input and data guardrails, the artist rule, scores matching their reasons, consistency (repeat runs, shuffled catalog, reload, tie-breaking), the diversity and fairness formulas, and the agent gate (every cheating shortcut, plus the planted-bug test above).
- **Evaluation report:** 360 profiles (15 genres × 4 moods × 3 energy levels × acoustic yes/no), compared with a random recommender and with the ranking before the artist rule.

**What worked**

| Measure | VibeFinder | Without artist rule | Random picks |
|---|---|---|---|
| Different genres in a top 5 | 84% | 74% | 91% |
| Lists with a repeated artist | 0% | 47% | 14% |
| Songs ever recommended | 100% | 100% | 100% |
| Average match of recommended songs | 70% | 70% | 50% |

- **Fully consistent:** identical results across repeat runs, 5 shuffled catalogs, reloading the file, and 1,080 reworded inputs ("POP", "  pop ", `favorite_genre`). Moving energy by ±0.02 keeps 93% of songs on average.
- **Reproducible across machines:** the fingerprint for the current weights is `350c709226f12b60...`.
- **The agent gate catches mistakes and cheats:** it rejected the planted bug, and it rejected lowering a threshold to turn a FAIL into a PASS.

**What didn't work**

8 of 10 evaluation checks pass. The two failures are real bias findings, not bugs:

- **Balanced genre exposure: FAIL.** Metal gets 0.20 of its fair share of recommendations, while classical gets 1.73.
- **Every genre's fans served: FAIL.** Metal fans see a metal song in only 33% of their top-5 lists (target: 50%).

All three metal songs have energy of 0.89 or higher, and energy is the largest weight, so metal only scores well for listeners who want very loud music. Adding songs fixed other gaps (the sad-pop listener now gets sad songs) but not this one, because the cause is the weights.

**What I learned**

- A test suite and a quality score can disagree. The planted bug made the score *better* while breaking a guardrail test, so an AI agent needs to be checked against both.
- Bias showed up in aggregate numbers, not in the hand-picked profiles. All 7 of my manual profiles looked fine; the metal problem only appeared across 360.
- It's tempting to "fix" a failing check by moving the target. Writing thresholds down first, and protecting them in code, kept the results honest.

---

## Reflection

The biggest lesson was that the hard part of an AI system isn't producing an answer. It's being able to trust it. VibeFinder's scoring is a few lines of arithmetic, yet changing two weights flipped which listeners it served well, and nothing looked wrong until I measured it across hundreds of profiles. Solving problems here meant turning vague goals like "diverse" and "fair" into numbers with targets, then building guardrails so neither I nor an AI agent could quietly move those targets. My full responsible-AI reflection, including how I worked with AI and the system's limitations, is in the [model card](model_card.md).

---

## Reliability and Evaluation

VibeFinder is checked in five ways. Every result below can be reproduced with the commands in [Setup Instructions](#setup-instructions).

| Method | How it works | Result |
|---|---|---|
| Automated tests | 95 pytest tests | 95 / 95 pass |
| Confidence scoring | Each song gets a match % compared to a perfect score; under 40% for the #1 song triggers a "no strong match" note | Flags weak matches, as shown in section 2 below |
| Logging and error handling | Bad input and bad data raise clear errors; warnings and results go to `logs/recommender.log` | 9 / 9 error cases handled without a crash |
| Human evaluation | I ran 10 listener profiles and judged each top 5 against written criteria | 8 pass, 1 partial, 1 fail |
| Automated evaluation | 10 PASS/FAIL checks over 360 profiles | 8 / 10 pass (2 real bias findings) |

### 1. Automated tests

Run with `pytest`.

| Test file | Tests | What it checks | Result |
|---|---|---|---|
| `tests/test_recommender.py` | 2 | Starter tests: ranking order, explanation text | Pass |
| `tests/test_main.py` | 6 | Command-line demo: options, notes for weak matches, error exit code, same output every run | Pass |
| `tests/test_guardrails.py` | 38 | Bad input, bad CSV data, one song per artist, scores match their reasons | Pass |
| `tests/test_consistency.py` | 9 | Same input gives the same output: repeat runs, shuffled catalog, reload, tie-breaking | Pass |
| `tests/test_diversity.py` | 11 | Diversity and fairness formulas, every genre has 3 songs | Pass |
| `tests/test_agent_gate.py` | 29 | Agent gate rejects each cheating shortcut, catches a planted bug, accepts its fix | Pass |
| **Total** | **95** | | **95 pass** |

### 2. Confidence scoring

Each recommendation shows a **match %**: its score divided by the best score possible for that profile. Only preferences the user actually gave count toward the maximum. If even the #1 song is under 40%, VibeFinder prints *"no strong matches... Showing the closest songs"* instead of pretending.

| Profile | #1 song | Match | "No strong match" note shown? | Correct? |
|---|---|---|---|---|
| pop / happy / 0.8 | Sunrise City | 99% | No | Yes, it's a full match |
| pop / melancholic / 0.9 | Paper Hearts | 84% | No | Yes, genre and mood match, but energy is off |
| metal / angry / 0.5 | Iron Furnace | 70% | No | Yes, right genre and mood, but too loud |
| genre "opera", mood "sad", likes acoustic | Moonlit Sonata No. 2 | 22% | **Yes** | Yes: neither word is in the catalog, so it admits no song fits |

**Limitation:** match % only measures fit to the listed preferences. For the lofi / intense / 0.95 listener (human evaluation test 7 below), Gym Hero scores 83% on mood and energy alone, even though it misses the genre the user cares about most.

### 3. Logging and error handling

Invalid input and bad data stop with a message that says what's wrong and where. Nothing fails silently.

| Test input | Expected behavior | Result |
|---|---|---|
| `energy: 5.0` | Reject with a clear message | Pass: `energy must be between 0 and 1, got 5.0` |
| `energy: "loud"` | Reject with a clear message | Pass: `energy must be a number between 0 and 1, got 'loud'` |
| Empty profile `{}` | Reject with a clear message | Pass: `user profile has no usable preferences (genre, mood, energy, likes_acoustic)` |
| `k=0` | Reject with a clear message | Pass: `k must be a whole number of at least 1, got 0` |
| `k=100` (catalog has 45) | Return all songs and log a warning | Pass: returns 45 songs |
| Empty song list | Reject with a clear message | Pass: `cannot recommend from an empty song list` |
| CSV missing columns | Stop loading and name the columns | Pass: `missing required column(s): tempo_bpm, valence, danceability, acousticness` |
| CSV row with `energy` 1.7 | Stop loading and name the row | Pass: `row 2: 'energy' must be between 0 and 1 (got 1.7)` |
| CSV with a repeated song id | Stop loading and name the row | Pass: `row 3: duplicate song id 1` |

Every run writes the profile, the results, the weights and any warnings to `logs/recommender.log`. Real log output for a profile the catalog can't serve:

```
WARNING src.recommender: Profile {'likes_acoustic': True, 'genre': 'opera', 'mood': 'sad'}: genre 'opera' is not in the catalog, so no song earns genre points
WARNING src.recommender: Profile {'likes_acoustic': True, 'genre': 'opera', 'mood': 'sad'}: mood 'sad' is unknown, so no song earns mood points
INFO    src.recommender: Profile {'likes_acoustic': True, 'genre': 'opera', 'mood': 'sad'} -> Moonlit Sonata No. 2 (0.48), Tidepool Drift (0.47), ...
WARNING src.recommender: Low confidence for {'likes_acoustic': True, 'genre': 'opera', 'mood': 'sad'}: top score is under 40% of the best possible
```

### 4. Human evaluation

I ran each profile, read the full top 5 with its reasons, and judged it against criteria I wrote before running it. Energy is on a 0–1 scale.

| # | Test input (genre / mood / energy) | Evaluation criteria | Result |
|---|---|---|---|
| 1 | pop / happy / 0.8 | #1 is a happy pop song; list is upbeat | **Pass:** Sunrise City (99%); all 5 songs are happy, energy 0.71–0.84 |
| 2 | lofi / chill / 0.35, likes acoustic | #1 is chill lofi; list is quiet | **Pass:** Library Rain (99%); 2 lofi, rest ambient and jazz |
| 3 | rock / intense / 0.9, dislikes acoustic | #1 is intense rock; list is loud | **Pass:** Storm Runner (98%); 2 rock in the top 5 |
| 4 | edm / euphoric / 0.95 | #1 is euphoric EDM | **Pass:** Strobe Horizon (100%) |
| 5 | folk / melancholic / 0.3, likes acoustic | #1 is sad acoustic folk | **Pass:** Letters I Never Sent (99%) |
| 6 | pop / melancholic / 0.9 (conflicting) | Mood isn't ignored; sad songs come first | **Pass:** top 3 are all melancholic (Paper Hearts, Cathedral of Ash, Broken Compass) |
| 7 | lofi / intense / 0.95 (conflicting) | At least one lofi song in the top 5 | **Fail:** no lofi at all; #1 is Gym Hero (pop). All 3 lofi songs are quiet, and energy outweighs genre |
| 8 | metal / angry / 0.5 | A metal fan still gets metal at medium energy | **Pass:** Iron Furnace (70%); 2 metal songs in the top 5 |
| 9 | "kpop" / "sad" / 0.5 (words not in catalog) | Warns about both unknown words | **Partial:** warns about "sad", but "kpop" gets partial *pop* credit (it contains "pop"), so there's no genre warning |
| 10 | `"  POP "` / `"Happy"` / 0.8 (messy typing) | Same result as test 1 | **Pass:** identical top 5 |

**What this found:** test 7 confirms the energy weight can override a listener's favorite genre, the same bias the automated evaluation found for metal. Test 9 shows that matching genres by substring is helpful for "indie pop" but too loose for words like "kpop". Both are recorded in the [model card](model_card.md).

### 5. Automated evaluation (360 profiles)

Run with `python -m src.evaluate`. It covers 15 genres × 4 moods × 3 energy levels × acoustic yes/no, with thresholds set before looking at results.

| Check | Target | Result |
|---|---|---|
| No artist repeats in any list | 0 repeats | **Pass:** 0 |
| Genre variety per list | ≥ 0.60 unique-genre ratio | **Pass:** 0.84 |
| Catalog coverage | ≥ 80% of songs shown to someone | **Pass:** 100% |
| Balanced genre exposure | Every genre 0.5–2.0× its fair share | **Fail:** metal 0.20×, classical 1.73× |
| Every genre's fans served | ≥ 50% of a genre's fans see that genre | **Fail:** metal 33% |
| Consistency: repeat runs | Identical over 3 runs | **Pass** |
| Consistency: catalog order | Identical over 5 shuffles | **Pass** |
| Consistency: reload from disk | Identical after reloading the CSV | **Pass** |
| Consistency: input normalization | 1,080 reworded inputs give identical results | **Pass:** 0 differed |
| Consistency: small input stability | ≥ 80% of songs kept when energy moves ±0.02 | **Pass:** 93% average |

Result fingerprint: `350c709226f12b60...` (same results on any machine with the same code and data).

