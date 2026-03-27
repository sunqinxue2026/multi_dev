import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from snack_app.catalog import checkout_summary, discovery_sections, filter_snacks


class SnackAppSmokeTests(unittest.TestCase):
    def test_filter_snacks_returns_only_healthy_items_when_enabled(self) -> None:
        items = filter_snacks(healthy_only=True)
        self.assertTrue(items)
        self.assertTrue(all(item['healthy_label'] in {'低负担', '高蛋白', '真果肉', '非油炸', '0糖', '轻负担', '低脂'} for item in items))

    def test_checkout_summary_applies_combo_and_shipping_rules(self) -> None:
        summary = checkout_summary(
            [
                {'id': 'seaweed_chips', 'qty': 1},
                {'id': 'iced_oolong', 'qty': 1},
                {'id': 'mixed_nuts', 'qty': 2},
            ],
            coupon_code='SNACK10',
        )
        self.assertGreater(summary['subtotal'], 0)
        self.assertGreaterEqual(summary['bundle_discount'], 3.0)
        self.assertIn('reward_points', summary)

    def test_discovery_sections_include_best_sellers(self) -> None:
        sections = discovery_sections()
        self.assertIn('best_sellers', sections)
        self.assertTrue(sections['best_sellers'])


if __name__ == '__main__':
    unittest.main()
