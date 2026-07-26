from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.main import (
    ChatRequest,
    ChatResponse,
    _session_token,
    _valid_session_token,
)
from app.sandbox_agent import (
    MAX_EVENT_PREVIEW_CHARS,
    MAX_TOOL_CALLS,
    MAX_TOOL_ROUNDS,
    TOOLS,
    build_messages,
    build_scatter_result,
    build_structured_result,
    response_result,
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

    def test_app_lock_session_token_is_signed_and_expires(self) -> None:
        token = _session_token("correct horse battery staple", expires_at=1_000)

        self.assertTrue(
            _valid_session_token(
                token,
                "correct horse battery staple",
                now=999,
            )
        )
        self.assertFalse(_valid_session_token(token, "wrong password", now=999))
        self.assertFalse(_valid_session_token(token, "correct horse battery staple", now=1_000))
        self.assertFalse(
            _valid_session_token(
                f"{token}tampered",
                "correct horse battery staple",
                now=999,
            )
        )

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

    def test_redundant_choose_chart_tool_is_not_exposed(self) -> None:
        tool_names = {tool["function"]["name"] for tool in TOOLS}

        self.assertNotIn("choose_chart", tool_names)

    def test_configure_chart_tool_exposes_bounded_chart_modifications(self) -> None:
        configure_chart = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "configure_chart"
        )

        properties = configure_chart["parameters"]["properties"]
        self.assertIn("auto", properties["type"]["enum"])
        self.assertIn("heatmap", properties["type"]["enum"])
        self.assertIn("distribution", properties["purpose"]["enum"])
        self.assertEqual(properties["top_n"]["maximum"], 50)
        self.assertFalse(configure_chart["parameters"]["additionalProperties"])

    def test_auto_distribution_choice_resolves_to_histogram(self) -> None:
        result = build_structured_result(
            self.fetch_record,
            {
                "purpose": "distribution",
                "type": "auto",
                "x": "value",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "histogram")
        self.assertEqual(result["chart"]["purpose"], "distribution")
        self.assertEqual(result["chart"]["x"], "value")
        ChatResponse(answer="Distribution.", result=result)

    def test_auto_comparison_uses_dot_plot_for_many_categories(self) -> None:
        self.fetch_record["output"]["rows"] = [
            {"geo_label": f"Country {index}", "value": index}
            for index in range(15)
        ]
        result = build_structured_result(
            self.fetch_record,
            {
                "purpose": "comparison",
                "type": "auto",
                "x": "geo_label",
                "y": "value",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "dot")

    def test_heatmap_requires_two_dimensions_and_numeric_color(self) -> None:
        result = build_structured_result(
            self.fetch_record,
            {
                "purpose": "relationship",
                "type": "heatmap",
                "x": "time_label",
                "y": "geo_label",
                "color": "value",
                "top_n": 10,
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "heatmap")
        self.assertEqual(result["chart"]["color"], "value")
        self.assertEqual(result["chart"]["top_n"], 10)

    def test_composition_choice_adds_normalized_stacking(self) -> None:
        result = build_structured_result(
            self.fetch_record,
            {
                "purpose": "composition",
                "type": "bar",
                "x": "time_label",
                "y": "value",
                "series": "geo_label",
                "stack": "normalize",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "bar")
        self.assertEqual(result["chart"]["stack"], "normalize")
        self.assertEqual(result["chart"]["series"], "geo_label")
        self.assertTrue(result["chart"]["zero_baseline"])

    def test_log_scale_falls_back_for_nonpositive_values(self) -> None:
        self.fetch_record["output"]["rows"][0]["value"] = 0
        result = build_structured_result(
            self.fetch_record,
            {
                "purpose": "trend",
                "type": "line",
                "x": "time_label",
                "y": "value",
                "series": "geo_label",
                "scale": "log",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["scale"], "linear")

    def test_two_fetched_measures_build_a_paired_scatter_and_table(self) -> None:
        gdp_fetch = {
            "arguments": {
                "dataset": "sdg_10_10",
                "params": ["indic_ppp=EXP_PPS_EU27_2020_HAB"],
                "last_time_period": 1,
            },
            "output": {
                "metadata": {
                    "label": "Purchasing power adjusted GDP per capita",
                    "updated": "2026-03-01T00:00:00+0100",
                },
                "rows": [
                    {
                        "geo": "DE",
                        "geo_label": "Germany",
                        "time": "2025",
                        "time_label": "2025",
                        "value": 48_000,
                    },
                    {
                        "geo": "FR",
                        "geo_label": "France",
                        "time": "2025",
                        "time_label": "2025",
                        "value": 40_700,
                    },
                ],
            },
        }
        patent_fetch = {
            "arguments": {
                "dataset": "pat_ep_tot",
                "params": ["unit=P_MHAB", "coop_ptn=APPL"],
                "last_time_period": 1,
            },
            "output": {
                "metadata": {
                    "label": "Patent applications to the EPO",
                    "updated": "2026-03-24T23:00:00+0100",
                },
                "rows": [
                    {
                        "geo": "DE",
                        "geo_label": "Germany",
                        "time": "2025",
                        "time_label": "2025",
                        "value": 292.86,
                    },
                    {
                        "geo": "FR",
                        "geo_label": "France",
                        "time": "2025",
                        "time_label": "2025",
                        "value": 158.70,
                    },
                ],
            },
        }

        result = build_scatter_result(
            [gdp_fetch, patent_fetch],
            {
                "x_dataset": "sdg_10_10",
                "y_dataset": "pat_ep_tot",
                "join_on": ["geo", "time"],
                "x_label": "GDP per capita (PPS)",
                "y_label": "Patents per million inhabitants",
                "title": "GDP per capita and patent applications",
                "label": "geo_label",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "scatter")
        self.assertEqual(result["chart"]["label"], "geo_label")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(result["rows"][0]["geo_label"], "Germany")
        x_field = result["chart"]["x"]
        y_field = result["chart"]["y"]
        self.assertEqual(result["rows"][0][x_field], 48_000)
        self.assertEqual(result["rows"][0][y_field], 292.86)
        response = ChatResponse(answer="Positive relationship.", result=result)
        self.assertEqual(len(response.result.sources), 2)

    def test_create_scatter_tool_is_available_for_multi_dataset_relationships(self) -> None:
        create_scatter = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "create_scatter"
        )

        self.assertIn("two previously fetched", create_scatter["description"])
        self.assertIn("join_on", create_scatter["parameters"]["required"])

    @patch("app.sandbox_agent.call_tool")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_agent_returns_composed_scatter_instead_of_last_fetched_bar(
        self,
        chat_mock,
        tool_mock,
    ) -> None:
        gdp_output = {
            "metadata": {"label": "GDP per capita"},
            "rows": [
                {
                    "geo": "DE",
                    "geo_label": "Germany",
                    "time": "2025",
                    "time_label": "2025",
                    "value": 48_000,
                },
                {
                    "geo": "FR",
                    "geo_label": "France",
                    "time": "2025",
                    "time_label": "2025",
                    "value": 40_700,
                },
            ],
        }
        patents_output = {
            "metadata": {"label": "Patent applications per million inhabitants"},
            "rows": [
                {
                    "geo": "DE",
                    "geo_label": "Germany",
                    "time": "2025",
                    "time_label": "2025",
                    "value": 292.86,
                },
                {
                    "geo": "FR",
                    "geo_label": "France",
                    "time": "2025",
                    "time_label": "2025",
                    "value": 158.70,
                },
            ],
        }

        def tool_output(name: str, raw_arguments: str) -> str:
            arguments = json.loads(raw_arguments)
            if name == "fetch_eurostat" and arguments["dataset"] == "sdg_10_10":
                return json.dumps(gdp_output)
            if name == "fetch_eurostat" and arguments["dataset"] == "pat_ep_tot":
                return json.dumps(patents_output)
            return "{}"

        tool_mock.side_effect = tool_output
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "fetch-gdp",
                                    "function": {
                                        "name": "fetch_eurostat",
                                        "arguments": json.dumps(
                                            {
                                                "dataset": "sdg_10_10",
                                                "last_time_period": 1,
                                            }
                                        ),
                                    },
                                },
                                {
                                    "id": "fetch-patents",
                                    "function": {
                                        "name": "fetch_eurostat",
                                        "arguments": json.dumps(
                                            {
                                                "dataset": "pat_ep_tot",
                                                "last_time_period": 1,
                                            }
                                        ),
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
                                    "id": "make-scatter",
                                    "function": {
                                        "name": "create_scatter",
                                        "arguments": json.dumps(
                                            {
                                                "x_dataset": "sdg_10_10",
                                                "y_dataset": "pat_ep_tot",
                                                "join_on": ["geo", "time"],
                                                "x_label": "GDP per capita (PPS)",
                                                "y_label": "Patents per million inhabitants",
                                                "title": "GDP per capita and patent applications",
                                                "label": "geo_label",
                                            }
                                        ),
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
                            "content": "The paired data show a positive relationship.",
                        }
                    }
                ]
            },
        ]

        response = run(
            {
                "query": (
                    "Is GDP per capita correlated with patent applications per million "
                    "inhabitants?"
                )
            }
        )

        assert response["result"] is not None
        self.assertEqual(response["result"]["chart"]["type"], "scatter")
        self.assertEqual(response["result"]["dataset"]["code"], "sdg_10_10__pat_ep_tot")
        self.assertEqual(len(response["result"]["rows"]), 2)
        self.assertEqual(response["tool_call_details"][-1]["name"], "create_scatter")
        self.assertEqual(response["tool_call_details"][-1]["status"], "completed")

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

    def test_system_prompt_includes_chart_selection_and_configuration_rules(self) -> None:
        messages = build_messages({"query": "Show the distribution."})

        self.assertIn("Chart selection", messages[0]["content"])
        self.assertIn("configure_chart", messages[0]["content"])
        self.assertIn("histogram", messages[0]["content"])

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

    def test_follow_up_request_accepts_previous_chart_data(self) -> None:
        context_result = build_structured_result(self.fetch_record)
        request = ChatRequest(
            message="Which country grew faster?",
            context_result=context_result,
        )

        assert request.context_result is not None
        self.assertEqual(request.context_result.dataset.code, "demo_pjan")
        self.assertEqual(len(request.context_result.rows), 4)

    def test_previous_chart_data_is_added_to_model_context(self) -> None:
        context_result = build_structured_result(self.fetch_record)
        messages = build_messages(
            {
                "query": "Which country grew faster?",
                "context_result": context_result,
            }
        )

        self.assertIn("Reusable structured result", messages[-2]["content"])
        self.assertIn('"geo":"DE"', messages[-2]["content"])
        self.assertEqual(messages[-1]["content"], "Which country grew faster?")

    def test_previous_result_is_returned_without_a_new_fetch(self) -> None:
        context_result = build_structured_result(self.fetch_record)
        result = response_result(None, context_result)

        self.assertEqual(result, context_result)

    def test_follow_up_can_rechart_previous_rows_without_fetching(self) -> None:
        context_result = build_structured_result(self.fetch_record)
        result = response_result(
            None,
            context_result,
            {
                "type": "bar",
                "x": "time_label",
                "y": "value",
                "series": "geo_label",
                "orientation": "vertical",
            },
        )

        assert result is not None
        self.assertEqual(result["chart"]["type"], "bar")
        self.assertEqual(result["chart"]["orientation"], "vertical")
        self.assertEqual(result["rows"], context_result["rows"])

    @patch("app.sandbox_agent.openrouter_chat")
    def test_follow_up_can_answer_without_any_tool_calls(self, chat_mock) -> None:
        context_result = build_structured_result(self.fetch_record)
        chat_mock.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Germany grew faster in the loaded period.",
                    }
                }
            ]
        }

        response = run(
            {
                "query": "Which country grew faster?",
                "context_result": context_result,
            }
        )

        self.assertEqual(response["tool_calls"], 0)
        self.assertEqual(response["result"], context_result)

    @patch("app.sandbox_agent.openrouter_chat")
    def test_agent_can_configure_reusable_rows_without_fetching(self, chat_mock) -> None:
        context_result = build_structured_result(self.fetch_record)
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "configure-chart",
                                    "function": {
                                        "name": "configure_chart",
                                        "arguments": json.dumps(
                                            {
                                                "purpose": "relationship",
                                                "type": "heatmap",
                                                "x": "time_label",
                                                "y": "geo_label",
                                                "color": "value",
                                                "labels": "hover",
                                            }
                                        ),
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
                            "content": "The loaded observations are now shown as a heatmap.",
                        }
                    }
                ]
            },
        ]

        response = run(
            {
                "query": "Turn the existing result into a heatmap.",
                "context_result": context_result,
            }
        )

        self.assertEqual(response["tool_calls"], 1)
        self.assertEqual(response["tool_call_details"][0]["name"], "configure_chart")
        self.assertEqual(response["result"]["chart"]["type"], "heatmap")
        self.assertEqual(response["result"]["rows"], context_result["rows"])

    @patch("app.sandbox_agent.call_tool")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_ambiguous_measure_is_clarified_after_bounded_discovery(
        self,
        chat_mock,
        tool_mock,
    ) -> None:
        search_output = json.dumps(
            [
                {
                    "code": "pat_ep_tot",
                    "title": "Patent applications to the EPO",
                },
                {
                    "code": "rd_e_gerdtot",
                    "title": "GERD by sectors of performance",
                },
            ]
        )
        dimensions_output = {
            "pat_ep_tot": json.dumps(
                {
                    "dataset": "pat_ep_tot",
                    "dimensions": [
                        {
                            "id": "unit",
                            "size": 1,
                            "sample_categories": [
                                {
                                    "code": "P_MHAB",
                                    "label": "Per million inhabitants",
                                }
                            ],
                        }
                    ],
                }
            ),
            "rd_e_gerdtot": json.dumps(
                {
                    "dataset": "rd_e_gerdtot",
                    "dimensions": [
                        {
                            "id": "unit",
                            "size": 1,
                            "sample_categories": [
                                {
                                    "code": "PC_GDP",
                                    "label": "Percentage of GDP",
                                }
                            ],
                        }
                    ],
                }
            ),
        }

        def tool_output(name: str, raw_arguments: str) -> str:
            arguments = json.loads(raw_arguments)
            if name == "search_eurostat":
                return search_output
            if name == "inspect_dimensions":
                return dimensions_output[arguments["dataset"]]
            self.fail(f"Unexpected tool call during clarification discovery: {name}")

        tool_mock.side_effect = tool_output
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "search-innovation",
                                    "function": {
                                        "name": "search_eurostat",
                                        "arguments": json.dumps(
                                            {"query": "innovation EU countries"}
                                        ),
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
                            "tool_calls": [
                                {
                                    "id": "inspect-patents",
                                    "function": {
                                        "name": "inspect_dimensions",
                                        "arguments": json.dumps(
                                            {"dataset": "pat_ep_tot"}
                                        ),
                                    },
                                },
                                {
                                    "id": "inspect-rd",
                                    "function": {
                                        "name": "inspect_dimensions",
                                        "arguments": json.dumps(
                                            {"dataset": "rd_e_gerdtot"}
                                        ),
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
                            "content": (
                                "I found patent applications per million inhabitants "
                                "(pat_ep_tot) and R&D expenditure as a percentage of GDP "
                                "(rd_e_gerdtot). Patents are the closer per-capita output "
                                "measure, so I recommend pat_ep_tot. Which should represent "
                                "innovation?"
                            ),
                        }
                    }
                ]
            },
        ]

        response = run(
            {
                "query": (
                    "Is GDP per capita correlated with innovation per capita across EU countries?"
                )
            }
        )

        self.assertEqual(response["tool_calls"], 3)
        self.assertIsNone(response["result"])
        self.assertIn("pat_ep_tot", response["answer"])
        self.assertIn("rd_e_gerdtot", response["answer"])
        self.assertIn("recommend", response["answer"])
        called_tools = [detail["name"] for detail in response["tool_call_details"]]
        self.assertEqual(
            called_tools,
            ["search_eurostat", "inspect_dimensions", "inspect_dimensions"],
        )
        self.assertNotIn("fetch_eurostat", called_tools)

    @patch("app.sandbox_agent.call_tool")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_clarification_choice_fetches_without_repeating_discovery(
        self,
        chat_mock,
        tool_mock,
    ) -> None:
        tool_mock.return_value = json.dumps(self.fetch_record["output"])
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "fetch-patents",
                                    "function": {
                                        "name": "fetch_eurostat",
                                        "arguments": json.dumps(
                                            {
                                                "dataset": "pat_ep_tot",
                                                "params": [
                                                    "unit=P_MHAB",
                                                    "geo=DE,FR",
                                                ],
                                                "last_time_period": 1,
                                            }
                                        ),
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
                            "content": "I used patent applications per million inhabitants.",
                        }
                    }
                ]
            },
        ]

        response = run(
            {
                "query": "Use patents per million inhabitants.",
                "history": [
                    {
                        "role": "user",
                        "content": (
                            "Is GDP per capita correlated with innovation per capita across "
                            "EU countries?"
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": (
                            "I found pat_ep_tot and rd_e_gerdtot. Which should represent "
                            "innovation?"
                        ),
                    },
                ],
            }
        )

        self.assertEqual(response["tool_calls"], 1)
        self.assertEqual(
            [detail["name"] for detail in response["tool_call_details"]],
            ["fetch_eurostat"],
        )
        self.assertEqual(response["result"]["dataset"]["code"], "pat_ep_tot")

    @patch("app.sandbox_agent.call_tool", return_value="[]")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_identical_tool_calls_are_executed_once(self, chat_mock, tool_mock) -> None:
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "search-1",
                                    "function": {
                                        "name": "search_eurostat",
                                        "arguments": '{"query":"population"}',
                                    },
                                },
                                {
                                    "id": "search-2",
                                    "function": {
                                        "name": "search_eurostat",
                                        "arguments": '{"query":"population"}',
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
                            "content": "I found the relevant population candidates.",
                        }
                    }
                ]
            },
        ]

        response = run({"query": "Find a population dataset."})

        self.assertEqual(response["tool_calls"], 1)
        self.assertEqual(len(response["tool_call_details"]), 1)
        self.assertEqual(tool_mock.call_count, 1)

    @patch("app.sandbox_agent.call_tool", return_value="[]")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_search_budget_stops_reformulation_loop(self, chat_mock, tool_mock) -> None:
        searches = [
            {
                "id": f"search-{index}",
                "function": {
                    "name": "search_eurostat",
                    "arguments": json.dumps({"query": f"innovation proxy {index}"}),
                },
            }
            for index in range(5)
        ]
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": searches,
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Please choose the intended innovation measure.",
                        }
                    }
                ]
            },
        ]

        response = run({"query": "Compare explicit patent innovation proxy measures."})

        self.assertEqual(response["tool_calls"], 4)
        self.assertEqual(tool_mock.call_count, 4)
        self.assertEqual(len(response["tool_call_details"]), 4)
        self.assertEqual(chat_mock.call_args_list[-1].args[2], [])

    @patch("app.sandbox_agent.call_tool")
    @patch("app.sandbox_agent.openrouter_chat")
    def test_invalid_complete_dimension_code_is_rejected_before_fetch(
        self,
        chat_mock,
        tool_mock,
    ) -> None:
        dimensions_output = json.dumps(
            {
                "dataset": "nama_10_pc",
                "dimensions": [
                    {
                        "id": "unit",
                        "size": 2,
                        "sample_categories": [
                            {"code": "CP_EUR_HAB", "label": "Euro per inhabitant"},
                            {
                                "code": "CP_PPS_EU27_2020_HAB",
                                "label": "PPS per inhabitant",
                            },
                        ],
                    }
                ],
            }
        )
        tool_mock.return_value = dimensions_output
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "inspect",
                                    "function": {
                                        "name": "inspect_dimensions",
                                        "arguments": '{"dataset":"nama_10_pc"}',
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
                            "tool_calls": [
                                {
                                    "id": "fetch",
                                    "function": {
                                        "name": "fetch_eurostat",
                                        "arguments": json.dumps(
                                            {
                                                "dataset": "nama_10_pc",
                                                "params": ["unit=PC_PPS_EU27_2020_HAB"],
                                            }
                                        ),
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
                            "content": "The requested unit code was invalid.",
                        }
                    }
                ]
            },
        ]

        response = run({"query": "Use nama_10_pc for GDP per capita."})

        self.assertEqual(response["tool_calls"], 2)
        self.assertEqual(tool_mock.call_count, 1)
        self.assertEqual(response["tool_call_details"][-1]["status"], "error")
        self.assertIn(
            "CP_PPS_EU27_2020_HAB",
            response["tool_call_details"][-1]["result_preview"],
        )

    @patch(
        "app.sandbox_agent.call_tool",
        return_value=json.dumps(
            {
                "metadata": {
                    "label": "Population",
                    "total_rows": 0,
                    "returned_rows": 0,
                    "truncated": False,
                },
                "rows": [],
            }
        ),
    )
    @patch("app.sandbox_agent.openrouter_chat")
    def test_zero_row_fetch_is_an_error_and_not_a_result(self, chat_mock, tool_mock) -> None:
        chat_mock.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "fetch",
                                    "function": {
                                        "name": "fetch_eurostat",
                                        "arguments": '{"dataset":"demo_pjan","params":["geo=XX"]}',
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
                            "content": "The filters returned no observations.",
                        }
                    }
                ]
            },
        ]

        response = run({"query": "Fetch population for an invalid geography."})

        self.assertEqual(response["tool_calls"], 1)
        self.assertIsNone(response["result"])
        self.assertEqual(response["tool_call_details"][0]["status"], "error")
        self.assertEqual(tool_mock.call_count, 1)

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

    def test_agent_has_bounded_round_and_tool_limits(self) -> None:
        self.assertEqual(MAX_TOOL_ROUNDS, 12)
        self.assertEqual(MAX_TOOL_CALLS, 12)

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
