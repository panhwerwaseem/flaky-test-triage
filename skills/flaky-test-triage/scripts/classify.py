#!/usr/bin/env python3
"""Suggest likely root-cause buckets for a flaky test from repro.py output.

Reads summary.json and the failure logs written by repro.py, matches them
against known flake patterns, and prints ranked hypotheses with the evidence
lines and the next check to run for each.

These are hints to direct the investigation. They are not a diagnosis: confirm
a hypothesis by making the failure deterministic before changing code.

Usage:
  classify.py                       # reads .flaky-triage/
  classify.py --dir path/to/out     # reads another repro.py output directory
  classify.py --json                # machine-readable output

Standard library only. Reads files only. Makes no network calls.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# bucket -> (section title in references/root-causes.md, next check, patterns)
BUCKETS = {
    "async-timing": (
        "Async and timing",
        "Find the wait that races. Replace fixed sleeps with a wait on the real condition.",
        [
            r"timed? ?out waiting",
            r"element .*(not found|not visible|detached)",
            r"waiting for (selector|locator|element)",
            r"was not awaited|unhandled promise|act\(\)",
            r"exceeded timeout of \d+ ?ms",
            r"toHaveBeenCalled|not called|called 0 times|still running|not (yet )?(ready|finished|done)",
        ],
    ),
    "order-shared-state": (
        "Test order and shared state",
        "Run the test alone, then after each neighbour, then in reversed and shuffled order.",
        [
            r"already exists|duplicate key|unique constraint|IntegrityError",
            r"KeyError|NoneType|undefined is not|cannot read propert(y|ies) of (undefined|null)",
            r"expected \[?\]? ?(to be empty|0|empty)|not empty",
            r"singleton|global state|stale cache|fixture .* not found|leaked|left over|leftover",
        ],
    ),
    "time-date": (
        "Clock, date and timezone",
        "Re-run with a fixed clock and with TZ set to UTC and to a far-offset zone.",
        [
            r"\b\d{4}-\d{2}-\d{2}\b.*(expected|!=|==|to equal)",
            r"timezone|tzinfo|UTC|DST|daylight|midnight|leap",
            r"datetime|Date\.now|System\.currentTimeMillis|time\.Now",
        ],
    ),
    "randomness": (
        "Unseeded randomness and ordering",
        "Capture the seed from a failing run and replay it. Check hash and map iteration order.",
        [
            r"\brandom\b|\brand\(|uuid|faker|shuffle|\bseed\b",
            r"hypothesis|property-based|falsifying example",
            r"dict(ionary)? order|set order|unordered|HashMap",
        ],
    ),
    "network-external": (
        "Network and external services",
        "List every host the test contacts. Replace each with a local fake or recorded response.",
        [
            r"ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND",
            r"connection (refused|reset|aborted|timed out)",
            r"\b(502|503|504|429)\b|rate limit|service unavailable",
            r"SSL|TLS|certificate|DNS|socket hang up",
        ],
    ),
    "resource-collision": (
        "Ports, files and other shared resources",
        "Run two copies at once (repro.py --jobs 2). Give each run its own port, temp dir and database.",
        [
            r"EADDRINUSE|address already in use|port \d+ is (already )?in use",
            r"EEXIST|file exists|ENOENT|no such file|permission denied|EBUSY|locked",
            r"too many open files|EMFILE|out of memory|OOM|no space left",
            r"database is locked|deadlock detected|lock wait timeout",
        ],
    ),
    "concurrency": (
        "Races and deadlocks in the code under test",
        "Run under the race detector or thread sanitizer for the language, and under --jobs.",
        [
            r"data race|race condition|WARNING: DATA RACE|ThreadSanitizer",
            r"deadlock|ConcurrentModification|concurrent map (read|write)",
            r"goroutine \d+|mutex|semaphore|lost update|torn read",
        ],
    ),
}


def load_logs(out_dir):
    logs = {}
    for path in sorted(out_dir.glob("run-[0-9]*.log")):
        logs[path.name] = path.read_text(encoding="utf-8", errors="replace")
    return logs


def score_buckets(logs):
    results = []
    for bucket, (section, next_check, patterns) in BUCKETS.items():
        matched_patterns = 0
        evidence = []
        for pattern in patterns:
            regex = re.compile(pattern, re.I)
            hit = False
            for name, text in logs.items():
                for line in text.splitlines():
                    if regex.search(line):
                        hit = True
                        snippet = "%s: %s" % (name, line.strip()[:160])
                        if snippet not in evidence and len(evidence) < 3:
                            evidence.append(snippet)
                        break
            if hit:
                matched_patterns += 1
        if matched_patterns:
            results.append({
                "bucket": bucket,
                "section": section,
                "matched_patterns": matched_patterns,
                "evidence": evidence,
                "next_check": next_check,
            })
    results.sort(key=lambda r: r["matched_patterns"], reverse=True)
    return results


def run_signals(summary):
    """Signals that come from how the runs behaved, not from log text."""
    signals = []
    runs = summary.get("runs", [])
    if any(r.get("status") == "timeout" for r in runs):
        signals.append("At least one run hit the timeout: suspect a hang, deadlock, or a wait "
                       "that never resolves, before suspecting slowness.")
    mean_pass = summary.get("mean_pass_duration_s")
    mean_fail = summary.get("mean_fail_duration_s")
    if mean_pass and mean_fail and mean_fail > mean_pass * 1.5:
        signals.append("Failing runs are much slower than passing runs (%.3fs vs %.3fs): "
                       "suspect a timing or timeout cause." % (mean_fail, mean_pass))
    if len(summary.get("signatures", {})) > 1:
        signals.append("%d distinct failure signatures: more than one flake is present. "
                       "Triage each signature separately." % len(summary["signatures"]))
    if summary.get("jobs", 1) > 1:
        signals.append("Runs used --jobs %d. Re-measure with --jobs 1: if the failures "
                       "disappear, the cause is a resource shared between runs." % summary["jobs"])
    failing_seeds = [r["seeds"] for r in runs if r.get("status") != "pass" and r.get("seeds")]
    if failing_seeds:
        signals.append("Seeds of failing runs (replay one to test for determinism): %s"
                       % json.dumps(failing_seeds[:3]))
    return signals


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=".flaky-triage", help="repro.py output directory")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)

    out_dir = Path(args.dir)
    summary_path = out_dir / "summary.json"
    if not summary_path.is_file():
        print("no summary.json in %s; run repro.py first" % out_dir, file=sys.stderr)
        return 2
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    logs = load_logs(out_dir)

    result = {
        "failures": summary.get("failures", 0),
        "signals": run_signals(summary),
        "hypotheses": score_buckets(logs) if logs else [],
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    if not result["failures"]:
        print("No failures recorded. Nothing to classify: reproduce the flake first.")
        return 0
    print("Hints only. Confirm by making the failure deterministic before editing code.\n")
    for signal in result["signals"]:
        print("signal: " + signal)
    if result["signals"]:
        print("")
    if not result["hypotheses"]:
        print("No known pattern matched the failure logs. Read the logs directly and compare "
              "a failing log with run-pass-sample.log.")
        return 0
    for rank, hyp in enumerate(result["hypotheses"], 1):
        print("%d. %s  [%s, %d pattern(s) matched]" % (
            rank, hyp["section"], hyp["bucket"], hyp["matched_patterns"]))
        for line in hyp["evidence"]:
            print("     " + line)
        print("   next: " + hyp["next_check"])
    print("\nSee references/root-causes.md for the diagnosis and fix for each bucket.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
