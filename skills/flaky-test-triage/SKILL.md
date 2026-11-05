---
name: flaky-test-triage
description: Reproduces an intermittently failing (flaky) test, measures its failure rate, classifies the root cause, and proves the fix with a computed number of repeated passing runs. Use when a test passes and fails without code changes, when CI goes red at random and passes on re-run, when a test is quarantined, skipped or wrapped in retries, or when the user says flaky, intermittent, nondeterministic, or works on my machine.
license: MIT
compatibility: Requires Python 3.9 or later to run the bundled scripts. No network access and no extra packages needed.
metadata:
  author: panhwerwaseem
  version: "0.1.0"
---

# Flaky test triage

A flaky test is fixed only when two things are true: the failure was reproduced
and its cause explained, and the test then passed enough consecutive runs that
an unfixed test would almost certainly have failed. Everything below serves
those two conditions.

Paths in this file are relative to this skill's directory.

## Hard rules

1. **Reproduce before editing.** Do not change test or product code until
   `scripts/repro.py` has recorded at least one failure, or you have told the
   user it could not be reproduced and what you tried.
2. **No symptom patches.** Do not raise a timeout, add a sleep, add a retry,
   loosen an assertion, or mark the test as expected-to-fail as the fix. These
   are allowed only when the root cause is a real, named latency bound, and then
   you must state the cause and why the new value is correct.
3. **No silent coverage loss.** Do not delete, skip, or quarantine a test
   without stating exactly what behaviour stops being tested and getting the
   user's agreement.
4. **Verified means computed.** Claim a fix only after `repro.py --mode verify`
   prints `VERIFIED`. The script computes the run count from the measured
   failure rate; do not substitute a smaller number such as "passed 3 times".
5. **One flake per signature.** If `repro.py` reports more than one failure
   signature, treat each as a separate problem with its own reproduction.
6. **Say so when stuck.** If the flake does not reproduce within the agreed
   budget, report that plainly with what was tried. Do not make a speculative
   edit and call it a fix.

## Workflow

### 1. Pin down the narrowest failing command

Get the exact test ID and the command that runs only that test. If the failure
was seen in CI, copy the CI command, environment variables, and runner settings
(parallelism, shuffling, shards). `references/runner-recipes.md` has the
single-test, repeat, shuffle, and isolation flags for common test runners.

### 2. Measure

```bash
python3 scripts/repro.py --runs 50 -- <test command>
```

The script runs the command without a shell, writes `summary.json` and the
failing logs to `.flaky-triage/`, and prints the failure rate, the distinct
failure signatures, and the number of passing runs a fix will need.

### 3. If it did not reproduce, widen the search before touching code

Try these in order, re-measuring after each. Stop at the first that fails.

| Step | Command change | What it exposes |
|---|---|---|
| Run copies at once | add `--jobs 4` | Shared ports, files, databases |
| Vary seeds | add `--seed-env PYTHONHASHSEED` (or the runner's seed variable) | Hash, map and random ordering |
| Run the file, then the suite | widen the test command | Order dependence, leaked state |
| Shuffle order | runner's shuffle flag | Order dependence |
| Match CI | CI's env vars, `TZ`, locale, CPU limit | Environment differences |
| More runs | `--runs 300` | Low-rate flakes |

A run of 50 passes does not show the test is healthy: a flake under about 6%
usually survives 50 runs. The script prints this bound for whatever run count
you used.

### 4. Classify

```bash
python3 scripts/classify.py
```

This prints ranked cause buckets with the log lines that triggered each and the
next check to run. Treat the output as hints. Then read the failing log and
compare it with `.flaky-triage/run-pass-sample.log`.
`references/root-causes.md` gives the diagnosis steps and the correct fix for
each bucket.

### 5. Confirm the cause by making the failure deterministic

Before fixing, force the failure to happen every time: replay the failing seed,
run the two tests in the failing order, pin the clock, inject the delay, or
occupy the port. If you cannot make it fail on demand, you have not found the
cause yet. Return to step 3 or 4.

### 6. Fix the cause

Apply the fix that `references/root-causes.md` gives for the confirmed bucket.
Fix product code when the product has the race; fix the test when the test has
it. Keep the change as small as the cause allows.

### 7. Verify

```bash
python3 scripts/repro.py --mode verify --baseline-rate <rate from step 2> -- <same command, same flags>
```

Use the same command, `--jobs`, and `--seed-env` flags that reproduced the
failure. The script stops at the first failure and prints `VERIFIED` only after
the computed number of consecutive passes. If the needed run count is
impractical, first make the flake more frequent (step 3 stress options),
re-measure, and verify against that higher rate.

### 8. Report

Give the user this, filled in from the script output:

```
Test:            <test ID>
Reproduced:      <failures>/<runs> runs (<rate>%), command: <command>
Root cause:      <one or two sentences, naming the bucket>
Made deterministic by: <how the failure was forced>
Fix:             <what changed and where>
Verified:        <N> consecutive passes at 95% confidence against the measured rate
Not done:        <anything skipped, other signatures left open, coverage changes>
```

## Edge cases

- **Only fails in CI.** Reproduce the CI conditions locally (container image,
  CPU limit, env vars) or run `repro.py` inside a CI job. Do not fix blind.
- **Failure rate near 100% in CI and 0% locally.** This is an environment
  difference, not a flake. Diff the environments first.
- **Very slow test.** Lower `--runs`, raise `--jobs` if the test tolerates it,
  and tell the user the confidence the smaller run count gives.
- **The test is right and the product is racy.** Say so. A flaky test that
  exposes a real race is a product bug; do not weaken the test to hide it.
- **`.flaky-triage/`** is scratch output. Do not commit it.
