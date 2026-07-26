from __future__ import annotations

import unittest

from scripts.eurostat_api import build_url, coords_from_index, flatten


class EurostatApiTests(unittest.TestCase):
    def test_coordinates_follow_json_stat_row_major_order(self) -> None:
        self.assertEqual(coords_from_index(0, [2, 3]), [0, 0])
        self.assertEqual(coords_from_index(4, [2, 3]), [1, 1])
        self.assertEqual(coords_from_index(5, [2, 3]), [1, 2])

    def test_flattens_sparse_observations_and_status(self) -> None:
        data = {
            "id": ["geo", "time"],
            "size": [2, 2],
            "dimension": {
                "geo": {
                    "category": {
                        "index": {"DE": 0, "FR": 1},
                        "label": {"DE": "Germany", "FR": "France"},
                    }
                },
                "time": {
                    "category": {
                        "index": {"2024": 0, "2025": 1},
                        "label": {"2024": "2024", "2025": "2025"},
                    }
                },
            },
            "value": {"0": 10, "3": 20},
            "status": {"3": "p"},
        }

        rows = flatten(data)

        self.assertEqual(rows[0]["geo_label"], "Germany")
        self.assertEqual(rows[1]["geo_label"], "France")
        self.assertEqual(rows[1]["time"], "2025")
        self.assertEqual(rows[1]["status"], "p")

    def test_build_url_repeats_dimension_filters(self) -> None:
        url = build_url("demo_pjan", [("geo", "DE"), ("geo", "FR")])

        self.assertIn("geo=DE", url)
        self.assertIn("geo=FR", url)


if __name__ == "__main__":
    unittest.main()
