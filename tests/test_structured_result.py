from __future__ import annotations

import unittest

from app.main import ChatRequest, ChatResponse
from app.sandbox_agent import build_messages, build_structured_result


class StructuredResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetch_record = {
            "arguments": {
                "dataset": "demo_pjan",
                "params": ["geo=DE,FR", "sex=T", "age=TOTAL"],
                "last_time_period": 2,
            },
            "output": {
                "metadata": {
                    "label": "Population on 1 January by age and sex",
                    "updated": "2026-07-25T11:00:00+0200",
                    "total_rows": 4,
                    "returned_rows": 4,
                    "truncated": False,
                },
                "rows": [
                    {
                        "value": 83_000_000,
                        "geo": "DE",
                        "geo_label": "Germany",
                        "sex": "T",
                        "sex_label": "Total",
                        "age": "TOTAL",
                        "age_label": "Total",
                        "time": "2024",
                        "time_label": "2024",
                    },
                    {
                        "value": 83_500_000,
                        "geo": "DE",
                        "geo_label": "Germany",
                        "sex": "T",
                        "sex_label": "Total",
                        "age": "TOTAL",
                        "age_label": "Total",
                        "time": "2025",
                        "time_label": "2025",
                    },
                    {
                        "value": 68_000_000,
                        "geo": "FR",
                        "geo_label": "France",
                        "sex": "T",
                        "sex_label": "Total",
                        "age": "TOTAL",
                        "age_label": "Total",
                        "time": "2024",
                        "time_label": "2024",
                    },
                    {
                        "value": 68_400_000,
                        "geo": "FR",
                        "geo_label": "France",
                        "sex": "T",
                        "sex_label": "Total",
                        "age": "TOTAL",
                        "age_label": "Total",
                        "time": "2025",
                        "time_label": "2025",
                    },
                ],
            },
        }

    def test_builds_chart_table_and_provenance(self) -> None:
        result = build_structured_result(self.fetch_record)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["dataset"]["code"], "demo_pjan")
        self.assertEqual(result["filters"]["geo"], ["DE", "FR"])
        self.assertEqual(result["filters"]["lastTimePeriod"], ["2"])
        self.assertEqual(result["chart"]["type"], "line")
        self.assertEqual(result["chart"]["x"], "time_label")
        self.assertEqual(result["chart"]["series"], "geo_label")
        self.assertIn("geo=DE", result["dataset"]["source_url"])
        self.assertIn("geo=FR", result["dataset"]["source_url"])
        self.assertEqual(len(result["rows"]), 4)

    def test_result_validates_against_public_api_contract(self) -> None:
        result = build_structured_result(self.fetch_record)
        response = ChatResponse(answer="Population increased in both countries.", result=result)

        self.assertEqual(response.result.dataset.code, "demo_pjan")
        self.assertEqual(response.result.chart.type, "line")

    def test_missing_fetch_has_no_result(self) -> None:
        self.assertIsNone(build_structured_result(None))

    def test_truncation_is_exposed_as_warning(self) -> None:
        self.fetch_record["output"]["metadata"]["truncated"] = True
        self.fetch_record["output"]["metadata"]["total_rows"] = 700
        self.fetch_record["output"]["metadata"]["returned_rows"] = 500

        result = build_structured_result(self.fetch_record)

        assert result is not None
        self.assertIn("Showing 500 of 700", result["warnings"][0])

    def test_summary_precedes_only_recent_history(self) -> None:
        payload = {
            "query": "What changed next?",
            "summary": "Earlier work used dataset demo_pjan with geo=DE.",
            "history": [
                {"role": "user", "content": f"Question {index}"}
                if index % 2 == 0
                else {"role": "assistant", "content": f"Answer {index}"}
                for index in range(8)
            ],
        }

        messages = build_messages(payload)

        self.assertIn("compact", messages[1]["content"])
        self.assertIn("demo_pjan", messages[1]["content"])
        self.assertEqual(messages[2]["content"], "Question 2")
        self.assertEqual(messages[-1]["content"], "What changed next?")

    def test_public_request_contract_bounds_recent_context(self) -> None:
        request = ChatRequest(
            message="Continue the comparison.",
            summary="Earlier investigation summary.",
            history=[
                {"role": "user" if index % 2 == 0 else "assistant", "content": f"Turn {index}"}
                for index in range(6)
            ],
        )

        self.assertEqual(len(request.history), 6)
        self.assertEqual(request.summary, "Earlier investigation summary.")


if __name__ == "__main__":
    unittest.main()
