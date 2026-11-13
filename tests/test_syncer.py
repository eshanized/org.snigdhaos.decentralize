"""
Tests for release synchronizer: idempotency, partial recovery, and release note enrichment.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import VerificationError
from release_mirror.syncer import ReleaseSyncer


class TestReleaseSyncer(unittest.TestCase):

    def setUp(self):
        self.config = MirrorConfig.from_env()
        self.mock_gitlab = MagicMock()
        self.mock_github = MagicMock()
        self.mock_verifier = MagicMock()
        self.syncer = ReleaseSyncer(
            self.config,
            gitlab_client=self.mock_gitlab,
            github_client=self.mock_github,
            verifier=self.mock_verifier,
        )

    def test_idempotent_already_mirrored_returns_early(self):
        # GitLab has 2 assets
        self.mock_gitlab.get_release.return_value = {
            "tag_name": "v2026.11.13-rc1",
            "name": "Snigdha OS Decentralized 2026.11.13-rc1",
            "assets": {
                "links": [
                    {"name": "snigdhaos.iso", "url": "https://gitlab.com/iso"},
                    {"name": "SHA256SUMS", "url": "https://gitlab.com/sums"},
                ]
            }
        }
        # GitHub already has release published with both assets matching
        self.mock_github.get_release_by_tag.return_value = {
            "id": 1001,
            "draft": False,
            "html_url": "https://github.com/eshanized/org.snigdhaos.decentralize/releases/tag/v2026.11.13-rc1",
        }
        self.mock_github.get_release_assets.return_value = [
            {"name": "snigdhaos.iso", "size": 1000},
            {"name": "SHA256SUMS", "size": 200},
        ]

        res = self.syncer.sync_release("v2026.11.13-rc1")
        self.assertEqual(res["status"], "already_mirrored")
        self.assertEqual(res["release_id"], 1001)

        # Ensure no uploads were attempted
        self.mock_github.upload_release_asset.assert_not_called()

    def test_dry_run_does_not_mutate(self):
        self.mock_gitlab.get_release.return_value = {
            "tag_name": "v2026.11.13",
            "name": "Snigdha OS Decentralized 2026.11.13",
            "assets": {
                "links": [
                    {"name": "snigdhaos.iso", "url": "https://gitlab.com/iso"}
                ]
            }
        }
        self.mock_github.get_release_by_tag.return_value = None

        res = self.syncer.sync_release("v2026.11.13", dry_run=True)
        self.assertEqual(res["status"], "dry_run")
        self.mock_github.create_release.assert_not_called()
        self.mock_github.upload_release_asset.assert_not_called()

    def test_format_gitlab_description_enrichment(self):
        original = (
            "## Snigdha OS Decentralized 2026.11.13-rc1\n\n"
            "Initial candidate release notes.\n\n"
            "### Verification\n\n"
            "sha256sum -c SHA256SUMS\n"
        )
        enriched = self.syncer.format_gitlab_description_with_downloads(
            original, "v2026.11.13-rc1", "snigdhaos-2026.11.13.iso"
        )

        self.assertIn("## Downloads", enriched)
        self.assertIn("Download ISO from GitHub", enriched)
        self.assertIn("https://github.com/eshanized/org.snigdhaos.decentralize/releases/download/v2026.11.13-rc1/snigdhaos-2026.11.13.iso", enriched)
        self.assertIn("Initial candidate release notes.", enriched)
        self.assertIn("### Verification", enriched)


if __name__ == "__main__":
    unittest.main()
