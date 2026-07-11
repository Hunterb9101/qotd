from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from qotd.external.llm.openai import render_prompt
from qotd.usecases.score_responses import DEFAULT_INTERPRET_ANSWER_PROMPT_PATH, LLMAnswerInterpreter
from tests.test_phase3_scoring import stored_question


class FakeLLMClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def create_structured_response(
        self,
        *,
        prompt_path: Path,
        payload: dict[str, Any],
        response_model: type[Any],
        schema_name: str,
        max_output_tokens: int,
    ) -> Any:
        self.calls.append(
            {
                "prompt_path": prompt_path,
                "payload": payload,
                "response_model": response_model,
                "schema_name": schema_name,
                "max_output_tokens": max_output_tokens,
            }
        )
        return response_model.model_validate(self.output)


class LLMAnswerInterpreterTests(unittest.TestCase):
    def test_default_prompt_is_packaged_and_defines_freeform_policy(self) -> None:
        prompt = DEFAULT_INTERPRET_ANSWER_PROMPT_PATH.read_text(encoding="utf-8")

        self.assertIn("joking, explanatory, hedged, uncertain, or conversational", prompt)
        self.assertIn("exactly one intended choice is discernible", prompt)
        self.assertIn("materially conflicting selections", prompt)
        self.assertIn("loophole attempt", prompt)
        self.assertIn("Do not decide whether the selected option is correct", prompt)
        self.assertNotIn("docs/prompts", str(DEFAULT_INTERPRET_ANSWER_PROMPT_PATH))

    def test_default_prompt_renders_question_answer_pairs_and_reply(self) -> None:
        question = stored_question()
        rendered = render_prompt(
            DEFAULT_INTERPRET_ANSWER_PROMPT_PATH,
            {
                "question": {"prompt": question.prompt, "options": question.options},
                "reply_text": "Probably Jupiter",
            },
        )

        self.assertIn(f"Question: {question.prompt}", rendered)
        self.assertIn("- A: Mars", rendered)
        self.assertIn("- B: Jupiter", rendered)
        self.assertIn("- C: Saturn", rendered)
        self.assertIn("- D: Neptune", rendered)
        self.assertIn("Probably Jupiter", rendered)

    def test_llm_interpreter_maps_structured_response_to_interpretation(self) -> None:
        client = FakeLLMClient({"option": "B", "needs_review": False})
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("Interpret an answer.", encoding="utf-8")
            interpreter = LLMAnswerInterpreter(
                llm_client=client,
                question=stored_question(),
                prompt_path=prompt_path,
            )

            interpretation = interpreter("Probably Jupiter")

        self.assertEqual(interpretation.option, "B")
        self.assertFalse(interpretation.needs_review)

        call = client.calls[0]
        self.assertEqual(call["prompt_path"], prompt_path)
        self.assertEqual(call["schema_name"], "qotd_answer_interpretation")
        request_payload = cast(dict[str, Any], call["payload"])
        self.assertEqual(set(request_payload), {"question", "reply_text"})
        self.assertEqual(set(request_payload["question"]), {"prompt", "options"})
        self.assertEqual(request_payload["reply_text"], "Probably Jupiter")
        self.assertEqual(request_payload["question"]["options"]["B"], "Jupiter")

    def test_unknown_option_always_needs_review(self) -> None:
        interpreter = LLMAnswerInterpreter(
            llm_client=FakeLLMClient({"option": "UNKNOWN", "needs_review": False}),
            question=stored_question(),
        )

        interpretation = interpreter("no idea")

        self.assertEqual(interpretation.option, "UNKNOWN")
        self.assertTrue(interpretation.needs_review)

    def test_clear_freeform_variants_map_to_the_single_intended_choice(self) -> None:
        replies = (
            "Jupiter",
            "Jupiter, because of the Great Red Spot",
            "Probably Jupiter",
            "Jupiter, unless my science teacher lied 😄",
        )

        for reply in replies:
            with self.subTest(reply=reply):
                interpreter = LLMAnswerInterpreter(
                    llm_client=FakeLLMClient({"option": "B", "needs_review": False}),
                    question=stored_question(),
                )
                interpretation = interpreter(reply)
                self.assertEqual(interpretation.option, "B")
                self.assertFalse(interpretation.needs_review)

    def test_indeterminate_freeform_variants_remain_unknown(self) -> None:
        replies = ("", "B or C", "Give me credit for whichever is right")

        for reply in replies:
            with self.subTest(reply=reply):
                interpreter = LLMAnswerInterpreter(
                    llm_client=FakeLLMClient({"option": "UNKNOWN", "needs_review": True}),
                    question=stored_question(),
                )
                interpretation = interpreter(reply)
                self.assertEqual(interpretation.option, "UNKNOWN")
                self.assertTrue(interpretation.needs_review)


if __name__ == "__main__":
    unittest.main()
