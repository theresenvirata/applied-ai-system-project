# 🎧 Model Card: VibeFinder 1.0

## 1. Overview

**VibeFinder** recommends 5 songs from a 45-song catalog. The user gives up to four preferences: favorite genre, mood, target energy (0–1), and whether they like acoustic music. Every song gets a score, and the top 5 are shown with the reasons each one was picked.

It is a **rule-based, content-based recommender**. It does not learn, has no listening history, and uses only what the user types in. The "AI" parts of the project are around it: an automated evaluator, consistency checks, and an agent gate that checks code changes written by an AI agent.

**Intended use:** a classroom project for learning how recommenders work and how weight choices create bias.

**Not intended for:** real listeners or a real app (the catalog is tiny and made up), judging whether a genre or artist is "good," or anything sensitive like mood or mental-health support.

---

## 2. How It Works

**Scoring.** Each song earns points for four checks. Every point comes with a written reason, such as "mood match: happy (+1.00)".

| Check | Max points | How points are earned |
|---|---|---|
| Genre | 0.75 | Full for an exact match, half for a related genre (one name contains the other, like "indie pop" and "pop") |
| Mood | 1.0 | Full for an exact match, half for a mood in the same family (calm, high energy, upbeat, reflective) |
| Energy | 3.0 | `3.0 × (1 − \|song energy − target\|)`, so closeness wins, not loudness |
| Acoustic | 0.5 | `0.5 × acousticness` if the user likes acoustic, otherwise `0.5 × (1 − acousticness)` |

The highest possible score is 5.25. These are the "Weight Shift" weights: the original design had genre at 1.5 and energy at 1.5. Halving genre and doubling energy made recommendations fit the requested vibe better, but it is also the main source of the biases in Section 5. Tempo, valence, and danceability are in the data but not scored.

**Ranking and guardrails.**

- Songs are sorted by score. Ties are broken by song id, so file order never changes the results.
- At most one song per artist appears in a top 5.
- Each song shows a **match %**: its score divided by the best score possible for the preferences given. If the #1 song is under 40%, VibeFinder says it found no strong match.
- Bad input (energy outside 0–1, an empty profile, `k < 1`) and bad data (missing columns, out-of-range values, duplicate ids) stop with an error that names the problem.
- Unknown genres or moods still return results, with a warning that the word earned no points.
- Every run logs the profile, the weights, the results, and any warnings to `logs/recommender.log`.

---

## 3. Data

- **45 songs**, **15 genres** with exactly 3 songs each, **14 moods**, and **31 artists** (14 of them have 2 songs).
- Features: title, artist, genre, mood, energy, tempo, valence, danceability, acousticness.
- The starter file had 10 songs. I grew it to 18, then to 45 so that every genre is the same size. If one genre then gets recommended more than another, the cause is the scoring, not the catalog.
- I added songs to fill gaps: loud sad songs, songs with energy between 0.58 and 0.75, and songs that break their genre's usual sound (a calm EDM track, an intense classical piece).

**Limits:** the songs and artists are made up, 3 songs per genre is a small sample, genre and mood labels are my own judgment, and the catalog leans calm (20 of 45 songs have energy below 0.6).

---

## 4. Evaluation

I tested VibeFinder four ways. Full tables are in the README's [Reliability and Evaluation](README.md#reliability-and-evaluation) section.

| Method | What it covers | Result |
|---|---|---|
| Human evaluation | 10 profiles judged against criteria written before running them | 8 pass, 1 partial, 1 fail |
| Automated evaluation (`python -m src.evaluate`) | 360 profiles: 15 genres × 4 moods × 3 energy levels × acoustic yes/no | 8 of 10 checks pass |
| Automated tests (`pytest`) | Command-line demo, guardrails, consistency, diversity formulas, agent gate | 95 of 95 pass |
| Agent gate (`python -m src.agent_gate`) | Rejects AI-written changes that break tests, lower targets, or touch protected files | Rejected a planted bug and a lowered threshold; accepted the fix |

**Key results from the 360-profile evaluation**

| Measure | VibeFinder | Without artist rule | Random picks |
|---|---|---|---|
| Different genres in a top 5 | 84% | 74% | 91% |
| Lists with a repeated artist | 0% | 47% | 14% |
| Songs ever recommended | 100% | 100% | 100% |
| Average match of recommended songs | 70% | 70% | 50% |

- **Consistent:** identical results across repeat runs, 5 shuffled catalogs, a reload, and 1,080 reworded inputs ("POP", "  pop "). Moving energy by ±0.02 keeps 93% of songs on average (60% in the worst case).
- **Failed checks:** metal gets 0.20× its fair share of recommendations (target: 0.5–2.0×), and metal fans see a metal song in only 33% of their lists (target: 50%). I set both targets before seeing the results.

---

## 5. Limitations and Biases

**Energy outweighs favorite genre.** Energy is worth 3.0 points and genre only 0.75. For 49% of test profiles, the #1 song is not in the user's favorite genre.

- **Metal is nearly invisible.** All three metal songs have energy of 0.89 or higher, so they only score well for very loud requests. Rock fans (54%) and ambient fans (62%) also often miss their genre.
- **A lofi fan who wants high energy gets no lofi at all.** All three lofi songs have energy between 0.35 and 0.42.

**A calm filter bubble.** Calm songs fit more requests. Moonlit Sonata No. 2 is in the top 5 for 31% of test profiles; Iron Furnace, the loudest song, is in it for 1%.

**Text matching is literal.**

- Words outside the catalog earn nothing. "sad" scores zero because the catalog says "melancholic". VibeFinder warns about this but doesn't fix it.
- Related genres are matched by substring. That helps "indie pop", but "kpop" also gets partial pop credit and no "unknown genre" warning.
- The mood families are my own judgment; someone else might group "confident" differently.

**The artist rule hides good songs.** It removed all repeats, but an artist's second song can disappear. Morning Etude (same artist as Moonlit Sonata No. 2) reaches the top 5 for only 1% of profiles.

**Confidence is not satisfaction.** Match % measures fit to the typed preferences, not whether someone would enjoy the song. Gym Hero scores 83% for a lofi fan because of mood and energy alone.

**Testing gaps.**

- The evaluation grid tops out at energy 0.8, so it under-tests listeners who want very loud music, which is exactly where metal scores well.
- The agent gate only catches what the tests and checks measure. Its code scan uses simple patterns that a determined agent could get around.

---

## 6. Misuse and Prevention

VibeFinder is low-stakes, but the same design could be misused in a real recommender.

| Possible misuse | How this project guards against it |
|---|---|
| **Hidden promotion:** quietly boosting a label's artists or a genre by editing weights or adding a special rule | Every song lists its reasons. Weights are logged with every run. The result fingerprint changes whenever any result changes. The agent gate rejects code that hard-codes a genre, artist, title, or song id. |
| **Faking fairness:** lowering a target so a failing check reads PASS | Targets were written down before the results. The agent gate locks `src/evaluate.py` and rejected a test where the metal target was lowered from 50% to 30%. |
| **Treating it as emotional support:** a "sad" request taken as understanding how someone feels | The intended-use statement rules this out. Unknown mood words like "sad" get an explicit warning instead of a confident answer. |
| **Rubber-stamping AI code:** treating the gate's ACCEPTED as approval to merge | The gate never merges. Every accepted change still needs human review, and every attempt is logged to `logs/agent_runs.jsonl`. |
| **Slipping in data changes:** an agent editing the song catalog to make checks pass | Data files are locked. Changing them requires a human to pass `--allow-data`, and that approval is logged. |

**Privacy:** VibeFinder stores no names or accounts. The log keeps the preferences entered for each run, so a real version would need a retention policy for that log.

---

## 7. What Surprised Me While Testing Reliability

- **A bug made the scores better.** I planted a bug that rewarded songs *far* from the target energy. The evaluation went from 8 to 9 passing checks, because metal fans happened to get more metal. Only the tests caught it: a guardrail test and a command-line test both failed. Judged on the evaluation alone, an AI agent would have kept the bug.
- **Hand-picked tests looked fine.** All 7 of my original profiles got sensible results. The metal problem only appeared once I measured 360 profiles.
- **Edge cases find what normal cases miss.** The "kpop" substring issue only showed up when I deliberately typed a word that isn't in the catalog.
- **Small changes matter more than expected.** Nudging energy by just 0.02 can swap 2 of the 5 songs, because many songs score within a few hundredths of each other. Two songs tie exactly at 3.97 for the "sad pop" profile, which is why fixed tie-breaking was necessary.
- **Cheating is one line.** Changing `0.50` to `0.30` would make the report look clean. That convinced me the targets had to be locked in code, not just documented.

---

## 8. Collaboration with AI

I used an AI coding assistant throughout the project. It helped me:

- brainstorm tricky test profiles, like "high energy but sad";
- find real bugs, such as " Pop " with spaces scoring lower than "pop", and energy 5.0 making every score negative;
- write the evaluation script, the consistency checks, and the agent gate;
- draft documentation.

I treated its output as a draft. I re-ran profiles and checked each claim against the real output. More than once its numbers were out of date after I changed the weights, and some early explanations claimed more than the data showed.

**A suggestion I accepted:** lock the tests and evaluation targets so an AI agent can't change them. When I asked about guardrails for an agent that writes, tests, and fixes code, the AI pointed out that the easiest way for an agent to "fix" my two metal failures would be to lower the target in `src/evaluate.py`, not to improve the recommender. I accepted this as written. The gate hashes the tests, the targets, the data, and itself, and rejects any change to them. It fits my project because I had already committed to setting targets before seeing results, and a test confirmed it works: lowering the metal target was rejected.

**A suggestion I did not accept as written:** the AI's first plan for the agentic workflow was much larger. It included a full agent loop with retry limits, sandboxing, separate git branches, a test that compares the README's weight table against the code, and a planted-bug test in which *the agent* finds and fixes the bug. I scoped it down to the gate and the planted-bug test. I also changed that test to check that the gate *rejects* the bug and *accepts* the fix, instead of depending on an agent to find it. The full loop was out of scope, since my project doesn't run an agent yet. A test that depends on an AI's output also wouldn't give the same result every time, which goes against the consistency my evaluation is built on.

---

## 9. Ideas for Improvement

1. **Rebalance the weights.** Raise genre so energy doesn't drown it out, then re-run the evaluation to see if the metal checks pass.
2. **Fill data gaps.** Add an upbeat lofi song and a calmer metal song.
3. **Widen the test grid.** Add energy levels of 0.05 and 0.95 so loud and very quiet genres are tested fairly.
4. **Stricter genre matching.** Use an explicit list of related genres instead of substring matching, so "kpop" isn't treated as pop.
5. **Use valence** so "sad" vs. "happy" is measured by how a song sounds, not just its label.
6. **Connect a real agent to the gate**, limited to 3–5 attempts, with every accepted change reviewed by me.

---

## 10. Personal Reflection

My biggest lesson came from the "Weight Shift" experiment. Changing two numbers flipped who the system served well. The weights aren't details; they *are* the recommender's opinion about what matters. VibeFinder is just adding up points, yet showing reasons like "mood match: happy" makes it feel smart and trustworthy, and it sounds just as confident when it's wrong. That's why I spent this project making it *prove* it works: measuring fairness across hundreds of profiles, checking that results never drift, and making sure neither I nor an AI agent could quietly move the targets.
