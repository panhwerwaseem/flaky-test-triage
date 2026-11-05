# Test runner recipes

Flags for running one test, shuffling order, and isolating state in common
test runners. Put the single-test command after `--` when calling
`scripts/repro.py`. Prefer `repro.py` for repetition over a runner's own repeat
flag, because it records the failure rate, signatures, and logs.

Flags change between versions. If one is rejected, check the runner's `--help`.

## pytest (Python)

| Need | Command |
|---|---|
| One test | `pytest path/test_file.py::TestClass::test_name` |
| Stop at first failure | add `-x` |
| Shuffle order | With the pytest-randomly plugin installed, order is shuffled on every run. With pytest-random-order, add `--random-order` |
| Replay a seed | pytest-randomly: `--randomly-seed=N` (the seed is printed in the run header). pytest-random-order: `--random-order-seed=N` |
| Turn shuffling off | pytest-randomly: `-p no:randomly` |
| Run in parallel | `pytest -n 4` (pytest-xdist) |
| Hash order | set `PYTHONHASHSEED`; use `repro.py --seed-env PYTHONHASHSEED` |
| Find a polluter | run `pytest A B` for each earlier test A and the victim B, halving the list each time |

## unittest (Python)

| Need | Command |
|---|---|
| One test | `python3 -m unittest package.module.TestClass.test_name` |
| Hash order | `repro.py --seed-env PYTHONHASHSEED` |

## Jest (JavaScript and TypeScript)

| Need | Command |
|---|---|
| One test | `npx jest path/file.test.ts -t "test name"` |
| Serial, one process | add `--runInBand` |
| Shuffle tests in a file | add `--randomize` (prints the seed), replay with `--seed=N` |
| Open handles | add `--detectOpenHandles` |

## Vitest

| Need | Command |
|---|---|
| One test | `npx vitest run path/file.test.ts -t "test name"` |
| Shuffle | add `--sequence.shuffle`, replay with `--sequence.seed=N` |
| Separate process per test file | add `--pool=forks` |

## Playwright Test

| Need | Command |
|---|---|
| One test | `npx playwright test path/file.spec.ts -g "test name"` |
| One worker | add `--workers=1` |
| No retries (see the real rate) | add `--retries=0` |
| Trace on failure | add `--trace=retain-on-failure` |

Set `--retries=0` while measuring. Retries hide the failure rate.

## Go

| Need | Command |
|---|---|
| One test | `go test ./pkg/... -run '^TestName$' -count=1` |
| Race detector | add `-race` |
| Shuffle | add `-shuffle=on` (prints the seed), replay with `-shuffle=N` |
| Disable caching | `-count=1` (always use when repeating) |

## JUnit with Maven or Gradle

| Need | Command |
|---|---|
| One test (Maven) | `mvn -q test -Dtest='ClassName#methodName'` |
| One test (Gradle) | `./gradlew test --tests 'pkg.ClassName.methodName' --rerun-tasks` |
| Random method order (JUnit 5) | set `junit.jupiter.testmethod.order.default=org.junit.jupiter.api.MethodOrderer$Random` |
| Disable Surefire reruns | `-Dsurefire.rerunFailingTestsCount=0` |

## RSpec (Ruby)

| Need | Command |
|---|---|
| One test | `bundle exec rspec path/file_spec.rb:LINE` |
| Shuffle | add `--order random`, replay with `--seed N` |
| Find a polluter | `bundle exec rspec --bisect --seed N` |

## Cargo (Rust)

| Need | Command |
|---|---|
| One test | `cargo test test_name -- --exact` |
| Single thread | `cargo test -- --test-threads=1` |

## .NET

| Need | Command |
|---|---|
| One test | `dotnet test --filter "FullyQualifiedName~Namespace.Class.Method"` |

## Matching CI

Copy these from the CI job before measuring locally:

- Environment variables, especially `CI`, `TZ`, `LANG`, `LC_ALL`, and `NODE_ENV`
- Worker or shard count and any shuffle seed the job printed
- Container image and CPU and memory limits
- Services the job starts (database, cache, browser) and their versions
- Whether the job reuses a cache or workspace from a previous run
