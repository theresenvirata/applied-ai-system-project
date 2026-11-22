"""
Agent gate: the acceptance check an automated write/test/fix agent must pass.

An agent told to "make the tests pass" can cheat by editing the tests, lowering the
evaluation thresholds, special-casing a genre, or adding randomness. This gate makes
those shortcuts fail, so the only way through is a real fix.

Run from the project root:
    python -m src.agent_gate baseline                       # 1. snapshot the current state
    ... agent edits src/recommender.py ...
    python -m src.agent_gate check --goal "fix X" \\
        --explain "why the results changed"                  # 2. accept or reject the attempt

Exit code 0 = accepted, 1 = rejected. Every check is appended to logs/agent_runs.jsonl.
An accepted attempt still needs a human review before merging. After merging, run
`baseline` again so the next attempt is compared against the new state.

Rules (an attempt is rejected if any of these fails):
  1. Only ALLOWED_FILES changed. Tests, src/evaluate.py (thresholds, seed, fingerprint),
     this gate, the data and the config are protected. New or deleted files are rejected too.
     Data changes need a human: pass --allow-data.
  2. The diff of the allowed files adds no randomness, clock or environment reads,
     test skips, song-id special cases, or hard-coded genre/artist/title literals.
  3. Every test passes, and no test that passed before is now missing or skipped.
  4. No evaluation check that passed before now fails, and every consistency check passes.
  5. If the result fingerprint changed, --explain must say why.
"""

import argparse
import ast
import csv
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The only files the agent may change.
ALLOWED_FILES = ("src/recommender.py",)

# Everything here is hashed. Any change outside ALLOWED_FILES rejects the attempt.
WATCHED_PATTERNS = ("src/**/*.py", "tests/**/*.py", "data/**/*", "requirements.txt", "pytest.ini")
DATA_PREFIX = "data/"

# The gate's own tests copy the project and run the gate, so they are not run by the gate.
GATE_TEST_FILE = "tests/test_agent_gate.py"

BASELINE_FILE = "logs/agent_baseline.json"
RUN_LOG_FILE = "logs/agent_runs.jsonl"
DEFAULT_TIMEOUT = 300  # seconds for each pytest / evaluation run

CONSISTENCY_PREFIX = "Consistency:"

# Patterns that are never allowed in lines the agent adds.
BANNED_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"^\s*(import|from)\s+(random|time|datetime|uuid|secrets)\b", "imports a non-deterministic module"),
    (r"\b(random|uuid|secrets)\.\w+", "uses randomness"),
    (r"\b(time|datetime)\.(time|now|today|perf_counter|monotonic)\b", "reads the clock"),
    (r"\bos\.environ\b|\bgetenv\(", "reads environment variables"),
    (r"pytest\.mark\.(skip|skipif|xfail)|pytest\.(skip|xfail)\(", "skips or xfails a test"),
    (r"\[\s*['\"]id['\"]\s*\]\s*(==|!=|\bin\b)", "special-cases a song id"),
    (r"\b(subprocess|socket|requests|urllib)\b", "runs processes or uses the network"),
)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def watched_files(root: Path) -> List[str]:
    """Paths (relative, forward slashes) of every watched file under root."""
    found = set()
    for pattern in WATCHED_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def hash_files(root: Path) -> Dict[str, str]:
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in watched_files(root)}


def read_allowed_sources(root: Path) -> Dict[str, str]:
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in ALLOWED_FILES if (root / rel).exists()}


def banned_literals(root: Path) -> Set[str]:
    """Genres, artists and titles from the catalog. Scoring code must not name them directly."""
    path = root / "data" / "songs.csv"
    if not path.exists():
        return set()
    names, moods = set(), set()
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for field in ("genre", "artist", "title"):
                if row.get(field):
                    names.add(row[field].strip().lower())
            if row.get("mood"):
                moods.add(row["mood"].strip().lower())
    return names - moods  # mood names are legitimately used in MOOD_FAMILIES


# ---------------------------------------------------------------------------
# Diff scan
# ---------------------------------------------------------------------------

def added_line_numbers(old: str, new: str) -> Set[int]:
    """1-based line numbers in `new` that were inserted or replaced."""
    matcher = difflib.SequenceMatcher(a=old.splitlines(), b=new.splitlines(), autojunk=False)
    added = set()
    for tag, _, _, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            added.update(range(j1 + 1, j2 + 1))
    return added


def _string_literals(source: str) -> List[Tuple[int, str]]:
    """(line, value) for each plain string literal. f-strings and broken code are skipped."""
    literals = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.STRING:
                try:
                    value = ast.literal_eval(tok.string)
                except (ValueError, SyntaxError):
                    continue
                if isinstance(value, str):
                    literals.append((tok.start[0], value))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        pass
    return literals


def scan_diff(old: str, new: str, literals: Set[str], filename: str = "") -> List[str]:
    """Problems found in the lines added between old and new."""
    added = added_line_numbers(old, new)
    lines = new.splitlines()
    problems = []
    for n in sorted(added):
        code = lines[n - 1].split("#", 1)[0]  # rough comment strip; good enough for these patterns
        for pattern, reason in BANNED_PATTERNS:
            if re.search(pattern, code):
                problems.append(f"{filename}:{n} {reason}: {lines[n - 1].strip()}")
    for n, value in _string_literals(new):
        if n in added and value.strip().lower() in literals:
            problems.append(f"{filename}:{n} hard-codes catalog value {value!r}: {lines[n - 1].strip()}")
    return problems


# ---------------------------------------------------------------------------
# Running tests and the evaluation
# ---------------------------------------------------------------------------

def _env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    return env


def run_tests(root: Path, timeout: int = DEFAULT_TIMEOUT) -> Dict:
    """Runs pytest and returns {"outcomes": {test_id: passed|failed|skipped}, "error": str|None}."""
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = os.path.join(tmp, "results.xml")
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               f"--junitxml={xml_path}", f"--ignore={GATE_TEST_FILE}"]
        try:
            proc = subprocess.run(cmd, cwd=root, env=_env(), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"outcomes": {}, "error": f"pytest timed out after {timeout}s"}
        if not os.path.exists(xml_path):
            return {"outcomes": {}, "error": f"pytest produced no results (exit {proc.returncode}): "
                                             f"{(proc.stdout + proc.stderr)[-500:]}"}
        outcomes = {}
        for case in ET.parse(xml_path).getroot().iter("testcase"):
            test_id = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None or case.find("error") is not None:
                outcomes[test_id] = "failed"
            elif case.find("skipped") is not None:
                outcomes[test_id] = "skipped"
            else:
                outcomes[test_id] = "passed"
        return {"outcomes": outcomes, "error": None}


def run_eval(root: Path, timeout: int = DEFAULT_TIMEOUT) -> Dict:
    """Runs src.evaluate and returns its checks, fingerprint and weights."""
    with tempfile.TemporaryDirectory() as tmp:
        json_path = os.path.join(tmp, "report.json")
        cmd = [sys.executable, "-m", "src.evaluate", "--json", json_path]
        try:
            proc = subprocess.run(cmd, cwd=root, env=_env(), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"error": f"evaluation timed out after {timeout}s"}
        if not os.path.exists(json_path):  # exit 1 just means some checks failed; a missing report means a crash
            return {"error": f"evaluation crashed (exit {proc.returncode}): {(proc.stdout + proc.stderr)[-500:]}"}
        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
    return {
        "error": None,
        "checks": {c["name"]: c["passed"] for c in report["checks"]},
        "details": {c["name"]: c["detail"] for c in report["checks"]},
        "fingerprint": report["fingerprint"],
        "weights": report["settings"]["weights"],
    }


def snapshot(root: Path, timeout: int = DEFAULT_TIMEOUT) -> Dict:
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hashes": hash_files(root),
        "allowed_sources": read_allowed_sources(root),
        "tests": run_tests(root, timeout),
        "eval": run_eval(root, timeout),
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare(baseline: Dict, current: Dict, explain: str = "", allow_data: bool = False) -> Dict[str, List[str]]:
    """
    Applies the rules to two snapshots. Returns {"problems", "warnings", "notes"};
    the attempt is accepted only if "problems" is empty.
    """
    problems: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    # Rule 1: only allowed files changed
    before, after = baseline["hashes"], current["hashes"]
    for rel in sorted(set(before) | set(after)):
        if rel in ALLOWED_FILES or before.get(rel) == after.get(rel):
            continue
        change = "added" if rel not in before else "deleted" if rel not in after else "modified"
        if rel.startswith(DATA_PREFIX) and allow_data:
            warnings.append(f"data file {change} (human-approved with --allow-data): {rel}")
        elif rel.startswith(DATA_PREFIX):
            problems.append(f"protected file {change}: {rel} (data changes need a human; rerun with --allow-data)")
        else:
            problems.append(f"protected file {change}: {rel}")

    # Rule 3: tests
    base_tests, cur_tests = baseline["tests"], current["tests"]
    if cur_tests.get("error"):
        problems.append(f"tests could not run: {cur_tests['error']}")
    else:
        base_out, cur_out = base_tests.get("outcomes", {}), cur_tests["outcomes"]
        for test_id, outcome in sorted(base_out.items()):
            if outcome == "passed" and cur_out.get(test_id) != "passed":
                problems.append(f"test {test_id}: passed before, now {cur_out.get(test_id, 'missing')}")
        for test_id, outcome in sorted(cur_out.items()):
            if outcome == "failed" and base_out.get(test_id) != "passed":
                problems.append(f"test {test_id}: failing")
        if len(cur_out) < len(base_out):
            problems.append(f"test count dropped from {len(base_out)} to {len(cur_out)}")

    # Rules 4 and 5: evaluation
    base_eval, cur_eval = baseline["eval"], current["eval"]
    if cur_eval.get("error"):
        problems.append(f"evaluation could not run: {cur_eval['error']}")
    elif not base_eval.get("error"):
        base_checks, cur_checks = base_eval["checks"], cur_eval["checks"]
        for name, passed in base_checks.items():
            if passed and not cur_checks.get(name, False):
                detail = cur_eval["details"].get(name, "check missing")
                problems.append(f"evaluation check regressed: {name} ({detail})")
            elif not passed and cur_checks.get(name):
                notes.append(f"evaluation check now passes: {name}")
        for name, passed in cur_checks.items():
            if name.startswith(CONSISTENCY_PREFIX) and not passed and base_checks.get(name) is not True:
                problems.append(f"consistency check failing: {name} ({cur_eval['details'][name]})")

        if cur_eval["fingerprint"] != base_eval["fingerprint"]:
            if explain.strip():
                notes.append(f"results changed (fingerprint {base_eval['fingerprint'][:12]} -> "
                             f"{cur_eval['fingerprint'][:12]}); explanation: {explain.strip()}")
            else:
                problems.append("results changed (fingerprint differs) but no --explain was given")

        if cur_eval["weights"] != base_eval["weights"]:
            changed = {k: (base_eval["weights"].get(k), v) for k, v in cur_eval["weights"].items()
                       if base_eval["weights"].get(k) != v}
            warnings.append(f"weights changed {changed}: update the README weight table and model card")

    return {"problems": problems, "warnings": warnings, "notes": notes}


def scan_all(baseline: Dict, root: Path) -> List[str]:
    """Rule 2: scan every allowed file's diff against the baseline copy."""
    literals = banned_literals(root)
    problems = []
    for rel, new in read_allowed_sources(root).items():
        problems += scan_diff(baseline["allowed_sources"].get(rel, ""), new, literals, rel)
    return problems


def unified_diff(baseline: Dict, root: Path) -> str:
    chunks = []
    for rel, new in read_allowed_sources(root).items():
        old = baseline["allowed_sources"].get(rel, "")
        chunks += difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}")
    return "".join(chunks)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _passed_count(tests: Dict) -> int:
    return sum(1 for o in tests.get("outcomes", {}).values() if o == "passed")


def _eval_passed(ev: Dict) -> Optional[int]:
    return None if ev.get("error") else sum(ev["checks"].values())


def cmd_baseline(root: Path, timeout: int) -> int:
    snap = snapshot(root, timeout)
    path = root / BASELINE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")

    tests, ev = snap["tests"], snap["eval"]
    print(f"Baseline saved to {BASELINE_FILE}")
    print(f"  files watched: {len(snap['hashes'])} (agent may edit: {', '.join(ALLOWED_FILES)})")
    test_summary = tests["error"] or f"{_passed_count(tests)}/{len(tests['outcomes'])} passed"
    print(f"  tests: {test_summary}")
    if ev.get("error"):
        print(f"  evaluation: {ev['error']}")
    else:
        print(f"  evaluation: {_eval_passed(ev)}/{len(ev['checks'])} checks pass, fingerprint {ev['fingerprint'][:16]}...")
    if tests["error"] or ev.get("error") or any(o == "failed" for o in tests["outcomes"].values()):
        print("  WARNING: the baseline is not clean. Fix it before letting an agent run.")
    return 0


def cmd_check(root: Path, timeout: int, goal: str, explain: str, allow_data: bool) -> int:
    path = root / BASELINE_FILE
    if not path.exists():
        print(f"No baseline found at {BASELINE_FILE}. Run `python -m src.agent_gate baseline` first.")
        return 1
    baseline = json.loads(path.read_text(encoding="utf-8"))
    current = snapshot(root, timeout)

    result = compare(baseline, current, explain, allow_data)
    result["problems"] = scan_all(baseline, root) + result["problems"]
    accepted = not result["problems"]

    record = {
        "checked_at": current["taken_at"],
        "baseline_at": baseline["taken_at"],
        "goal": goal,
        "explanation": explain,
        "accepted": accepted,
        **result,
        "tests_passed": {"before": _passed_count(baseline["tests"]), "after": _passed_count(current["tests"])},
        "eval_passed": {"before": _eval_passed(baseline["eval"]), "after": _eval_passed(current["eval"])},
        "fingerprint": {"before": baseline["eval"].get("fingerprint"), "after": current["eval"].get("fingerprint")},
        "diff": unified_diff(baseline, root),
    }
    log_path = root / RUN_LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    print("=" * 72)
    print(f" Agent gate: {'ACCEPTED' if accepted else 'REJECTED'}" + (f"  ({goal})" if goal else ""))
    print("=" * 72)
    print(f" Tests passed:      {record['tests_passed']['before']} -> {record['tests_passed']['after']}")
    print(f" Evaluation checks: {record['eval_passed']['before']} -> {record['eval_passed']['after']} passing")
    for title, key in (("Problems (must fix)", "problems"), ("Warnings", "warnings"), ("Notes", "notes")):
        if result[key]:
            print(f"\n {title}:")
            for line in result[key]:
                print(f"   - {line}")
    if not record["diff"]:
        print("\n No changes to the allowed files.")
    print(f"\n Logged to {RUN_LOG_FILE}")
    if accepted:
        print(" Next: a human reviews the diff, then merges and reruns `baseline`.")
    print("=" * 72)
    return 0 if accepted else 1


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(PROJECT_ROOT), help="project root (default: this project)")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per test/eval run")
    parser = argparse.ArgumentParser(description="Acceptance gate for automated code changes.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("baseline", parents=[common], help="snapshot tests, evaluation and file hashes")
    check = sub.add_parser("check", parents=[common], help="compare the current state with the baseline")
    check.add_argument("--goal", default="", help="what the agent was trying to do")
    check.add_argument("--explain", default="", help="why the recommendations changed (needed if they did)")
    check.add_argument("--allow-data", action="store_true", help="HUMAN ONLY: accept changes to data/")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.command == "baseline":
        return cmd_baseline(root, args.timeout)
    return cmd_check(root, args.timeout, args.goal, args.explain, args.allow_data)


if __name__ == "__main__":
    sys.exit(main())
