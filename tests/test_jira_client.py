"""Tests for JiraClient credential handling."""

from unittest.mock import MagicMock, patch

import pytest

from mouc.jira_client import JiraAuthError, JiraClient


class TestJiraClientCredentials:
    """Tests for JiraClient credential resolution priority."""

    @patch("mouc.jira_client.Jira")
    def test_explicit_credentials_used(self, mock_jira_class: MagicMock) -> None:
        """Test that explicitly passed credentials are used."""
        client = JiraClient(
            base_url="https://example.atlassian.net",
            email="explicit@example.com",
            api_token="explicit_token",
        )

        assert client.email == "explicit@example.com"
        assert client.api_token == "explicit_token"
        mock_jira_class.assert_called_once_with(
            url="https://example.atlassian.net",
            username="explicit@example.com",
            password="explicit_token",
            cloud=True,
        )

    @patch("mouc.jira_client.Jira")
    @patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com", "JIRA_API_TOKEN": "env_token"})
    def test_env_vars_used_when_no_explicit_credentials(self, mock_jira_class: MagicMock) -> None:
        """Test that environment variables are used when no explicit credentials provided."""
        client = JiraClient(base_url="https://example.atlassian.net")

        assert client.email == "env@example.com"
        assert client.api_token == "env_token"
        mock_jira_class.assert_called_once_with(
            url="https://example.atlassian.net",
            username="env@example.com",
            password="env_token",
            cloud=True,
        )

    @patch("mouc.jira_client.Jira")
    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    @patch.dict("os.environ", {}, clear=True)
    def test_netrc_used_as_fallback(
        self, mock_get_netrc_creds: MagicMock, mock_jira_class: MagicMock
    ) -> None:
        """Test that .netrc is used when environment variables are not set."""
        mock_get_netrc_creds.return_value = ("netrc@example.com", "netrc_token")

        client = JiraClient(base_url="https://example.atlassian.net")

        assert client.email == "netrc@example.com"
        assert client.api_token == "netrc_token"
        mock_get_netrc_creds.assert_called_once_with("https://example.atlassian.net")
        mock_jira_class.assert_called_once_with(
            url="https://example.atlassian.net",
            username="netrc@example.com",
            password="netrc_token",
            cloud=True,
        )

    @patch("mouc.jira_client.Jira")
    @patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com", "JIRA_API_TOKEN": "env_token"})
    def test_env_vars_take_precedence_over_explicit_credentials(
        self, mock_jira_class: MagicMock
    ) -> None:
        """Test that env vars are checked before explicit params (via 'or' logic)."""
        # When both are provided, explicit should win due to parameter default handling
        client = JiraClient(
            base_url="https://example.atlassian.net",
            email="explicit@example.com",
            api_token="explicit_token",
        )

        assert client.email == "explicit@example.com"
        assert client.api_token == "explicit_token"

    @patch("mouc.jira_client.Jira")
    @patch.dict(
        "os.environ", {"JIRA_EMAIL": "env@example.com", "JIRA_API_TOKEN": "env_token"}, clear=True
    )
    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    def test_env_vars_take_precedence_over_netrc(
        self, mock_get_netrc_creds: MagicMock, mock_jira_class: MagicMock
    ) -> None:
        """Test that environment variables take precedence over .netrc."""
        mock_get_netrc_creds.return_value = ("netrc@example.com", "netrc_token")

        client = JiraClient(base_url="https://example.atlassian.net")

        assert client.email == "env@example.com"
        assert client.api_token == "env_token"
        # netrc should not be called since env vars are present
        mock_get_netrc_creds.assert_not_called()

    @patch("mouc.jira_client.Jira")
    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    @patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com"}, clear=True)
    def test_netrc_fills_missing_credential(
        self, mock_get_netrc_creds: MagicMock, mock_jira_class: MagicMock
    ) -> None:
        """Test that .netrc can fill in missing credentials when env has partial credentials."""
        mock_get_netrc_creds.return_value = ("netrc@example.com", "netrc_token")

        client = JiraClient(base_url="https://example.atlassian.net")

        # Email from env, token from netrc
        assert client.email == "env@example.com"
        assert client.api_token == "netrc_token"
        mock_get_netrc_creds.assert_called_once()

    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    @patch.dict("os.environ", {}, clear=True)
    def test_error_when_no_credentials_found(self, mock_get_netrc_creds: MagicMock) -> None:
        """Test that JiraAuthError is raised when no credentials are found anywhere."""
        mock_get_netrc_creds.return_value = (None, None)

        with pytest.raises(
            JiraAuthError,
            match="Jira credentials not found. Set JIRA_EMAIL and JIRA_API_TOKEN environment "
            "variables or add credentials to ~/.netrc file.",
        ):
            JiraClient(base_url="https://example.atlassian.net")

    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    @patch.dict("os.environ", {"JIRA_EMAIL": "env@example.com"}, clear=True)
    def test_error_when_only_email_found(self, mock_get_netrc_creds: MagicMock) -> None:
        """Test that JiraAuthError is raised when only email is found."""
        mock_get_netrc_creds.return_value = (None, None)

        with pytest.raises(JiraAuthError):
            JiraClient(base_url="https://example.atlassian.net")

    @patch("mouc.jira_client.get_jira_credentials_from_netrc")
    @patch.dict("os.environ", {"JIRA_API_TOKEN": "env_token"}, clear=True)
    def test_error_when_only_token_found(self, mock_get_netrc_creds: MagicMock) -> None:
        """Test that JiraAuthError is raised when only token is found."""
        mock_get_netrc_creds.return_value = (None, None)

        with pytest.raises(JiraAuthError):
            JiraClient(base_url="https://example.atlassian.net")

    @patch("mouc.jira_client.Jira")
    def test_base_url_trailing_slash_removed(self, mock_jira_class: MagicMock) -> None:
        """Test that trailing slash is removed from base_url."""
        client = JiraClient(
            base_url="https://example.atlassian.net/",
            email="user@example.com",
            api_token="token",
        )

        assert client.base_url == "https://example.atlassian.net"
        mock_jira_class.assert_called_once_with(
            url="https://example.atlassian.net",
            username="user@example.com",
            password="token",
            cloud=True,
        )
