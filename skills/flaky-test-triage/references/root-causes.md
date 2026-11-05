# Root causes of flaky tests

How to confirm and fix each cause bucket that `scripts/classify.py` reports.
For every bucket: confirm by forcing the failure, then apply the listed fix.

## Contents

- [Async and timing](#async-and-timing)
- [Test order and shared state](#test-order-and-shared-state)
- [Clock, date and timezone](#clock-date-and-timezone)
- [Unseeded randomness and ordering](#unseeded-randomness-and-ordering)
- [Network and external services](#network-and-external-services)
- [Ports, files and other shared resources](#ports-files-and-other-shared-resources)
- [Races and deadlocks in the code under test](#races-and-deadlocks-in-the-code-under-test)
- [Patches that hide a flake](#patches-that-hide-a-flake)

## Async and timing

**What it looks like.** The test asserts before asynchronous work finishes.
Failing runs are often slower, or fail more under `--jobs` and on loaded CI
machines. Typical lines: "timed out waiting", "element not found", "expected
mock to have been called", "was not awaited".

**Confirm.** Inject a delay into the asynchronous path (a sleep in the worker,
a throttled CPU, a slowed network stub). If the failure rate jumps to 100%, the
test is racing that path.

**Fix.**
- Wait on the condition, not on time: await the promise or future, join the
  thread, poll for the observable state with a bounded deadline, or use the
  framework's auto-waiting assertion.
- Return or await every promise in the test body. A missing `await` lets the
  test finish before the assertion runs.
- Use fake timers when the code under test schedules work with timers, and
  advance them explicitly.
- A longer fixed sleep is not a fix. It lowers the rate and slows every run.

## Test order and shared state

**What it looks like.** The test passes alone and fails in the suite, or the
reverse. Failures depend on which tests ran before. Typical lines: duplicate
key, "already exists", unexpected leftover rows, a `None` or `undefined` where
an earlier test was expected to have set a value.

**Confirm.** Run the test alone. Then run it directly after each suspect
neighbour, and in reversed order. Bisect the preceding tests until one
predecessor (the polluter) makes it fail every time, or until removing one
predecessor (the state-setter) makes it fail every time.

**Fix.**
- Each test creates the state it needs and removes the state it creates. Move
  shared setup into per-test fixtures.
- Reset module-level caches, singletons, environment variables, and mocks in
  teardown.
- Roll back or truncate database state per test, or give each test its own
  schema or transaction.
- Fix the victim and the polluter. Fixing only the order hides the problem.

## Clock, date and timezone

**What it looks like.** Failures cluster at certain times: around midnight, at
month or year end, on daylight-saving changes, or only on CI machines set to
UTC. Typical lines: an expected date differing by one day or one hour.

**Confirm.** Run with a pinned clock at the suspect boundary, and with `TZ`
set to `UTC` and then to a far-offset zone such as `Pacific/Kiritimati`. A
deterministic failure at one setting confirms it.

**Fix.**
- Inject the clock. The code under test takes "now" as a parameter or from a
  replaceable provider, and the test supplies a fixed instant.
- Compare instants, not formatted local strings. State the zone explicitly
  wherever a zone is needed.
- Do not compute expected values with the real clock in the test.

## Unseeded randomness and ordering

**What it looks like.** A low, steady failure rate that does not depend on
load. Failures follow a seed. Typical causes: random test data that sometimes
hits an edge value, generated IDs that occasionally collide, assertions that
depend on hash-map, set, or directory-listing order.

**Confirm.** Take the seed from a failing run (`repro.py --seed-env NAME`
records it in `summary.json`) and replay it. The same seed failing every time
confirms it.

**Fix.**
- If the random input found a real bug, fix the product code and add the
  failing value as a fixed regression case.
- If the test needs stable data, seed the generator and log the seed on
  failure so any failure can be replayed.
- Never assert on the order of an unordered collection. Sort first, or compare
  as sets.

## Network and external services

**What it looks like.** Connection refused or reset, DNS errors, 429 and 5xx
responses, TLS errors. The rate tracks the health of something outside the
repository.

**Confirm.** List every host the test contacts. Block outbound network for the
test process; a test that now fails every time depends on that service.

**Fix.**
- Unit and integration tests should not call real third-party services.
  Replace them with a local fake, a recorded response, or a container the test
  starts and owns.
- For a service the test starts itself, wait for readiness with a health check
  before the first request.
- A retry around the real call hides outages and belongs in a separately
  labelled end-to-end suite, not here.

## Ports, files and other shared resources

**What it looks like.** Fails when tests run in parallel or when a previous
run left something behind. Typical lines: "address already in use", "file
exists", "database is locked", "too many open files".

**Confirm.** Measure with `repro.py --jobs 1` and again with `--jobs 4`.
Failures only under `--jobs` mean runs collide on a shared resource.

**Fix.**
- Bind to port 0 and read back the assigned port instead of using a fixed one.
- Use a unique temporary directory per test and remove it in teardown.
- Give each worker its own database or schema, keyed by worker ID.
- Close every handle, socket, and server the test opens.

## Races and deadlocks in the code under test

**What it looks like.** Data-race or concurrent-modification reports, hangs
that hit the timeout, results that differ between runs with identical inputs.
This is usually a product bug that the test happens to expose.

**Confirm.** Run under the language's race detector or thread sanitizer (for
example `go test -race`, `-fsanitize=thread`). For a hang, capture a stack
dump of all threads when the timeout fires.

**Fix.**
- Fix the synchronisation in the product code: guard the shared state, or stop
  sharing it.
- Acquire locks in one consistent order to remove a deadlock.
- Keep the test. Tell the user the flake was a real concurrency defect.

## Patches that hide a flake

Each of these lowers the failure rate without removing the cause. Use one only
when the stated condition holds, and say why in the report.

| Patch | Why it hides the problem | When it is legitimate |
|---|---|---|
| Raise a timeout | The race is still there on a slower machine | The operation has a real, known upper bound that the old value was under |
| Add a sleep | Same race, slower suite | Almost never; wait on the condition |
| Add retries | A real intermittent bug now passes | A labelled end-to-end suite against services the team does not control |
| Loosen an assertion | The test stops checking the behaviour | The original assertion was stricter than the specification |
| Skip or quarantine | Coverage is lost | Temporary, with an owner, a ticket, and the lost coverage stated |
| Force serial execution | Hides shared-resource bugs, slows CI | The resource truly cannot be isolated, and that is documented |
