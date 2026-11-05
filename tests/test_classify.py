import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "flaky-test-triage" / "scripts"))

import classify  # noqa: E402


def write_run(directory, logs, summary=None):
    base = {"failures": len(logs), "jobs": 1, "signatures": {"a": {}}, "runs": [],
            "mean_pass_duration_s": 1.0, "mean_fail_duration_s": 1.0}
    base.update(summary or {})
    (directory / "summary.json").write_text(json.dumps(base))
    for index, text in enumerate(logs, 1):
        (directory / ("run-%04d.log" % index)).write_text(text)


def classify_json(directory):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = classify.main(["--dir", str(directory), "--json"])
    return code, json.loads(buffer.getvalue())


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def top_bucket(self, log):
        write_run(self.dir, [log])
        _, result = classify_json(self.dir)
        return result["hypotheses"][0]["bucket"]

    def test_port_in_use_points_to_resource_collision(self):
        self.assertEqual(
            self.top_bucket("OSError: [Errno 48] Address already in use\n"), "resource-collision")

    def test_connection_refused_points_to_network(self):
        self.assertEqual(
            self.top_bucket("Error: connect ECONNREFUSED 10.0.0.5:443\n503 Service Unavailable\n"),
            "network-external")

    def test_data_race_points_to_concurrency(self):
        self.assertEqual(
            self.top_bucket("WARNING: DATA RACE\nWrite at 0x00c by goroutine 7\n"), "concurrency")

    def test_wait_timeout_points_to_async_timing(self):
        self.assertEqual(
            self.top_bucket("TimeoutError: Timed out waiting for selector '#save'\n"),
            "async-timing")

    def test_unique_constraint_points_to_shared_state(self):
        self.assertEqual(
            self.top_bucket("IntegrityError: duplicate key value violates unique constraint\n"),
            "order-shared-state")

    def test_evidence_lines_are_reported(self):
        write_run(self.dir, ["OSError: Address already in use\n"])
        _, result = classify_json(self.dir)
        self.assertIn("Address already in use", result["hypotheses"][0]["evidence"][0])

    def test_unknown_failure_gives_no_hypothesis(self):
        write_run(self.dir, ["something odd happened\n"])
        _, result = classify_json(self.dir)
        self.assertEqual(result["hypotheses"], [])

    def test_slow_failures_and_timeouts_raise_signals(self):
        write_run(self.dir, ["x\n"], {
            "mean_pass_duration_s": 1.0, "mean_fail_duration_s": 4.0,
            "runs": [{"status": "timeout", "seeds": {"SEED": 7}}],
            "signatures": {"a": {}, "b": {}},
        })
        _, result = classify_json(self.dir)
        text = " ".join(result["signals"])
        self.assertIn("timeout", text)
        self.assertIn("slower", text)
        self.assertIn("2 distinct failure signatures", text)
        self.assertIn('"SEED": 7', text)

    def test_missing_summary_is_an_error(self):
        self.assertEqual(classify.main(["--dir", str(self.dir / "nope")]), 2)


class ValidateRepoTests(unittest.TestCase):
    def test_repository_passes_its_own_validator(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import validate
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = validate.main(["validate.py", str(ROOT)])
        self.assertEqual(code, 0, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
