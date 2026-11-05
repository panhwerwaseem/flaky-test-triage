import unittest

import codes


class CodeTests(unittest.TestCase):
    def test_generated_code_is_valid(self):
        self.assertTrue(codes.is_valid(codes.new_code()))

    def test_lowercase_input_is_accepted(self):
        self.assertTrue(codes.is_valid("ab12cd34"))


if __name__ == "__main__":
    unittest.main()
