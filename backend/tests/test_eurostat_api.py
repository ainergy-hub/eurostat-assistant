from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

from skill.scripts.eurostat_api import (
    MAX_ESTIMATED_CELLS,
    MAX_RESPONSE_BYTES,
    build_sdmx_constraint_url,
    build_sdmx_dataflow_url,
    build_url,
    coords_from_index,
    dimensions,
    estimated_cell_count,
    fetch,
    flatten,
    get_text,
    match_dimension_categories,
    parse_sdmx_dimensions,
    rank_catalog,
)


SDMX_DATAFLOW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure
    xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
    xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
    xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <mes:Structures>
    <str:Dataflows>
      <str:Dataflow id="NAIO_10_FCP_II4" agencyID="ESTAT" version="1.0">
        <com:Name xml:lang="en">Inter-country input-output table</com:Name>
      </str:Dataflow>
    </str:Dataflows>
    <str:DataStructures>
      <str:DataStructure id="NAIO_10_FCP_II4" agencyID="ESTAT" version="1.0">
        <str:DataStructureComponents>
          <str:DimensionList>
            <str:Dimension id="freq" position="1">
              <str:ConceptIdentity><Ref id="FREQ" /></str:ConceptIdentity>
              <str:LocalRepresentation><str:Enumeration><Ref id="FREQ" /></str:Enumeration></str:LocalRepresentation>
            </str:Dimension>
            <str:Dimension id="geo" position="2">
              <str:ConceptIdentity><Ref id="GEO" /></str:ConceptIdentity>
              <str:LocalRepresentation><str:Enumeration><Ref id="GEO" /></str:Enumeration></str:LocalRepresentation>
            </str:Dimension>
            <str:TimeDimension id="TIME_PERIOD" position="3">
              <str:ConceptIdentity><Ref id="TIME_PERIOD" /></str:ConceptIdentity>
            </str:TimeDimension>
          </str:DimensionList>
        </str:DataStructureComponents>
      </str:DataStructure>
    </str:DataStructures>
    <str:Concepts>
      <str:ConceptScheme id="NAIO_10_FCP_II4">
        <str:Concept id="FREQ"><com:Name xml:lang="en">Frequency</com:Name></str:Concept>
        <str:Concept id="GEO"><com:Name xml:lang="en">Geographical area</com:Name></str:Concept>
        <str:Concept id="TIME_PERIOD"><com:Name xml:lang="en">Time</com:Name></str:Concept>
      </str:ConceptScheme>
    </str:Concepts>
    <str:Codelists>
      <str:Codelist id="FREQ">
        <str:Code id="A"><com:Name xml:lang="en">Annual</com:Name></str:Code>
      </str:Codelist>
      <str:Codelist id="GEO">
        <str:Code id="DE"><com:Name xml:lang="en">Germany</com:Name></str:Code>
        <str:Code id="FR"><com:Name xml:lang="en">France</com:Name></str:Code>
        <str:Code id="IT"><com:Name xml:lang="en">Italy</com:Name></str:Code>
      </str:Codelist>
    </str:Codelists>
  </mes:Structures>
</mes:Structure>
"""


SDMX_CONSTRAINT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure
    xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v3_0/message"
    xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v3_0/structure"
    xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v3_0/common">
  <mes:Structures>
    <str:DataConstraints>
      <str:DataConstraint id="NAIO_10_FCP_II4">
        <str:CubeRegion include="true">
          <com:KeyValue id="freq"><com:Value>A</com:Value></com:KeyValue>
          <com:KeyValue id="geo"><com:Value>FR</com:Value></com:KeyValue>
          <com:KeyValue id="TIME_PERIOD"><com:Value>2022</com:Value></com:KeyValue>
        </str:CubeRegion>
      </str:DataConstraint>
    </str:DataConstraints>
  </mes:Structures>
</mes:Structure>
"""


class EurostatApiTests(unittest.TestCase):
    def test_sdmx_urls_request_structure_and_constraints_without_data(self) -> None:
        dataflow_url = build_sdmx_dataflow_url("naio_10_fcp_ii4")
        constraint_url = build_sdmx_constraint_url("naio_10_fcp_ii4")

        self.assertIn("/sdmx/2.1/dataflow/ESTAT/NAIO_10_FCP_II4/", dataflow_url)
        self.assertIn("references=descendants", dataflow_url)
        self.assertIn("detail=referencepartial", dataflow_url)
        self.assertIn(
            "/sdmx/3.0/structure/dataconstraint/ESTAT/NAIO_10_FCP_II4/",
            constraint_url,
        )

    def test_parses_sdmx_dimensions_and_available_positions(self) -> None:
        result = parse_sdmx_dimensions(
            SDMX_DATAFLOW_XML,
            SDMX_CONSTRAINT_XML,
            "naio_10_fcp_ii4",
        )

        self.assertEqual(result["inspection_source"], "sdmx")
        self.assertEqual(result["label"], "Inter-country input-output table")
        self.assertEqual([item["id"] for item in result["dimensions"]], ["freq", "geo", "time"])
        self.assertEqual(result["dimensions"][1]["label"], "Geographical area")
        self.assertEqual(
            [item["code"] for item in result["dimensions"][1]["categories"]],
            ["FR"],
        )
        self.assertEqual(result["dimensions"][2]["categories"][0]["code"], "2022")

    def test_large_dataset_dimension_inspection_never_requests_observations(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "skill.scripts.eurostat_api.get_text",
                side_effect=[SDMX_DATAFLOW_XML, SDMX_CONSTRAINT_XML],
            ) as get_text_mock,
            patch(
                "skill.scripts.eurostat_api.get_json",
                side_effect=AssertionError("observation endpoint must not be used"),
            ),
            redirect_stdout(stdout),
        ):
            dimensions("naio_10_fcp_ii4", ["France", "2022"])

        output = json.loads(stdout.getvalue())
        self.assertEqual(output["inspection_source"], "sdmx")
        self.assertEqual(get_text_mock.call_count, 2)
        self.assertEqual(output["matches"][0]["categories"][0]["code"], "FR")
        self.assertEqual(output["matches"][1]["categories"][0]["code"], "2022")

    def test_dimension_inspection_falls_back_to_statistics_api(self) -> None:
        statistics_response = {
            "label": "Population",
            "updated": "2026-01-01",
            "id": ["geo", "time"],
            "size": [1, 1],
            "dimension": {
                "geo": {
                    "label": "Geography",
                    "category": {"index": {"FR": 0}, "label": {"FR": "France"}},
                },
                "time": {
                    "label": "Time",
                    "category": {"index": {"2025": 0}, "label": {"2025": "2025"}},
                },
            },
            "value": [1],
        }
        stdout = io.StringIO()
        with (
            patch("skill.scripts.eurostat_api.get_text", return_value="not XML"),
            patch("skill.scripts.eurostat_api.get_json", return_value=statistics_response),
            redirect_stdout(stdout),
        ):
            dimensions("demo_pjan")

        output = json.loads(stdout.getvalue())
        self.assertEqual(output["inspection_source"], "statistics_fallback")
        self.assertEqual(output["dimensions"][0]["sample_categories"][0]["code"], "FR")

    def test_estimated_cell_count_rejects_over_broad_cubes_before_flattening(self) -> None:
        self.assertEqual(estimated_cell_count({"size": [2, 3, 4]}), 24)

        with self.assertRaisesRegex(SystemExit, "too broad"):
            estimated_cell_count({"size": [MAX_ESTIMATED_CELLS, 2]})

    def test_http_reader_rejects_responses_above_the_byte_limit(self) -> None:
        class Response:
            headers = {"Content-Length": str(MAX_RESPONSE_BYTES + 1)}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("skill.scripts.eurostat_api.urllib.request.urlopen", return_value=Response()):
            with self.assertRaisesRegex(SystemExit, "too large"):
                get_text("https://example.test/data")

    def test_fetch_requires_a_bounded_time_filter_before_network_access(self) -> None:
        arguments = Namespace(
            dataset="demo_pjan",
            param=["geo=DE"],
            last_time_period=None,
            time=[],
            max_rows=500,
            output="json",
        )

        with patch("skill.scripts.eurostat_api.get_json") as get_json_mock:
            with self.assertRaisesRegex(SystemExit, "bounded time filter"):
                fetch(arguments)

        get_json_mock.assert_not_called()

    def test_fetch_rejects_conflicting_time_selectors_before_network_access(self) -> None:
        for param, time in ((["geo=DE"], ["2024"]), (["geo=DE", "time=2024"], [])):
            arguments = Namespace(
                dataset="demo_pjan",
                param=param,
                last_time_period=1,
                time=time,
                max_rows=500,
                output="json",
            )

            with self.subTest(param=param, time=time):
                with patch("skill.scripts.eurostat_api.get_json") as get_json_mock:
                    with self.assertRaisesRegex(SystemExit, "mutually exclusive"):
                        fetch(arguments)

                get_json_mock.assert_not_called()

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

    def test_dimension_matching_resolves_input_output_activity_language(self) -> None:
        data = {
            "id": ["ind_use"],
            "dimension": {
                "ind_use": {
                    "category": {
                        "index": {"A01": 0, "C10-12": 1, "C20": 2},
                        "label": {
                            "A01": (
                                "Crop and animal production, hunting and related service activities"
                            ),
                            "C10-12": (
                                "Manufacture of food products; beverages and tobacco products"
                            ),
                            "C20": "Manufacture of chemicals and chemical products",
                        },
                    }
                }
            },
        }

        matches = match_dimension_categories(data, ["Agriculture", "Manufacturing"])

        self.assertEqual(matches[0]["categories"][0]["code"], "A01")
        manufacturing_codes = {
            item["code"] for item in matches[1]["categories"]
        }
        self.assertEqual(manufacturing_codes, {"C10-12", "C20"})


if __name__ == "__main__":
    unittest.main()
