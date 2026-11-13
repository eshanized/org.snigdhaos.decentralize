"""
Custom exceptions for the release mirroring system.
SPDX-License-Identifier: GPL-3.0-or-later
"""

class MirrorError(Exception):
    """Base exception for all release mirror errors."""
    pass


class ConfigurationError(MirrorError):
    """Raised when environment or parameter configuration is invalid or missing."""
    pass


class GitLabAPIError(MirrorError):
    """Raised on GitLab API communication failures or non-2xx responses."""
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(f"GitLab API Error [{status_code}]: {message}")
        self.status_code = status_code
        self.response_body = response_body


class GitHubAPIError(MirrorError):
    """Raised on GitHub API communication failures or non-2xx responses."""
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(f"GitHub API Error [{status_code}]: {message}")
        self.status_code = status_code
        self.response_body = response_body


class VerificationError(MirrorError):
    """Base exception for cryptographic verification failures."""
    pass


class ChecksumMismatchError(VerificationError):
    """Raised when computed SHA-256 or BLAKE2b digest does not match manifest."""
    pass


class SignatureVerificationError(VerificationError):
    """Raised when OpenPGP / GPG signature check fails."""
    pass


class UntrustedKeyError(VerificationError):
    """Raised when the key fingerprint does not match the configured trusted fingerprint."""
    pass


class AssetOversizedError(MirrorError):
    """Raised when an asset exceeds the target platform's upload size limit."""
    pass


class ReleaseImmutableMutationError(MirrorError):
    """Raised when an existing published release differs in asset digest or content."""
    pass


class DiskSpaceError(MirrorError):
    """Raised when available disk space is insufficient for transfer operations."""
    pass
