import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "flaky-test-triage" / "scripts"))

import repro  # noqa: E402

# Fails on every third invocation, tracked through a counter file.
EVERY_THIRD = """
import sys
path = sys.argv[1]
try:
    count = int(open(path).read())
except (IOError, ValueError):
    count = 0
count += 1
open(path, "w").write(str(count))
if count % 3 == 0:
    print("AssertionError: expected 42 but got %d after 0.0%ds" % (count, count))
    sys.exit(1)
print("ok")
"""


class RunsNeededTests(unittest.TestCase):
    def test_half_rate_needs_five_runs(self):
        self.assertEqual(repro.runs_needed(0.5, 0.95), 5)

    def test_one_in_thirty_two_needs_ninety_five_runs(self):
        self.assertEqual(repro.runs_needed(1 / 32.0, 0.95), 95)

    def test_zero_rate_has_no_answer(self):
        self.assertIsNone(repro.runs_needed(0, 0.95))

    def test_certain_failure_needs_one_run(self):
        self.assertEqual(repro.runs_needed(1.0, 0.95), 1)


class SignatureTests(unittest.TestCase):
    def test_same_failure_with_different_numbers_has_same_signature(self):
        first, _ = repro.signature_of("AssertionError: expected 42 but got 17 after 12ms\n", "fail")
        second, _ = repro.signature_of("AssertionError: expected 42 but got 993 after 250ms\n", "fail")
        self.assertEqual(first, second)

    def test_different_failures_have_different_signatures(self):
        first, _ = repro.signature_of("AssertionError: expected 42\n", "fail")
        second, _ = repro.signature_of("ConnectionRefusedError: port 5432\n", "fail")
        self.assertNotEqual(first, second)

    def test_same_error_reported_by_tests_in_a_different_order_has_same_signature(self):
        first, lines = repro.signature_of(
            "ERROR: test_a (m.T)\nKeyError: 'widget'\nERROR: test_b (m.T)\nKeyError: 'widget'\n", "fail")
        second, _ = repro.signature_of(
            "ERROR: test_b (m.T)\nKeyError: 'widget'\n", "fail")
        self.assertEqual(first, second)
        self.assertEqual(lines, ["KeyError: 'widget'"])

    def test_timeout_has_fixed_signature(self):
        self.assertEqual(repro.signature_of("anything", "timeout")[0], "timeout")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"
        self.helper = self.dir / "every_third.py"
        self.helper.write_text(EVERY_THIRD)
        self.counter = self.dir / "counter"
        devnull = open(os.devnull, "w")
        self.addCleanup(devnull.close)
        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = devnull
        self.addCleanup(self._restore)

    def _restore(self):
        sys.stdout, sys.stderr = self._stdout, self._stderr

    def summary(self):
        return json.loads((self.out / "summary.json").read_text())

    def flaky_command(self):
        return ["--", sys.executable, str(self.helper), str(self.counter)]

    def test_measure_counts_failures_and_groups_them_under_one_signature(self):
        code = repro.main(["--runs", "9", "--out", str(self.out)] + self.flaky_command())
        summary = self.summary()
        self.assertEqual(code, 1)
        self.assertEqual(summary["failures"], 3)
        self.assertEqual(summary["completed_runs"], 9)
        self.assertEqual(len(summary["signatures"]), 1)
        self.assertEqual(summary["verify_runs_needed"], repro.runs_needed(3 / 9.0, 0.95))
        self.assertEqual(len(list(self.out.glob("run-0*.log"))), 3)
        self.assertTrue((self.out / "run-pass-sample.log").is_file())

    def test_measure_returns_zero_when_every_run_passes(self):
        code = repro.main(["--runs", "4", "--out", str(self.out), "--",
                           sys.executable, "-c", "print('ok')"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary()["failures"], 0)
        self.assertIsNone(self.summary()["verify_runs_needed"])

    def test_verify_refuses_too_few_runs(self):
        with self.assertRaises(SystemExit) as caught:
            repro.main(["--mode", "verify", "--baseline-rate", "0.1", "--runs", "5",
                        "--out", str(self.out), "--", sys.executable, "-c", "pass"])
        self.assertEqual(caught.exception.code, 2)

    def test_verify_requires_baseline_rate(self):
        with self.assertRaises(SystemExit) as caught:
            repro.main(["--mode", "verify", "--out", str(self.out), "--",
                        sys.executable, "-c", "pass"])
        self.assertEqual(caught.exception.code, 2)

    def test_verify_passes_after_computed_number_of_runs(self):
        code = repro.main(["--mode", "verify", "--baseline-rate", "0.5",
                           "--out", str(self.out), "--", sys.executable, "-c", "pass"])
        summary = self.summary()
        self.assertEqual(code, 0)
        self.assertTrue(summary["verified"])
        self.assertEqual(summary["completed_runs"], 5)

    def test_verify_stops_at_first_failure(self):
        code = repro.main(["--mode", "verify", "--baseline-rate", "0.2",
                           "--out", str(self.out)] + self.flaky_command())
        summary = self.summary()
        self.assertEqual(code, 1)
        self.assertFalse(summary["verified"])
        self.assertEqual(summary["completed_runs"], 3)

    def test_seed_env_is_set_and_recorded(self):
        code = repro.main(["--runs", "2", "--seed-env", "MY_SEED", "--out", str(self.out), "--",
                           sys.executable, "-c",
                           "import os,sys; sys.exit(0 if os.environ['MY_SEED'].isdigit() else 1)"])
        self.assertEqual(code, 0)
        for run in self.summary()["runs"]:
            self.assertIn("MY_SEED", run["seeds"])

    def test_timeout_counts_as_failure(self):
        code = repro.main(["--runs", "1", "--timeout", "0.5", "--out", str(self.out), "--",
                           sys.executable, "-c", "import time; time.sleep(5)"])
        self.assertEqual(code, 1)
        self.assertEqual(self.summary()["runs"][0]["status"], "timeout")

    def test_parallel_jobs_complete_all_runs(self):
        code = repro.main(["--runs", "6", "--jobs", "3", "--out", str(self.out), "--",
                           sys.executable, "-c", "pass"])
        self.assertEqual(code, 0)
        self.assertEqual(self.summary()["completed_runs"], 6)

    def test_missing_command_is_a_usage_error(self):
        code = repro.main(["--runs", "1", "--out", str(self.out), "--", "no-such-binary-xyz"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
