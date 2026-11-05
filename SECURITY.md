# Security

An agent skill is instructions and code that your coding agent will follow and run. Review a skill before installing it, the same way you would review any dependency.

## What this skill does on your machine

| | |
|---|---|
| Reads | Output of the test command you supply; its own output directory |
| Writes | `summary.json` and failure logs inside `.flaky-triage/` or the `--out` directory |
| Executes | The test command you pass after `--`, directly, without a shell. It runs repeatedly, and concurrently when `--jobs` is above 1 |
| Network | None. The bundled scripts import no network modules. `tools/validate.py` checks this in CI |
| Dependencies | Python standard library only |
| Pre-approved tools | None. `SKILL.md` has no `allowed-tools` entry, so your agent's normal permission prompts apply |
| Hooks, MCP servers, background processes | None |

The skill instructs the agent to edit test or product code only after reproducing a failure. Those edits go through your agent's normal review and permission flow.

Because `repro.py` runs your test command many times, a test with side effects (sending email, charging a card, writing to a shared database) will repeat those side effects. Point it at tests that are safe to repeat.

## Reporting a vulnerability

Please report security problems privately through the repository's **Security** tab ("Report a vulnerability"). If that option is not available, open an issue that says a private channel is needed, without including exploit details.

## Verifying what you install

- Install from a tagged release and read the diff between tags before updating.
- The whole skill is the `skills/flaky-test-triage/` folder: one Markdown protocol, two Python scripts, two reference files, and eval fixtures.
