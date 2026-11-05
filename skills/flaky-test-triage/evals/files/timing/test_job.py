import time
import unittest

from job import Job


class JobTests(unittest.TestCase):
    def test_job_doubles_value(self):
        job = Job()
        job.start(21)
        time.sleep(0.015)
        self.assertEqual(job.result, 42)


if __name__ == "__main__":
    unittest.main()
