"""Run the suite in shuffled order, the way the CI job does.

The order comes from the TEST_SEED environment variable. With no TEST_SEED a
random seed is chosen and printed so a failing order can be replayed.
"""
import os
import random
import sys
import unittest


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for test in flatten(item):
                yield test
        else:
            yield item


def main():
    seed = int(os.environ.get("TEST_SEED") or random.randrange(1, 10 ** 6))
    print("TEST_SEED=%d" % seed)
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    tests = sorted(flatten(unittest.defaultTestLoader.discover(here)), key=lambda t: t.id())
    random.Random(seed).shuffle(tests)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
