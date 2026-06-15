"""Authentication and account resolution.

Resolves AWS credentials using the default boto3 credential chain
(AWS_PROFILE, environment variables, instance roles) and calls
STS GetCallerIdentity to obtain the active 12-digit account ID.

Returns an AuthResult containing the account ID and a boto3 Session
scoped to the configured region.
"""

from dataclasses import dataclass

import boto3
import botocore.config
import botocore.exceptions


class AuthError(Exception):
    """Raised when credential resolution or STS call fails."""

    pass


@dataclass
class AuthResult:
    """Result of successful authentication."""

    account_id: str
    session: boto3.Session


class AuthModule:
    """Resolves AWS credentials and retrieves the active account ID via STS."""

    def __init__(self, region: str) -> None:
        self._region = region

    def get_credentials(self) -> AuthResult:
        """Resolve credentials via default boto3 chain and call STS GetCallerIdentity.

        Region resolution logic:
        - If self._region is a non-empty string, use it directly.
        - If self._region is empty, use session.region_name.
        - If session.region_name is also None, fall back to "us-east-1".

        Returns:
            AuthResult with the 12-digit account ID and a boto3 Session
            scoped to the resolved region.

        Raises:
            AuthError: On credential resolution failure, STS call failure,
                or STS call timeout.
        """
        # Resolve region
        resolved_region = self._region if self._region else None

        try:
            session = boto3.Session(region_name=resolved_region)
        except Exception as e:
            raise AuthError(f"Failed to create boto3 session: {e}") from e

        # If region was empty and session didn't resolve one, fall back to us-east-1
        if not session.region_name:
            session = boto3.Session(region_name="us-east-1")

        # Configure STS client with connect_timeout=5, read_timeout=5 (10s total budget)
        sts_config = botocore.config.Config(
            connect_timeout=5,
            read_timeout=5,
        )

        try:
            sts_client = session.client("sts", config=sts_config)
        except botocore.exceptions.NoCredentialsError as e:
            raise AuthError(
                "Credential resolution failed: no AWS credentials found. "
                "Ensure AWS_PROFILE, environment variables, or instance role is configured."
            ) from e
        except Exception as e:
            raise AuthError(f"Failed to create STS client: {e}") from e

        # Call STS GetCallerIdentity
        try:
            response = sts_client.get_caller_identity()
        except botocore.exceptions.NoCredentialsError as e:
            raise AuthError(
                "Credential resolution failed: no AWS credentials found. "
                "Ensure AWS_PROFILE, environment variables, or instance role is configured."
            ) from e
        except botocore.exceptions.ConnectTimeoutError as e:
            raise AuthError(
                "STS GetCallerIdentity timed out: connection timeout exceeded (5s). "
                "Check network connectivity to the STS endpoint."
            ) from e
        except botocore.exceptions.ReadTimeoutError as e:
            raise AuthError(
                "STS GetCallerIdentity timed out: read timeout exceeded (5s). "
                "The STS service did not respond in time."
            ) from e
        except botocore.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", "Unknown error")
            raise AuthError(
                f"STS GetCallerIdentity call failed: {error_code} - {error_message}"
            ) from e
        except botocore.exceptions.EndpointConnectionError as e:
            raise AuthError(
                "STS GetCallerIdentity failed: unable to connect to STS endpoint. "
                "Check network connectivity and region configuration."
            ) from e
        except Exception as e:
            raise AuthError(
                f"STS GetCallerIdentity call failed: {e}"
            ) from e

        account_id = response.get("Account", "")
        if not account_id:
            raise AuthError(
                "STS GetCallerIdentity returned an empty account ID."
            )

        return AuthResult(account_id=account_id, session=session)
