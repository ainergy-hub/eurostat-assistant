from __future__ import annotations

import unittest

from scripts.eurostat_api import (
    build_url,
    coords_from_index,
    flatten,
    match_dimension_categories,
    rank_catalog,
)


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

    def test_search_ignores_per_substrings_and_prioritizes_patents(self) -> None:
        rows = [
            {
                "code": "cens_01ndpercons",
                "title": "Owner-occupied dwellings by type and year of construction",
                "type": "dataset",
            },
            {
                "code": "crim_crt_per",
                "title": "Persons brought before criminal courts",
                "type": "dataset",
            },
            {
                "code": "pat_ep_tot",
                "title": "Patent applications to the EPO by country of applicants and inventors",
                "type": "dataset",
                "data_end": "2025",
            },
            {
                "code": "met_pat_epipc",
                "title": (
                    "Patent applications to the EPO by international patent classification and "
                    "metropolitan region"
                ),
                "type": "dataset",
                "data_end": "2012",
            },
        ]

        results = rank_catalog(rows, "patent applications per capita", 5)

        self.assertEqual(results[0]["code"], "pat_ep_tot")
        self.assertTrue(all("patent" in row["title"].casefold() for row in results))

    def test_search_prioritizes_an_exact_dataset_code(self) -> None:
        rows = [
            {
                "code": "nama_10_gdp",
                "title": "Gross domestic product and main components",
                "type": "dataset",
            },
            {
                "code": "nama_10_pc",
                "title": "Gross domestic product per capita",
                "type": "dataset",
            },
        ]

        results = rank_catalog(rows, "nama_10_pc", 5)

        self.assertEqual(results[0]["code"], "nama_10_pc")

    def test_complete_category_matching_handles_accents_and_misspellings(self) -> None:
        data = {
            "id": ["geo"],
            "dimension": {
                "geo": {
                    "category": {
                        "index": {"DE1": 0, "ES41": 1},
                        "label": {
                            "DE1": "Baden-Württemberg",
                            "ES41": "Castilla y León",
                        },
                    }
                }
            },
        }

        matches = match_dimension_categories(
            data,
            ["Baden-Wurttemberg", "Castille and Léon"],
        )

        self.assertEqual(matches[0]["categories"][0]["code"], "DE1")
        self.assertEqual(matches[1]["categories"][0]["code"], "ES41")

    def test_complete_category_matching_exposes_solar_variants(self) -> None:
        data = {
            "id": ["siec"],
            "dimension": {
                "siec": {
                    "category": {
                        "index": {"RA410": 0, "RA420": 1, "RA500": 2},
                        "label": {
                            "RA410": "Solar thermal",
                            "RA420": "Solar photovoltaic",
                            "RA500": "Tide, wave, ocean",
                        },
                    }
                }
            },
        }

        matches = match_dimension_categories(data, ["solar generation"])
        codes = [item["code"] for item in matches[0]["categories"]]

        self.assertEqual(set(codes[:2]), {"RA420", "RA410"})


if __name__ == "__main__":
    unittest.main()
