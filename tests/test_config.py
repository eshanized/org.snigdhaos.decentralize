"""
Tests for centralized configuration and secret sanitization.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import unittest
from release_mirror.config import MirrorConfig


class TestMirrorConfig(unittest.TestCase):

    def test_default_config(self):
        config = MirrorConfig.from_env()
        self.assertEqual(config.github_repository, "eshanized/org.snigdhaos.decentralize")
        self.assertEqual(config.gitlab_project, "SnigdhaOS/decentralize/iso")
        self.assertEqual(config.trusted_signing_key_fingerprint, "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A")
        self.assertEqual(config.max_asset_size_bytes, 2 * 1024 * 1024 * 1024)

    def test_env_override(self):
        os.environ["GITHUB_RELEASE_REPOSITORY"] = "custom/repo"
        os.environ["GITHUB_RELEASE_TOKEN"] = "secret_gh_token_12345"
        try:
            config = MirrorConfig.from_env()
            self.assertEqual(config.github_repository, "custom/repo")
            self.assertEqual(config.github_token, "secret_gh_token_12345")
        finally:
            del os.environ["GITHUB_RELEASE_REPOSITORY"]
            del os.environ["GITHUB_RELEASE_TOKEN"]

    def test_mask_secrets(self):
        config = MirrorConfig.from_env()
        config.github_token = "ghp_mySuperSecretToken123456789"
        config.gitlab_token = "glpat-anotherSecretToken987654321"

        error_message = (
            "Failed request with token ghp_mySuperSecretToken123456789 and "
            "private token glpat-anotherSecretToken987654321 on host."
        )
        masked = config.mask_secrets(error_message)
        self.assertNotIn("ghp_mySuperSecretToken123456789", masked)
        self.assertNotIn("glpat-anotherSecretToken987654321", masked)
        self.assertIn("***REDACTED", masked)


if __name__ == "__main__":
    unittest.main()
