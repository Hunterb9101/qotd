"""Generate a Google OAuth refresh token for the QOTD Gmail account."""

from __future__ import annotations

import argparse

GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the token helper parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_secrets_file", help="Downloaded OAuth desktop client JSON file")
    return parser


def main() -> None:
    """Run a local OAuth browser flow and print the GitHub secret values."""

    flow_module = __import__("google_auth_oauthlib.flow", fromlist=["InstalledAppFlow"])
    args = build_parser().parse_args()
    flow = flow_module.InstalledAppFlow.from_client_secrets_file(
        args.client_secrets_file,
        scopes=list(GOOGLE_OAUTH_SCOPES),
    )
    credentials = flow.run_local_server(port=0, prompt="consent")
    client_config = flow.client_config

    print("Add these values to the GitHub production environment secrets:")
    print(f"GOOGLE_OAUTH_CLIENT_ID={client_config['client_id']}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={client_config['client_secret']}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")


if __name__ == "__main__":
    main()
