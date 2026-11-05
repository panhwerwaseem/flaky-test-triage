"""Discount code generation and normalisation."""
import random

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8


def new_code(rng=random):
    return "".join(rng.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalise(code):
    """Clean up a code typed by a customer."""
    return code.strip().upper().lstrip("0")


def is_valid(code):
    code = normalise(code)
    return len(code) == CODE_LENGTH and all(ch in ALPHABET for ch in code)
