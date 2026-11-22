# System Diagram

How the music recommender is organized: data flows from input to recommendations (top), the evaluator and tests check the results (middle), and an AI agent's code changes must pass the gate and a human review before they are kept (bottom).

```mermaid
flowchart TD
    %% ---------- Input ----------
    subgraph IN["1 - Input"]
        CSV[("data/songs.csv<br/>45 songs")]
        USER["User profile from the command line<br/>python -m src.main --genre --mood --energy --acoustic --k"]
    end

    %% ---------- Recommender ----------
    subgraph REC["2 - Recommender  (src/recommender.py)"]
        LOAD["Data guardrails<br/>load_songs: required columns, 0-1 ranges<br/>validate_prefs: types, aliases, case"]
        SCORE["Scorer<br/>score_song: genre + mood + energy + acoustic<br/>each point comes with a reason"]
        RANK["Ranker<br/>rank_songs: sort by score, ties by song id"]
        DIV["Diversity guardrail<br/>max 1 song per artist"]
        CONF["Confidence check<br/>warn if top score under 40% of max"]
    end

    %% ---------- Output ----------
    subgraph OUT["3 - Output"]
        RESULT["Top k songs printed by src/main.py<br/>score, match %, reasons, Note: warnings<br/>or Error: message + exit code 2"]
        LOG[("logs/recommender.log")]
    end

    CSV --> LOAD
    USER --> LOAD
    LOAD --> SCORE --> RANK --> DIV --> CONF --> RESULT
    CONF --> LOG

    %% ---------- Testing ----------
    subgraph TEST["4 - Automated checks"]
        PYTEST["pytest: 95 tests<br/>demo CLI, guardrails, consistency, diversity, gate"]
        EVAL["Evaluator  (src/evaluate.py)<br/>360 fixed profiles vs random baseline<br/>diversity, fairness, consistency<br/>10 PASS/FAIL checks + fingerprint"]
    end

    REC -. tested by .-> PYTEST
    REC -. evaluated by .-> EVAL

    %% ---------- Agent loop ----------
    subgraph AGENT["5 - Agentic write / test / fix loop"]
        AI["AI coding agent<br/>external tool, not part of this repo<br/>may only edit src/recommender.py"]
        BASE[("logs/agent_baseline.json<br/>tests, checks, fingerprint, file hashes")]
        GATE{"Agent gate  (src/agent_gate.py check)<br/>protected files unchanged?<br/>no cheating patterns in diff?<br/>no test or check regressed?<br/>result change explained?"}
        RUNLOG[("logs/agent_runs.jsonl")]
    end

    BASE -- compared against --> GATE
    AI -- proposes code change --> GATE
    GATE -- runs --> PYTEST
    GATE -- runs --> EVAL
    GATE -- rejected: list of problems --> AI
    GATE --> RUNLOG

    %% ---------- Humans ----------
    HUMAN(["Human review<br/>reads diff + before/after metrics<br/>approves data changes  --allow-data<br/>merges, then reruns baseline"])
    CARD["README + model card<br/>bias findings, weights"]

    GATE -- accepted --> HUMAN
    HUMAN -- merge --> REC
    RESULT -. spot-checked by .-> HUMAN
    EVAL -- report --> HUMAN
    HUMAN -- documents --> CARD

    classDef human fill:#fde68a,stroke:#b45309,color:#1f2937
    classDef check fill:#bbf7d0,stroke:#15803d,color:#1f2937
    classDef ai fill:#ddd6fe,stroke:#6d28d9,color:#1f2937
    class HUMAN,CARD human
    class PYTEST,EVAL,GATE check
    class AI ai
```

## Key

| Color | Meaning |
|---|---|
| Yellow | A human checks or decides |
| Green | Automated testing checks AI and code results |
| Purple | The AI agent that writes and fixes code (an outside tool; the repo provides the gate it must pass) |

**Where results are checked**

- **Guardrails inside the recommender** reject bad data and bad input, cap repeat artists, and flag low-confidence results.
- **pytest** checks behavior on every change. Consistency tests make sure the same question always gets the same answer.
- **The evaluator** measures genre diversity and fairness across 360 profiles. Its two current failures (metal exposure and metal fans' hit rate) are real bias findings, reported in the model card instead of hidden.
- **The agent gate** compares a change with the saved baseline. It accepts an AI-written change only if no test or check gets worse and no protected file (tests, thresholds, data) was touched.
- **A human** has the final say: they review every accepted change, approve any data change, and record findings in the model card.
