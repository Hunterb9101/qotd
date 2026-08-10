import pytest

from qotd.usecases.parse_organizer_instruction import parse_organizer_instruction_payload


def test_parse_organizer_instruction_reads_only_the_initial_contiguous_block() -> None:
    payload = parse_organizer_instruction_payload(
        "Action: set-answer\n"
        "Day: 2026-08-10\n"
        "Correct option: B\n"
        "Source URL: https://example.com/source\n"
        "\n"
        "> Action: set-answer\n"
        "> Day: 2026-08-11\n"
    )

    assert payload.action == "set-answer"
    assert payload.fields["day"] == "2026-08-10"


@pytest.mark.parametrize(
    "body",
    (
        "Action: set-answer\nAction: set-answer\n",
        "Action: set-answer\nCorrect option: A\nCorrect option: B\n",
    ),
)
def test_parser_rejects_duplicate_fields(body: str) -> None:
    with pytest.raises(ValueError, match="duplicate field"):
        parse_organizer_instruction_payload(body)


def test_parser_does_not_treat_a_rejection_template_as_another_instruction() -> None:
    payload = parse_organizer_instruction_payload(
        "Action: set-answer\nDay: 2026-08-10\nCorrect option: B\nSource URL: https://example.com/source\n"
        "On Monday, someone wrote:\nAction: set-answer\nDay: 2026-08-11\n"
    )

    assert payload.fields["day"] == "2026-08-10"
