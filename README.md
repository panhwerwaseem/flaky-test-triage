# flaky-test-triage

**An agent skill that reproduces a flaky test, finds the cause, and proves the fix with a computed number of passing runs.**

Left alone, a coding agent asked to fix a flaky test tends to add an `await`, raise a timeout, run the test once or twice, and report success. This skill replaces that with a protocol and two scripts: no edit before the failure is reproduced, no timeout bump as a fix, and no "fixed" claim until the test has passed as many consecutive runs as its measured failure rate requires.

Works with Claude Code, and with any agent that reads the open [Agent Skills](https://agentskills.io) format (Codex, Cursor, GitHub Copilot, Gemini CLI and others).

## What it looks like

Measuring a test that fails about one run in four:

```console
$ python3 scripts/repro.py --runs 40 -- python3 -m unittest test_job
mode: measure   runs: 40/40   failures: 10   failure rate: 25.0%
mean duration: pass 0.069s, fail 0.071s
signature 39d0932232  x10  (runs 3, 6, 9, 10, 16, 17, 26, 38)
    AssertionError: None != <n>
REPRODUCED. A fix needs 11 consecutive passing runs to be verified at 95% confidence:
    repro.py --mode verify --baseline-rate 0.25 -- <same command>
```

Verifying a fix:

```console
$ python3 scripts/repro.py --mode verify --baseline-rate 0.25 -- python3 -m unittest test_job
mode: verify   runs: 11/11   failures: 0   failure rate: 0.0%
VERIFIED: 11 consecutive passes. A test still failing at the baseline rate of 0.25 would have failed at least once with 95% probability.
```

Asking for too few runs is refused:

```console
$ python3 scripts/repro.py --mode verify --baseline-rate 0.03 --runs 10 -- pytest tests/test_codes.py
repro.py: error: --runs 10 is too few: a baseline rate of 0.03 needs 99 passing runs for 95% confidence
```

## Install

Pick one route. Installing through more than one gives you the skill twice.

**Claude Code (plugin)**

```
/plugin install flaky-test-triage --marketplace panhwerwaseem/flaky-test-triage
```

On Claude Code versions before 2.1.275, use two steps:

```
/plugin marketplace add panhwerwaseem/flaky-test-triage
/plugin install flaky-test-triage@panhwerwaseem-flaky-test-triage
```

**Any agent (skills CLI)**

```bash
npx skills add panhwerwaseem/flaky-test-triage
```

**Manual**

Copy the `skills/flaky-test-triage` folder into `.claude/skills/` (Claude Code) or `.agents/skills/` (cross-agent) in your project, or into the same folder under your home directory.

To pin a release, add the tag: `/plugin marketplace add panhwerwaseem/flaky-test-triage#v0.1.0` or `npx skills add panhwerwaseem/flaky-test-triage@v0.1.0`. Third-party plugins do not update automatically; run `claude plugin update flaky-test-triage@panhwerwaseem-flaky-test-triage` to update.

## Use

Describe the problem and the skill loads on its own:

> test_checkout_total fails about one run in ten on CI and passes when I re-run the job. Fix it.

In Claude Code you can also call it directly with `/flaky-test-triage`.

## What is in the skill

| File | Purpose |
|---|---|
| `SKILL.md` | The protocol: six hard rules and an eight-step workflow from reproduction to verified fix |
| `scripts/repro.py` | Runs a test command N times, in parallel if asked, with fresh random seeds if asked. Reports failure rate and failure signatures. In verify mode it computes the run count from the measured rate and stops at the first failure |
| `scripts/classify.py` | Reads the failure logs and suggests cause buckets (timing, test order, clock, randomness, network, shared resources, races) with the evidence lines |
| `references/root-causes.md` | How to confirm and correctly fix each cause, and which patches only hide a flake |
| `references/runner-recipes.md` | Single-test, shuffle, and isolation flags for pytest, Jest, Vitest, Playwright, Go, JUnit, RSpec, Cargo and .NET |
| `evals/` | Three seeded flaky projects (order dependence, a 3% random failure, a thread race) with eval cases, plus trigger queries |

### How the run count is computed

If a test fails with probability *p* per run, the chance that an unfixed test passes *n* runs in a row is (1 − *p*)ⁿ. Verify mode picks the smallest *n* where that chance is at most 5%:

*n* ≥ ln(0.05) / ln(1 − *p*)

So a 25% flake needs 11 passes, a 5% flake needs 59, and a 1% flake needs 299. Three green runs prove very little.

## Requirements

- Python 3.9 or later
- No packages to install and no network access

## What it reads, writes and contacts

- **Reads:** the output of the test command you give it, and its own `.flaky-triage/` directory.
- **Writes:** `summary.json` and failure logs inside `.flaky-triage/` (or the directory passed to `--out`). Nothing else.
- **Runs:** only the test command you pass after `--`, directly, without a shell.
- **Contacts:** nothing. The scripts contain no network code; CI enforces this.
- **Permissions:** the skill pre-approves no tools. Your agent asks before running commands, as usual.

See [SECURITY.md](SECURITY.md).

## Testing status

- The scripts have unit tests that run in CI on Python 3.9 and 3.12, together with a validator for the skill format and plugin manifests.
- The eval cases in `skills/flaky-test-triage/evals/` are in the [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) format. A with-skill versus without-skill score has not been published yet; results are welcome as an issue or pull request.

## Development

```bash
python3 tools/validate.py              # skill format, manifests, no-network check
python3 -m unittest discover -s tests  # script unit tests
```

## License

[MIT](LICENSE)
