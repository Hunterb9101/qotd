from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from qotd.usecases.score_responses import LLMAnswerInterpreter
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


if __name__ == "__main__":
    unittest.main()
