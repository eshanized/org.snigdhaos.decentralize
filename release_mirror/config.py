"""
Configuration management for automated release mirroring.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class MirrorConfig:
    """Centralized configuration for GitLab -> GitHub release synchronization."""

    # Target GitHub repository configuration
    github_repository: str
    github_token: str

    # Source GitLab repository configuration
    gitlab_project: str
    gitlab_host: str
    gitlab_token: Optional[str]

    # Cryptographic trust configuration
    trusted_signing_key_fingerprint: str

    # Limits and thresholds
    max_asset_size_bytes: int
    min_free_disk_bytes: int
    chunk_size_bytes: int
    timeout_seconds: int
    max_retries: int
    backoff_factor: float

    # Directory settings
    temp_dir: Optional[str]

    @classmethod
    def from_env(cls) -> "MirrorConfig":
        """Load configuration from environment variables with safe defaults."""
        github_repo = os.environ.get(
            "GITHUB_RELEASE_REPOSITORY",
            os.environ.get("GITHUB_REPOSITORY", "eshanized/org.snigdhaos.decentralize")
        ).strip()

        github_token = os.environ.get(
            "GITHUB_RELEASE_TOKEN",
            os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
        ).strip()

        gitlab_project = os.environ.get(
            "GITLAB_RELEASE_PROJECT",
            os.environ.get("CI_PROJECT_PATH", "SnigdhaOS/decentralize/iso")
        ).strip()

        gitlab_host = os.environ.get(
            "GITLAB_HOST",
            os.environ.get("CI_SERVER_HOST", "gitlab.com")
        ).strip()

        gitlab_token = os.environ.get(
            "GITLAB_RELEASE_TOKEN",
            os.environ.get("GITLAB_TOKEN", os.environ.get("CI_JOB_TOKEN", ""))
        ).strip() or None

        # Canonical release signing key fingerprint (dev & production)
        # 2BDB 00AE 6CAB EF0E 4052 0A8F 553F D42B 02A8 211A
        trusted_fpr = os.environ.get(
            "TRUSTED_SIGNING_KEY_FINGERPRINT",
            "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A"
        ).replace(" ", "").upper().strip()

        # GitHub release asset individual file limit: 2 GiB (2 * 1024 * 1024 * 1024 bytes)
        max_asset_size = int(os.environ.get(
            "MAX_ASSET_SIZE_BYTES",
            str(2 * 1024 * 1024 * 1024)
        ))

        # Minimum required free disk space in working directory (default: 5 GiB)
        min_free_disk = int(os.environ.get(
            "MIN_FREE_DISK_BYTES",
            str(5 * 1024 * 1024 * 1024)
        ))

        chunk_size = int(os.environ.get("CHUNK_SIZE_BYTES", str(8 * 1024 * 1024))) # 8 MiB
        timeout = int(os.environ.get("TIMEOUT_SECONDS", "300"))
        max_retries = int(os.environ.get("MAX_RETRIES", "5"))
        backoff = float(os.environ.get("BACKOFF_FACTOR", "1.5"))
        temp_dir = os.environ.get("MIRROR_TEMP_DIR", None)

        return cls(
            github_repository=github_repo,
            github_token=github_token,
            gitlab_project=gitlab_project,
            gitlab_host=gitlab_host,
            gitlab_token=gitlab_token,
            trusted_signing_key_fingerprint=trusted_fpr,
            max_asset_size_bytes=max_asset_size,
            min_free_disk_bytes=min_free_disk,
            chunk_size_bytes=chunk_size,
            timeout_seconds=timeout,
            max_retries=max_retries,
            backoff_factor=backoff,
            temp_dir=temp_dir,
        )

    def mask_secrets(self, text: str) -> str:
        """Sanitize sensitive credentials from strings, logs, and error outputs."""
        if not text:
            return text
        sanitized = text
        if self.github_token and len(self.github_token) > 4:
            sanitized = sanitized.replace(self.github_token, "***REDACTED_GITHUB_TOKEN***")
        if self.gitlab_token and len(self.gitlab_token) > 4:
            sanitized = sanitized.replace(self.gitlab_token, "***REDACTED_GITLAB_TOKEN***")
        # Mask any Authorization headers or tokens matching common patterns
        sanitized = re.sub(r'(Bearer\s+|token\s+|ghp_|gho_|glpat-)[A-Za-z0-9_\-\.]{10,}', r'\1***REDACTED***', sanitized)
        return sanitized
