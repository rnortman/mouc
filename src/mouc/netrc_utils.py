"""Utilities for reading Jira credentials from .netrc file."""

import netrc
import os
from pathlib import Path
from urllib.parse import urlparse


def get_jira_credentials_from_netrc(base_url: str) -> tuple[str | None, str | None]:
    """
    Retrieve Jira credentials from .netrc file.

    Extracts the hostname from the base_url and looks up credentials
    in the user's .netrc file (~/.netrc on Unix, ~/_netrc on Windows).

    Args:
        base_url: The Jira base URL (e.g., 'https://example.atlassian.net')

    Returns:
        A tuple of (login, password) if found, or (None, None) if not found
        or if any error occurs during lookup.

    Example .netrc entry:
        machine example.atlassian.net
        login user@example.com
        password your_api_token_here
    """
    try:
        # Extract hostname from URL
        parsed = urlparse(base_url)
        hostname = parsed.netloc or parsed.path.split("/")[0]

        if not hostname:
            return None, None

        # Locate .netrc file
        netrc_path = Path.home() / (".netrc" if os.name != "nt" else "_netrc")

        if not netrc_path.exists():
            return None, None

        # Parse .netrc and lookup credentials
        netrc_obj = netrc.netrc(str(netrc_path))
        auth = netrc_obj.authenticators(hostname)

        if auth:
            login, _, password = auth
            return login, password

        return None, None

    except (netrc.NetrcParseError, OSError, ValueError):
        # Silently handle errors - .netrc is optional
        return None, None
