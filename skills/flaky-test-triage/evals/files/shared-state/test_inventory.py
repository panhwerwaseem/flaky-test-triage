import unittest

import inventory


class InventoryTests(unittest.TestCase):
    def test_load_prices_returns_count(self):
        self.assertEqual(inventory.load_prices(), 3)

    def test_price_of_widget(self):
        self.assertEqual(inventory.price_of("widget"), 250)

    def test_total_of_basket(self):
        self.assertEqual(inventory.total(["widget", "gadget"]), 1240)


if __name__ == "__main__":
    unittest.main()
