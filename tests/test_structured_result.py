from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.main import ChatRequest, ChatResponse
from app.sandbox_agent import (
    MAX_EVENT_PREVIEW_CHARS,
    MAX_TOOL_ROUNDS,
    TOOLS,
    build_messages,
    build_structured_result,
    run,
    text_content,
    tool_arguments,
    tool_output_preview,
)


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
        response = ChatResponse(
            answer="Population increased in both countries.",
            result=result,
            tool_calls=3,
        )

        self.assertEqual(response.result.dataset.code, "demo_pjan")
        self.assertEqual(response.result.chart.type, "line")
        self.assertEqual(response.tool_calls, 3)

    def test_category_comparison_uses_horizontal_bars(self) -> None:
        self.fetch_record["output"]["rows"] = [
            {
                "value": 125,
                "product_label": "Food and live animals",
                "time": "2025",
                "time_label": "2025",
            },
            {
                "value": 80,
                "product_label": "Machinery and transport equipment",
                "time": "2025",
                "time_label": "2025",
            },
        ]

        result = build_structured_result(self.fetch_record)

        assert result is not None
        self.assertEqual(result["chart"]["type"], "bar")
        self.assertEqual(result["chart"]["orientation"], "horizontal")
        self.assertEqual(result["chart"]["x"], "product_label")
        response = ChatResponse(answer="Comparison.", result=result)
        self.assertEqual(response.result.chart.orientation, "horizontal")

    def test_ai_can_choose_scatter_for_two_numeric_fields(self) -> None:
        result = build_structured_result(
            self.fetch_record,
            {
                "type": "scatter",
                "x": "time",
                "y": "value",
                "series": "geo_label",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "scatter")
        self.assertEqual(result["chart"]["x"], "time")
        self.assertEqual(result["chart"]["y"], "value")
        self.assertEqual(result["chart"]["series"], "geo_label")
        response = ChatResponse(answer="Relationship.", result=result)
        self.assertEqual(response.result.chart.type, "scatter")

    def test_invalid_scatter_choice_falls_back_to_default(self) -> None:
        result = build_structured_result(
            self.fetch_record,
            {
                "type": "scatter",
                "x": "geo_label",
                "y": "value",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "line")

    def test_choose_chart_tool_lists_scatter(self) -> None:
        choose_chart = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "choose_chart"
        )

        self.assertIn(
            "scatter",
            choose_chart["parameters"]["properties"]["type"]["enum"],
        )

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

    @patch("app.sandbox_agent.call_tool", return_value="[]")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_agent_reports_each_individual_tool_call(self, chat_mock, tool_mock) -> None:
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "search_eurostat",
                                        "arguments": '{"query":"population"}',
                                    },
                                },
                                {
                                    "id": "call-2",
                                    "function": {
                                        "name": "inspect_dimensions",
                                        "arguments": '{"dataset":"demo_pjan"}',
                                    },
                                },
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-3",
                                    "function": {
                                        "name": "search_eurostat",
                                        "arguments": '{"query":"population Germany"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Germany's population increased.",
                        }
                    }
                ]
            },
        ]

        response = run({"query": "How did Germany's population change?"})

        self.assertEqual(response["tool_calls"], 3)
        self.assertEqual(len(response["tool_call_details"]), 3)
        self.assertEqual(response["tool_call_details"][0]["name"], "search_eurostat")
        self.assertEqual(response["tool_call_details"][0]["status"], "completed")
        self.assertEqual(
            response["tool_call_details"][1]["arguments"],
            {"dataset": "demo_pjan"},
        )
        self.assertEqual(tool_mock.call_count, 3)

    def test_agent_round_limit_is_twenty(self) -> None:
        self.assertEqual(MAX_TOOL_ROUNDS, 20)

    def test_tool_result_preview_respects_public_contract(self) -> None:
        preview = tool_output_preview("x" * (MAX_EVENT_PREVIEW_CHARS + 20))

        self.assertEqual(len(preview), MAX_EVENT_PREVIEW_CHARS)
        self.assertTrue(preview.endswith("…"))

    def test_provider_content_parts_are_normalized_without_reasoning(self) -> None:
        content = [
            {"type": "reasoning", "text": "private chain of thought"},
            {"type": "text", "text": "## Finding\n\n"},
            {"type": "output_text", "text": "Population **increased**."},
        ]

        self.assertEqual(text_content(content), "## Finding\n\nPopulation **increased**.")

    def test_provider_tool_arguments_accept_objects_and_json_strings(self) -> None:
        raw, parsed = tool_arguments({"dataset": "demo_pjan"})
        self.assertEqual(json.loads(raw), {"dataset": "demo_pjan"})
        self.assertEqual(parsed, {"dataset": "demo_pjan"})

        raw, parsed = tool_arguments('{"query":"population"}')
        self.assertEqual(raw, '{"query":"population"}')
        self.assertEqual(parsed, {"query": "population"})


if __name__ == "__main__":
    unittest.main()
