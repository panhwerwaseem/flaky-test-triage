#!/usr/bin/env python3
"""Run a test command many times and report how often, and how, it fails.

Two modes:

  measure  Run the command --runs times and report the failure rate, the
           distinct failure signatures, and how many passing runs a fix needs
           before it can be called verified.
  verify   Prove a fix. Given the failure rate measured before the fix
           (--baseline-rate), run the command enough times that an unfixed
           test would almost certainly have failed. Stops at the first failure.

The command goes after "--" and is executed directly, without a shell.

Examples:
  repro.py --runs 50 -- pytest tests/test_cache.py::test_eviction -x
  repro.py --runs 50 --jobs 4 --seed-env PYTHONHASHSEED -- pytest tests/test_cache.py
  repro.py --mode verify --baseline-rate 0.06 -- pytest tests/test_cache.py::test_eviction

Exit codes: 0 = every run passed, 1 = at least one run failed, 2 = usage error.
Standard library only. Makes no network calls. Writes only inside --out.
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ERROR_LINE_RE = re.compile(
    r"(error|exception|fail|assert|panic|timeout|timed out|traceback|expected|refused|killed|segmentation)",
    re.I,
)
# Lines that state the error itself, e.g. "AssertionError: None != 42",
# "java.lang.IllegalStateException: closed", "panic: nil map", "--- FAIL: TestX".
STRONG_LINE_RE = re.compile(
    r"^\s*(?:E\s+)?[\w.$]*(?:Error|Exception|Failure)\b.*:"
    r"|^\s*panic:|^\s*--- FAIL:|^\s*Caused by:|^\s*thread '.*' panicked"
)
MAX_SAVED_FAILURE_LOGS = 20


def normalise(line):
    """Strip run-specific detail so the same failure hashes the same way."""
    line = re.sub(r"0x[0-9a-fA-F]+", "<hex>", line)
    line = re.sub(r"\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds|us|ns)\b", "<dur>", line)
    line = re.sub(r"\d+", "<n>", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line[:200]


def signature_of(output, status):
    """Return (short hash, representative lines) describing one failure."""
    if status == "timeout":
        return "timeout", ["command exceeded --timeout"]
    lines = [l for l in output.splitlines() if l.strip()]
    # Prefer the lines that state the error. Sorting makes the signature
    # independent of the order in which several tests reported the same error.
    picked = sorted(set(normalise(l) for l in lines if STRONG_LINE_RE.search(l)))[:5]
    if not picked:
        for line in lines:
            if ERROR_LINE_RE.search(line):
                norm = normalise(line)
                if norm not in picked:
                    picked.append(norm)
            if len(picked) == 5:
                break
    if not picked:
        picked = [normalise(l) for l in lines[-3:]] or ["(no output)"]
    digest = hashlib.sha1("\n".join(picked).encode("utf-8")).hexdigest()[:10]
    return digest, picked


def runs_needed(failure_rate, confidence):
    """Passing runs needed so a test still failing at failure_rate would have
    been caught with the given confidence: n >= ln(1 - confidence) / ln(1 - rate)."""
    if failure_rate <= 0:
        return None
    if failure_rate >= 1:
        return 1
    return int(math.ceil(math.log(1.0 - confidence) / math.log(1.0 - failure_rate)))


def run_once(index, command, timeout, seed_envs, cwd):
    env = os.environ.copy()
    seeds = {}
    for name in seed_envs:
        seeds[name] = random.randrange(1, 2 ** 31)
        env[name] = str(seeds[name])
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        output = proc.stdout.decode("utf-8", errors="replace")
        status = "pass" if proc.returncode == 0 else "fail"
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b"").decode("utf-8", errors="replace")
        status = "timeout"
        exit_code = None
    duration = round(time.time() - started, 3)
    record = {
        "index": index,
        "status": status,
        "exit_code": exit_code,
        "duration_s": duration,
        "seeds": seeds,
    }
    if status != "pass":
        record["signature"], record["signature_lines"] = signature_of(output, status)
    return record, output


def mean(values):
    return round(sum(values) / len(values), 3) if values else None


def summarise(records, args, planned_runs, baseline_needed):
    failures = [r for r in records if r["status"] != "pass"]
    passes = [r for r in records if r["status"] == "pass"]
    total = len(records)
    rate = (len(failures) / float(total)) if total else 0.0
    signatures = {}
    for rec in failures:
        entry = signatures.setdefault(
            rec["signature"], {"count": 0, "lines": rec["signature_lines"], "runs": []}
        )
        entry["count"] += 1
        entry["runs"].append(rec["index"])
    summary = {
        "mode": args.mode,
        "command": args.command,
        "jobs": args.jobs,
        "seed_envs": args.seed_env,
        "planned_runs": planned_runs,
        "completed_runs": total,
        "failures": len(failures),
        "failure_rate": round(rate, 4),
        "mean_pass_duration_s": mean([r["duration_s"] for r in passes]),
        "mean_fail_duration_s": mean([r["duration_s"] for r in failures]),
        "signatures": signatures,
        "runs": [{k: v for k, v in r.items() if k != "signature_lines"} for r in records],
    }
    if args.mode == "measure":
        summary["verify_runs_needed"] = runs_needed(rate, args.confidence) if failures else None
    else:
        summary["baseline_rate"] = args.baseline_rate
        summary["verify_runs_needed"] = baseline_needed
        summary["verified"] = not failures and total >= baseline_needed
    return summary


def print_summary(summary, out_dir, confidence):
    total = summary["completed_runs"]
    failed = summary["failures"]
    pct = int(round(confidence * 100))
    print("mode: %s   runs: %d/%d   failures: %d   failure rate: %.1f%%" % (
        summary["mode"], total, summary["planned_runs"], failed, summary["failure_rate"] * 100))
    if summary["mean_pass_duration_s"] is not None and summary["mean_fail_duration_s"] is not None:
        print("mean duration: pass %.3fs, fail %.3fs" % (
            summary["mean_pass_duration_s"], summary["mean_fail_duration_s"]))
    for digest, entry in summary["signatures"].items():
        print("signature %s  x%d  (runs %s)" % (
            digest, entry["count"], ", ".join(str(i) for i in entry["runs"][:8])))
        for line in entry["lines"][:3]:
            print("    " + line)
    if len(summary["signatures"]) > 1:
        print("NOTE: more than one failure signature. These may be separate flakes; "
              "reproduce and explain each one.")
    if summary["mode"] == "measure":
        if failed:
            print("REPRODUCED. A fix needs %d consecutive passing runs to be verified at %d%% confidence:" % (
                summary["verify_runs_needed"], pct))
            print("    repro.py --mode verify --baseline-rate %s -- <same command>" % summary["failure_rate"])
        else:
            print("NOT REPRODUCED in %d runs. This does not show the test is healthy: a flake "
                  "below about %.1f%% would usually pass this many runs. Widen the search "
                  "(--jobs, --seed-env, more runs, the whole suite) before changing code." % (
                      total, (1 - (1 - confidence) ** (1.0 / total)) * 100 if total else 0))
    else:
        if summary["verified"]:
            print("VERIFIED: %d consecutive passes. A test still failing at the baseline rate of %s "
                  "would have failed at least once with %d%% probability." % (
                      total, summary["baseline_rate"], pct))
        elif failed:
            print("NOT FIXED: failed on run %d of %d." % (total, summary["planned_runs"]))
        else:
            print("INCOMPLETE: %d passes, %d needed." % (total, summary["verify_runs_needed"]))
    print("details: %s" % (out_dir / "summary.json"))


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("measure", "verify"), default="measure")
    parser.add_argument("--runs", type=int, help="number of runs (measure default: 30)")
    parser.add_argument("--baseline-rate", type=float,
                        help="verify mode: failure rate measured before the fix, e.g. 0.06")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="confidence used to size verify runs (default 0.95)")
    parser.add_argument("--max-runs", type=int, default=5000,
                        help="refuse to plan more runs than this (default 5000)")
    parser.add_argument("--jobs", type=int, default=1,
                        help="run this many copies at once to expose shared-resource flakes")
    parser.add_argument("--seed-env", action="append", default=[], metavar="NAME",
                        help="set this env var to a new random integer each run; repeatable")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="seconds before one run is killed and counted as a failure")
    parser.add_argument("--cwd", default=None, help="directory to run the command in")
    parser.add_argument("--out", default=".flaky-triage",
                        help="directory for summary.json and failure logs")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="the test command, after --")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("give the test command after --")
    if not 0 < args.confidence < 1:
        parser.error("--confidence must be between 0 and 1")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args, parser


def plan_runs(args, parser):
    """Return (planned_runs, runs needed by the baseline or None)."""
    if args.mode == "measure":
        runs = args.runs if args.runs is not None else 30
        if runs < 1:
            parser.error("--runs must be at least 1")
        return runs, None
    if args.baseline_rate is None:
        parser.error("verify mode needs --baseline-rate (the failure rate from a measure run)")
    if not 0 < args.baseline_rate <= 1:
        parser.error("--baseline-rate must be greater than 0 and at most 1")
    needed = runs_needed(args.baseline_rate, args.confidence)
    if args.runs is not None and args.runs < needed:
        parser.error(
            "--runs %d is too few: a baseline rate of %s needs %d passing runs for %d%% confidence"
            % (args.runs, args.baseline_rate, needed, int(round(args.confidence * 100))))
    runs = args.runs if args.runs is not None else needed
    if runs > args.max_runs:
        parser.error(
            "%d runs are needed, above --max-runs %d. Raise --max-runs, or first make the "
            "flake more frequent (stress with --jobs, or narrow the command) and re-measure."
            % (runs, args.max_runs))
    return runs, needed


def main(argv=None):
    args, parser = parse_args(argv if argv is not None else sys.argv[1:])
    planned, baseline_needed = plan_runs(args, parser)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("run-*.log"):
        stale.unlink()

    records = []
    saved_failures = 0
    saved_pass = False
    stop = False
    next_index = 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        while next_index <= planned and not stop:
            batch = range(next_index, min(next_index + args.jobs, planned + 1))
            futures = [
                pool.submit(run_once, i, args.command, args.timeout, args.seed_env, args.cwd)
                for i in batch
            ]
            for future in futures:
                try:
                    record, output = future.result()
                except OSError as exc:
                    print("cannot run command: %s" % exc, file=sys.stderr)
                    return 2
                records.append(record)
                if record["status"] != "pass":
                    if saved_failures < MAX_SAVED_FAILURE_LOGS:
                        (out_dir / ("run-%04d.log" % record["index"])).write_text(
                            output, encoding="utf-8")
                        saved_failures += 1
                    if args.mode == "verify":
                        stop = True
                elif not saved_pass:
                    (out_dir / "run-pass-sample.log").write_text(output, encoding="utf-8")
                    saved_pass = True
            next_index = batch[-1] + 1

    records.sort(key=lambda r: r["index"])
    summary = summarise(records, args, planned, baseline_needed)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print_summary(summary, out_dir, args.confidence)
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
