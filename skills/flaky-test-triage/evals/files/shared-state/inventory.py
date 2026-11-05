"""Tiny price lookup with a module-level cache."""

_PRICES = {}


def load_prices():
    _PRICES.update({"widget": 250, "gadget": 990, "gizmo": 1200})
    return len(_PRICES)


def price_of(item):
    return _PRICES[item]


def total(items):
    return sum(price_of(item) for item in items)
