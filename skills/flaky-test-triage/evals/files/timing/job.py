"""Background job that doubles a number."""
import random
import threading
import time


class Job:
    def __init__(self):
        self.result = None
        self._thread = None

    def start(self, value):
        def work():
            time.sleep(random.uniform(0.0, 0.02))  # stands in for real I/O latency
            self.result = value * 2

        self._thread = threading.Thread(target=work)
        self._thread.start()

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return self.result
