"""Unit tests for auth module.

Tests authentication with mocked STS: success, timeout, and credential failure.

Requirements: 2.1–2.6
"""

from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

from aws_cost_analytics.auth import AuthError, AuthModule, AuthResult


class TestAuthModuleSuccess:
    """Test successful authentication flow (Reqs 2.1, 2.2, 2.3, 2.4)."""

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_successful_auth_with_explicit_region(self, mock_session_cls):
        """Auth returns account ID and session scoped to configured region."""
        mock_session = MagicMock()
        mock_session.region_name = "us-west-2"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/test",
            "UserId": "AIDEXAMPLE",
        }
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-west-2")
        result = auth.get_credentials()

        assert isinstance(result, AuthResult)
        assert result.account_id == "123456789012"
        assert result.session == mock_session
        mock_session_cls.assert_called_with(region_name="us-west-2")

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_successful_auth_with_empty_region_uses_session_default(self, mock_session_cls):
        """When region is empty, uses session's default region (Req 2.4)."""
        mock_session = MagicMock()
        mock_session.region_name = "eu-west-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.return_value = {
            "Account": "987654321098",
            "Arn": "arn:aws:iam::987654321098:user/test",
            "UserId": "AIDEXAMPLE",
        }
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="")
        result = auth.get_credentials()

        assert result.account_id == "987654321098"
        # First call with region_name=None (empty string -> None)
        mock_session_cls.assert_any_call(region_name=None)

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_successful_auth_falls_back_to_us_east_1(self, mock_session_cls):
        """When region empty and session has no region, falls back to us-east-1."""
        # First call: session with no region
        mock_session_no_region = MagicMock()
        mock_session_no_region.region_name = None

        # Second call: session with us-east-1 fallback
        mock_session_fallback = MagicMock()
        mock_session_fallback.region_name = "us-east-1"

        mock_session_cls.side_effect = [mock_session_no_region, mock_session_fallback]

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.return_value = {
            "Account": "111222333444",
            "Arn": "arn:aws:iam::111222333444:user/test",
            "UserId": "AIDEXAMPLE",
        }
        mock_session_fallback.client.return_value = mock_sts_client

        auth = AuthModule(region="")
        result = auth.get_credentials()

        assert result.account_id == "111222333444"
        # Should have created a second session with us-east-1
        mock_session_cls.assert_any_call(region_name="us-east-1")


class TestAuthModuleTimeout:
    """Test STS timeout handling (Req 2.6)."""

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_connect_timeout_raises_auth_error(self, mock_session_cls):
        """ConnectTimeoutError from STS raises AuthError with timeout indication."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = (
            botocore.exceptions.ConnectTimeoutError(endpoint_url="https://sts.amazonaws.com")
        )
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        assert "timeout" in str(exc_info.value).lower()

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_read_timeout_raises_auth_error(self, mock_session_cls):
        """ReadTimeoutError from STS raises AuthError with timeout indication."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = (
            botocore.exceptions.ReadTimeoutError(endpoint_url="https://sts.amazonaws.com")
        )
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        assert "timeout" in str(exc_info.value).lower()


class TestAuthModuleCredentialFailure:
    """Test credential resolution failure (Req 2.5)."""

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_no_credentials_on_sts_call(self, mock_session_cls):
        """NoCredentialsError during STS call raises AuthError."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = (
            botocore.exceptions.NoCredentialsError()
        )
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        error_msg = str(exc_info.value).lower()
        assert "credential" in error_msg

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_client_error_on_sts_call(self, mock_session_cls):
        """ClientError from STS raises AuthError indicating STS failure."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = botocore.exceptions.ClientError(
            error_response={"Error": {"Code": "AccessDenied", "Message": "Not allowed"}},
            operation_name="GetCallerIdentity",
        )
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        error_msg = str(exc_info.value)
        assert "AccessDenied" in error_msg or "failed" in error_msg.lower()

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_endpoint_connection_error(self, mock_session_cls):
        """EndpointConnectionError raises AuthError about connectivity."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.side_effect = (
            botocore.exceptions.EndpointConnectionError(endpoint_url="https://sts.amazonaws.com")
        )
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        error_msg = str(exc_info.value).lower()
        assert "connect" in error_msg or "endpoint" in error_msg

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_empty_account_id_raises_auth_error(self, mock_session_cls):
        """Empty account ID in STS response raises AuthError."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_sts_client = MagicMock()
        mock_sts_client.get_caller_identity.return_value = {
            "Account": "",
            "Arn": "",
            "UserId": "",
        }
        mock_session.client.return_value = mock_sts_client

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        assert "empty" in str(exc_info.value).lower() or "account" in str(exc_info.value).lower()

    @patch("aws_cost_analytics.auth.boto3.Session")
    def test_no_credentials_on_client_creation(self, mock_session_cls):
        """NoCredentialsError during client creation raises AuthError."""
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_session_cls.return_value = mock_session

        mock_session.client.side_effect = botocore.exceptions.NoCredentialsError()

        auth = AuthModule(region="us-east-1")

        with pytest.raises(AuthError) as exc_info:
            auth.get_credentials()

        assert "credential" in str(exc_info.value).lower()
