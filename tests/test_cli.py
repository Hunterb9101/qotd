from __future__ import annotations

from unittest.mock import patch

from qotd.cli import build_parser


def test_send_question_reads_google_group_email_from_environment() -> None:
    """Configure private Group delivery through the production environment."""

    with patch.dict(
        "os.environ",
        {"QOTD_GOOGLE_GROUP_EMAIL": "qotd-group@googlegroups.com"},
        clear=True,
    ):
        parser = build_parser()

    args = parser.parse_args(["send-question"])

    assert args.google_group_email == "qotd-group@googlegroups.com"
