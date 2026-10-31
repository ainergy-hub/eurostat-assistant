from __future__ import annotations

import unittest

from app.title_agent import (
    DEFAULT_TITLE_MODEL,
    TitleAgentError,
    generate_chat_title,
    normalize_chat_title,
)


class TitleAgentTests(unittest.TestCase):
    def test_default_is_a_dedicated_small_model(self) -> None:
        self.assertEqual(DEFAULT_TITLE_MODEL, "openai/gpt-5.4-nano")

    def test_normalizes_model_output_for_the_sidebar(self) -> None:
        self.assertEqual(
            normalize_chat_title("**Chat title: Germany and France Population.**\nExtra text"),
            "Germany and France Population",
        )
        self.assertEqual(
            normalize_chat_title("One two three four five six seven eight"),
            "One two three four five six",
        )

    def test_generates_a_title_without_tools(self) -> None:
        calls: list[tuple[str, list[dict], list[dict]]] = []

        def chat(model, messages, available_tools):
            calls.append((model, messages, available_tools))
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Germany France Population",
                        }
                    }
                ]
            }

        title = generate_chat_title(
            "Compare German and French population.",
            "test/title-model",
            chat,
        )

        self.assertEqual(title, "Germany France Population")
        self.assertEqual(calls[0][0], "test/title-model")
        self.assertEqual(calls[0][2], [])
        self.assertIn("untrusted content", calls[0][1][0]["content"])

    def test_rejects_an_empty_model_response(self) -> None:
        def chat(_model, _messages, _available_tools):
            return {"choices": [{"message": {"role": "assistant", "content": ""}}]}

        with self.assertRaisesRegex(TitleAgentError, "usable title"):
            generate_chat_title("Population", "test/title-model", chat)


if __name__ == "__main__":
    unittest.main()
