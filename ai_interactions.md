# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agentic Workflow (SF8)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**Agent used:** Claude Code (Claude Opus) inside VS Code. It could read files, run shell commands (`pytest`, `python -m src.evaluate`), and edit files, with each tool call shown to me as it happened.

**Starting point: genre bias testing, built with AI.** Before the agent workflow, I added bias testing so that every genre is checked for fair treatment, including less common ones like metal. I worked on it with AI. I decided the steps and guardrails, the AI wrote the code, and I reviewed the results.

- **What I determined:** what to test (every genre's fans, plus a fair share of recommendations for every genre), how to build the test profiles (all 15 genres × 4 moods × 3 energy levels × acoustic yes/no = 360 profiles, with no hand-picking), and the guardrails. The pass/fail targets were set *before* looking at any results, the runs had to be repeatable (fixed seed, a fingerprint of all results), and there had to be a random recommender to compare against.
- **What the AI built:** the evaluator (`src/evaluate.py`) that runs those profiles and calculates the measures, plus tests that check the formulas are correct.
- **What I reviewed:** the results. Metal gets only 0.20× its fair share of recommendations, and metal fans see a metal song in only 33% of their lists (the target is 50%). I checked why: all three metal songs have energy of 0.89 or higher, and energy is the largest weight. I decided to report these as real bias findings instead of changing the targets to make them pass. Protecting them became the main reason for building the agent gate: the easiest way for an agent to "fix" the metal failures would be to lower the target, not to make the recommender fairer.

**What task did you give the agent?**

To design and build a safe workflow for letting an AI agent write, test, and fix code in this project. The goal was that an agent could never "pass" by cheating, given that I had just added tests for consistency and genre diversity. After that, I used the same agent to document the project: the system diagram, README, model card, and a check against the grading rubric.

**Prompts used:**

| Step | Prompt (as I typed it) | What it led to |
|---|---|---|
| 1 | "If I want to include the following AI feature: Agentic Workflow that writes, tests, and fixes code automatically. What are some guardrails and steps required for this that are appropriate to the project and the fact that I just included testing system that tests and gives more consistent answers for genre diversity." | A plan of 8 guardrails and an 8-step loop, based on my actual code (`THRESHOLDS`, the fingerprint, the two metal failures) |
| 2 | "yes, build the gate script and planted-bug test" | `src/agent_gate.py` and `tests/test_agent_gate.py` |
| 3 | "Show how your project is organized by creating a short system diagram..." | `diagrams/system_diagram.md` (Mermaid) |
| 4 | "Rewrite the README file that clearly explains your project..." | New `README.md` with real sample output |
| 5 | "update the model card with the agent gate and 89 tests" | Agent gate and test sections added to `model_card.md` |
| 6 | Pasted the reliability requirements, adding "under Reliability and Evaluation" | The README's Reliability and Evaluation tables, including a 10-profile human evaluation |
| 7 | Pasted the reflection questions, adding "fix the model_card.md to be more concise and accurate to the actual model" | A shorter model card, with sections on limitations, misuse, testing surprises, and AI collaboration |
| 8 | Pasted the grading rubric, adding "Ensure this project meets the following required features" | A check against the rubric, which found 3 gaps (below) |

**What did the agent generate or change?**

- **`src/agent_gate.py` (new):** `baseline` and `check` commands. The gate hashes protected files (tests, `src/evaluate.py`, data, config, and the gate itself). It scans the diff for randomness, hard-coded genre or artist names, and song-id special cases. It runs pytest and the evaluator, rejects any test or check that got worse, requires an explanation when results change, and logs every attempt to `logs/agent_runs.jsonl`.
- **`tests/test_agent_gate.py` (new, 29 tests):** unit tests for each cheating shortcut, plus two end-to-end tests that run on a copy of the project:
  - a planted bug (energy formula `1 - abs` changed to `1 + abs`) is rejected, and its fix is accepted;
  - lowering the metal threshold from 0.50 to 0.30 is rejected.
- **`src/main.py` (changed):** command-line options (`--genre`, `--mood`, `--energy`, `--acoustic`, `--k`) and clean `Error:` messages with exit code 2.
- **`tests/test_main.py` (new, 6 tests):** tests for the command-line demo, including a check that the same command always gives the same output.
- **`pytest.ini`:** registered a `slow` marker so `pytest -m "not slow"` skips the end-to-end gate tests.
- **Documentation:** `diagrams/system_diagram.md`, `README.md`, and `model_card.md`.
- **Commands it ran to check its work:** `pytest` after each change (60 → 89 → 95 tests, all passing), `python -m src.evaluate` to confirm the numbers quoted in the docs, the gate on a scratch copy with the planted bug, and short scripts to get real output for each sample in the README.

**What did you verify or fix manually?**

The agent made mistakes. Some it caught itself by running the code, and some only came out when I asked it to check the work against requirements:

| Problem | How it was caught | Fix |
|---|---|---|
| `--root` only worked before the command name, so the first end-to-end gate tests failed | Running `pytest` | Shared options added to both commands |
| The README cited the wrong match % for Gym Hero (62% instead of 83%) and called its mood a "family" match when it was exact | Agent re-checked its claims against the real output | Corrected before I saw the final version |
| The diagram showed a "max 3–5 tries" retry loop and an AI agent as if they were built into the project | My rubric check ("Diagram matches actual project implementation") | Agent shown as an outside tool; retry limit removed |
| README samples were hand-trimmed, and `main.py` couldn't reproduce most of them | My rubric check | Added command-line options; pasted exact, unedited output |
| Every warning printed twice in the console | Running the new commands | The console log handler stays quiet; warnings still go to the log file |
| The README and model card still listed the original weights (genre 1.5, energy 1.5) after I had changed them to 0.75 and 3.0 | Agent compared the docs with the code | Docs updated to the current weights |

What I decided myself:

- **Scoped the plan down.** The agent first proposed a full agent loop with retry limits, sandboxing, and a docs-sync test. I asked only for the gate and the planted-bug test.
- **Kept `requirements.txt` unchanged.** The agent pointed out that pandas and streamlit aren't imported anywhere. I chose not to remove anything.
- **Reviewed the claims written in my voice.** The agent flagged every statement it wrote as mine (the human evaluation verdicts, my reasons in the model card, and facts about my Modules 1–3 project) so I could check and edit them.
- **Kept the two failing metal checks visible.** Both stay in the report as real bias findings, instead of being tuned away.

**What I learned:** the agent was most useful when it could check itself. Running the tests caught its code bugs, and comparing claims with real output caught its documentation errors. The mistakes it couldn't catch alone (the diagram describing features that didn't exist, trimmed samples) were caught by checking against a clear, written standard. That is the same idea behind the agent gate.

---

## Design Pattern (SF10)

Not attempted for this project.
