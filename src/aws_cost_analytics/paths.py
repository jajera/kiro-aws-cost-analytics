"""Default filesystem paths for local cache storage."""

from pathlib import Path

CACHE_DIR_NAME = "aws-cost-analytics"
SERVICES_CACHE_FILENAME = "ce-services-bedrock.json"


def default_cache_dir() -> Path:
    """Return ~/.cache/aws-cost-analytics (created on first write)."""
    return Path.home() / ".cache" / CACHE_DIR_NAME


def services_cache_path(cache_dir: Path | None = None) -> Path:
    """Path to the Bedrock service discovery cache file."""
    return (cache_dir or default_cache_dir()) / SERVICES_CACHE_FILENAME
