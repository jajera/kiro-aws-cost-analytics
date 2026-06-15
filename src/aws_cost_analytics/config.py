"""Configuration loading and validation.

Loads config.json using pydantic for validation. Supports two fields:
- region: AWS region (validated against pattern [a-z]{2,4}-[a-z]+-\\d{1,2})
- cache_ttl_hours: Cache TTL in hours (1-168 inclusive, default 24)

If config.json is missing, operates with all default values.
Unrecognized fields are rejected with descriptive errors.
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


_REGION_PATTERN = re.compile(r"^[a-z]{2,4}-[a-z]+-\d{1,2}$")


class Config(BaseModel):
    """Configuration model for aws-cost-analytics."""

    model_config = ConfigDict(extra="forbid")

    region: str = ""
    cache_ttl_hours: int = 24

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        """Validate AWS region format if provided.

        Empty string is accepted (means "resolve from boto3/fallback to us-east-1").
        Non-empty strings must match the pattern [a-z]{2,4}-[a-z]+-\\d{1,2}.
        """
        if v == "":
            return v
        if not _REGION_PATTERN.match(v):
            raise ValueError(
                f"Invalid region format: '{v}'. "
                f"Must match pattern [a-z]{{2,4}}-[a-z]+-\\d{{1,2}} "
                f"(e.g., 'us-east-1', 'eu-west-2')"
            )
        return v

    @field_validator("cache_ttl_hours")
    @classmethod
    def validate_cache_ttl(cls, v: int) -> int:
        """Ensure 1 <= cache_ttl_hours <= 168."""
        if v < 1 or v > 168:
            raise ValueError(
                f"cache_ttl_hours must be between 1 and 168 inclusive, got {v}"
            )
        return v


def load_config(path: Path = Path("config.json")) -> Config:
    """Load config from JSON file, return defaults if file missing.

    Args:
        path: Path to the config.json file.

    Returns:
        Config instance with validated values.

    Raises:
        ConfigError: If the file contains malformed JSON or invalid values.
    """
    if not path.exists():
        return Config()

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Failed to read config file '{path}': {e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Failed to parse config file '{path}': malformed JSON - {e}"
        ) from e

    try:
        return Config(**data)
    except ValidationError as e:
        errors = e.errors()
        messages = []
        for error in errors:
            field = ".".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            error_type = error["type"]
            if error_type == "extra_forbidden":
                messages.append(f"Unrecognized field '{field}'")
            else:
                messages.append(f"Invalid value for '{field}': {msg}")
        raise ConfigError(
            f"Config validation failed: {'; '.join(messages)}"
        ) from e
