from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.prompt_regression import (
    CASSETTE_DIR,
    SCENARIO_DIR,
    ReplayChat,
    ReplayTools,
    ScenarioFailure,
    assert_turn,
    execute_scenario,
    load_cassette,
    load_scenario,
)


class PromptRegressionHarnessTests(unittest.TestCase):
    def test_every_scenario_has_a_valid_replay_cassette(self) -> None:
        paths = sorted(SCENARIO_DIR.glob("*.json"))
        self.assertGreaterEqual(len(paths), 5)

        for path in paths:
            scenario = load_scenario(path)
            cassette = load_cassette(
                CASSETTE_DIR / f"{scenario['id']}.json",
                scenario["id"],
                len(scenario["turns"]),
            )
            self.assertEqual(len(cassette["turns"]), len(scenario["turns"]))

    def test_replay_is_offline_and_deterministic(self) -> None:
        scenario = load_scenario(SCENARIO_DIR / "solar_generation_selection.json")
        cassette = load_cassette(
            CASSETTE_DIR / "solar_generation_selection.json",
            scenario["id"],
            len(scenario["turns"]),
        )

        with (
            patch("tests.prompt_regression.openrouter_chat", side_effect=AssertionError("network")),
            patch("tests.prompt_regression.call_tool", side_effect=AssertionError("network")),
        ):
            first, _ = execute_scenario(scenario, mode="replay", cassette=cassette)
            second, _ = execute_scenario(scenario, mode="replay", cassette=cassette)

        self.assertEqual(first, second)
        self.assertEqual(first[0]["result"]["filters"]["siec"], ["RA420"])

    def test_replay_reports_cassette_exhaustion_and_unexpected_tools(self) -> None:
        chat = ReplayChat([])
        with self.assertRaisesRegex(ScenarioFailure, "exhausted"):
            chat("model", [])

        tools = ReplayTools([])
        with self.assertRaisesRegex(ScenarioFailure, "unexpected tool call"):
            tools("fetch_eurostat", "{}")

    def test_assertions_reject_tool_markup_duplicates_and_unknown_keys(self) -> None:
        with self.assertRaisesRegex(ScenarioFailure, "tool-call markup"):
            assert_turn(
                {"answer": "<tool_call>fetch_eurostat</tool_call>", "result": None},
                {"result": "null"},
            )

        duplicate = {
            "answer": "Done.",
            "result": None,
            "tool_call_details": [
                {"name": "search_eurostat", "arguments": {"query": "gdp"}},
                {"name": "search_eurostat", "arguments": {"query": "gdp"}},
            ],
        }
        with self.assertRaisesRegex(ScenarioFailure, "duplicate tool call"):
            assert_turn(duplicate, {"result": "null"})
        with self.assertRaisesRegex(ScenarioFailure, "unsupported assertions"):
            assert_turn({"answer": "Done.", "result": None}, {"exact_answer": "Done."})

    def test_malformed_scenario_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "id": "different-name",
                        "turns": [{"expect": {}}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ScenarioFailure):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
