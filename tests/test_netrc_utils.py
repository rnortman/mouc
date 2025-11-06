"""Tests for netrc_utils module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from mouc.netrc_utils import get_jira_credentials_from_netrc


class TestGetJiraCredentialsFromNetrc:
    """Tests for get_jira_credentials_from_netrc function."""

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_valid_netrc_with_matching_machine(
        self, mock_home: MagicMock, mock_netrc_class: MagicMock
    ) -> None:
        """Test successful credential retrieval with matching machine."""
        # Setup mock
        mock_home.return_value = Path("/home/user")
        mock_netrc_instance = MagicMock()
        mock_netrc_instance.authenticators.return_value = (
            "user@example.com",
            None,
            "api_token_123",
        )
        mock_netrc_class.return_value = mock_netrc_instance

        # Test with .netrc file existence
        with patch.object(Path, "exists", return_value=True):
            login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        assert login == "user@example.com"
        assert password == "api_token_123"
        mock_netrc_instance.authenticators.assert_called_once_with("example.atlassian.net")

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_no_matching_machine(self, mock_home: MagicMock, mock_netrc_class: MagicMock) -> None:
        """Test when .netrc exists but has no matching machine entry."""
        mock_home.return_value = Path("/home/user")
        mock_netrc_instance = MagicMock()
        mock_netrc_instance.authenticators.return_value = None
        mock_netrc_class.return_value = mock_netrc_instance

        with patch.object(Path, "exists", return_value=True):
            login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        assert login is None
        assert password is None

    @patch("mouc.netrc_utils.Path.home")
    def test_missing_netrc_file(self, mock_home: MagicMock) -> None:
        """Test when .netrc file does not exist."""
        mock_home.return_value = Path("/home/user")

        with patch.object(Path, "exists", return_value=False):
            login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        assert login is None
        assert password is None

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_netrc_parse_error(self, mock_home: MagicMock, mock_netrc_class: MagicMock) -> None:
        """Test graceful handling of .netrc parse errors."""
        from netrc import NetrcParseError

        mock_home.return_value = Path("/home/user")
        mock_netrc_class.side_effect = NetrcParseError("Invalid format")

        with patch.object(Path, "exists", return_value=True):
            login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        assert login is None
        assert password is None

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_permission_error(self, mock_home: MagicMock, mock_netrc_class: MagicMock) -> None:
        """Test graceful handling of permission errors."""
        mock_home.return_value = Path("/home/user")
        mock_netrc_class.side_effect = OSError("Permission denied")

        with patch.object(Path, "exists", return_value=True):
            login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        assert login is None
        assert password is None

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_hostname_extraction_with_path(
        self, mock_home: MagicMock, mock_netrc_class: MagicMock
    ) -> None:
        """Test hostname extraction when URL includes path components."""
        mock_home.return_value = Path("/home/user")
        mock_netrc_instance = MagicMock()
        mock_netrc_instance.authenticators.return_value = ("user@example.com", None, "token")
        mock_netrc_class.return_value = mock_netrc_instance

        with patch.object(Path, "exists", return_value=True):
            get_jira_credentials_from_netrc("https://example.atlassian.net/browse/PROJECT-123")

        mock_netrc_instance.authenticators.assert_called_once_with("example.atlassian.net")

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    def test_hostname_extraction_without_scheme(
        self, mock_home: MagicMock, mock_netrc_class: MagicMock
    ) -> None:
        """Test hostname extraction when URL lacks scheme."""
        mock_home.return_value = Path("/home/user")
        mock_netrc_instance = MagicMock()
        mock_netrc_instance.authenticators.return_value = ("user@example.com", None, "token")
        mock_netrc_class.return_value = mock_netrc_instance

        with patch.object(Path, "exists", return_value=True):
            get_jira_credentials_from_netrc("example.atlassian.net")

        mock_netrc_instance.authenticators.assert_called_once_with("example.atlassian.net")

    @patch("mouc.netrc_utils.Path.home")
    def test_empty_hostname(self, mock_home: MagicMock) -> None:
        """Test handling of invalid URL that produces empty hostname."""
        mock_home.return_value = Path("/home/user")

        with patch.object(Path, "exists", return_value=True):
            login, password = get_jira_credentials_from_netrc("")

        assert login is None
        assert password is None

    @patch("mouc.netrc_utils.netrc.netrc")
    @patch("mouc.netrc_utils.Path.home")
    @patch("mouc.netrc_utils.os.name", "nt")
    def test_windows_netrc_path(self, mock_home: MagicMock, mock_netrc_class: MagicMock) -> None:
        """Test that _netrc is used on Windows."""
        # Create a mock Path that avoids WindowsPath instantiation issues
        mock_home_path = MagicMock()
        mock_netrc_path = MagicMock()
        mock_netrc_path.exists.return_value = True
        mock_home_path.__truediv__ = MagicMock(return_value=mock_netrc_path)
        mock_home.return_value = mock_home_path

        mock_netrc_instance = MagicMock()
        mock_netrc_instance.authenticators.return_value = ("user@example.com", None, "token")
        mock_netrc_class.return_value = mock_netrc_instance

        login, password = get_jira_credentials_from_netrc("https://example.atlassian.net")

        # Verify that Path.home() / "_netrc" was used for the netrc path
        # The actual path string passed to netrc.netrc() will be str(mock_netrc_path)
        assert login == "user@example.com"
        assert password == "token"
        # Verify authenticators was called
        mock_netrc_instance.authenticators.assert_called_once_with("example.atlassian.net")
