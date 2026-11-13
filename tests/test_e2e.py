"""
End-to-end integration test of the release mirroring pipeline using simulated small test assets.
Validates the entire synchronization workflow without touching production artifacts.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from release_mirror.badges import BadgeGenerator
from release_mirror.config import MirrorConfig
from release_mirror.github_client import GitHubClient
from release_mirror.gitlab_client import GitLabClient
from release_mirror.stats import ReleaseStatsAggregator
from release_mirror.syncer import ReleaseSyncer
from release_mirror.verifier import CryptographicVerifier


class TestEndToEndReleaseMirroring(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="e2e_mirror_test_")
        self.config = MirrorConfig.from_env()
        self.config.temp_dir = self.temp_dir
        self.config.trusted_signing_key_fingerprint = "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A"
        self.config.github_token = "mock_gh_token"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_mirroring_lifecycle_with_test_assets(self):
        """Simulate end-to-end execution of a release mirror with mock small assets."""
        test_tag = "v2026.11.13-test1"

        # 1. Create simulated small release assets
        assets_dir = os.path.join(self.temp_dir, "gl_assets")
        os.makedirs(assets_dir, exist_ok=True)

        iso_content = b"Simulated minimal Snigdha OS ISO image (1024 bytes test payload)\n" * 16
        iso_sha256 = hashlib.sha256(iso_content).hexdigest()
        iso_file = os.path.join(assets_dir, "snigdhaos-test-2026.11.13-x86_64.iso")
        with open(iso_file, "wb") as f:
            f.write(iso_content)

        manifest_content = f"{iso_sha256}  snigdhaos-test-2026.11.13-x86_64.iso\n"
        manifest_file = os.path.join(assets_dir, "SHA256SUMS")
        with open(manifest_file, "w", encoding="utf-8") as f:
            f.write(manifest_content)

        sig_files = ["SHA256SUMS.sig", "snigdhaos-test-2026.11.13-x86_64.iso.sig", "release-signing-key.asc"]
        for s in sig_files:
            with open(os.path.join(assets_dir, s), "w", encoding="utf-8") as f:
                f.write(f"-----BEGIN PGP SIGNATURE-----\nMock signature for {s}\n-----END PGP SIGNATURE-----\n")

        # 2. Mock GitLab Client
        mock_gitlab = MagicMock(spec=GitLabClient)
        mock_gitlab.get_release.return_value = {
            "tag_name": test_tag,
            "name": f"Snigdha OS Decentralized {test_tag}",
            "description": "Initial test release notes",
            "upcoming_release": False,
            "assets": {
                "links": [
                    {"name": os.path.basename(iso_file), "url": f"mock://{os.path.basename(iso_file)}"},
                    {"name": "SHA256SUMS", "url": "mock://SHA256SUMS"},
                    {"name": "SHA256SUMS.sig", "url": "mock://SHA256SUMS.sig"},
                    {"name": "snigdhaos-test-2026.11.13-x86_64.iso.sig", "url": "mock://iso.sig"},
                    {"name": "release-signing-key.asc", "url": "mock://key.asc"},
                ]
            }
        }

        def mock_download(url, dest, **kwargs):
            fname = os.path.basename(dest)
            src = os.path.join(assets_dir, fname)
            shutil.copyfile(src, dest)
            with open(dest, "rb") as f:
                c = f.read()
            return hashlib.sha256(c).hexdigest(), hashlib.blake2b(c).hexdigest(), len(c)

        mock_gitlab.download_asset.side_effect = mock_download

        # 3. Mock GitHub Client
        mock_github = MagicMock(spec=GitHubClient)
        # First check returns None (release not created yet)
        mock_github.get_release_by_tag.return_value = None

        created_release_id = 998877
        mock_github.create_release.return_value = {
            "id": created_release_id,
            "tag_name": test_tag,
            "name": f"Snigdha OS Decentralized {test_tag}",
            "draft": True,
            "upload_url": "https://uploads.github.com/mock/assets{?name,label}",
        }

        # Track uploaded assets
        uploaded_assets = []
        def mock_upload(upload_url_template, file_path, asset_name=None, **kwargs):
            name = asset_name or os.path.basename(file_path)
            size = os.path.getsize(file_path)
            asset_obj = {"id": len(uploaded_assets) + 1, "name": name, "size": size, "download_count": 0}
            uploaded_assets.append(asset_obj)
            return asset_obj

        mock_github.upload_release_asset.side_effect = mock_upload
        mock_github.get_release_assets.side_effect = lambda rel_id: list(uploaded_assets)
        mock_github.update_release.return_value = {
            "id": created_release_id,
            "tag_name": test_tag,
            "draft": False,
            "html_url": f"https://github.com/eshanized/org.snigdhaos.decentralize/releases/tag/{test_tag}",
        }

        # 4. Mock Cryptographic Verifier internals
        mock_verifier = MagicMock(spec=CryptographicVerifier)
        mock_verifier.verify_release_bundle.return_value = {
            os.path.basename(iso_file): iso_sha256,
        }

        # 5. Run Syncer
        syncer = ReleaseSyncer(
            self.config,
            gitlab_client=mock_gitlab,
            github_client=mock_github,
            verifier=mock_verifier,
        )

        result = syncer.sync_release(test_tag, dry_run=False, update_gitlab_notes=True)

        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["tag"], test_tag)
        self.assertEqual(result["release_id"], created_release_id)
        self.assertEqual(result["assets_mirrored"], 5)

        # Verify GitHub release was created with draft=True first, then updated to draft=False
        mock_github.create_release.assert_called_once()
        self.assertTrue(mock_github.create_release.call_args[1]["draft"])
        mock_github.update_release.assert_called_once()
        self.assertFalse(mock_github.update_release.call_args[1]["draft"])

        # Verify GitLab release description was updated with downloads section
        mock_gitlab.update_release_description.assert_called_once()
        updated_desc = mock_gitlab.update_release_description.call_args[0][1]
        self.assertIn("## Downloads", updated_desc)
        self.assertIn("Download ISO from GitHub", updated_desc)

        # 6. Verify stats aggregation on the mirrored release
        mock_github.list_all_releases.return_value = [
            {
                "tag_name": test_tag,
                "name": f"Snigdha OS Decentralized {test_tag}",
                "prerelease": True,
                "draft": False,
                "published_at": "2026-11-13T12:00:00Z",
                "assets": [
                    {"name": os.path.basename(iso_file), "size": len(iso_content), "download_count": 42},
                    {"name": "SHA256SUMS", "size": len(manifest_content), "download_count": 10},
                ]
            }
        ]
        stats_agg = ReleaseStatsAggregator(self.config, client=mock_github)
        stats = stats_agg.generate_stats(use_cache=False)

        self.assertEqual(stats["totals"]["releases"], 1)
        self.assertEqual(stats["totals"]["iso_downloads"], 42)
        self.assertEqual(stats["totals"]["asset_downloads"], 52)
        self.assertEqual(stats["latest"]["tag"], test_tag)

        # 7. Generate Badges from stats
        badge_gen = BadgeGenerator(stats)
        badges_dir = os.path.join(self.temp_dir, "badges")
        badge_gen.generate_all(badges_dir)

        self.assertTrue(os.path.isfile(os.path.join(badges_dir, "total-iso-downloads.svg")))
        self.assertTrue(os.path.isfile(os.path.join(badges_dir, "total-iso-downloads.json")))

        with open(os.path.join(badges_dir, "total-iso-downloads.json"), "r") as f:
            b_data = json.load(f)
            self.assertEqual(b_data["message"], "42")


if __name__ == "__main__":
    unittest.main()
