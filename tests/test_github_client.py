"""
Tests for GitHub client: release creation, asset upload limits, rate limiting, and pagination.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import AssetOversizedError, GitHubAPIError
from release_mirror.github_client import GitHubClient


class TestGitHubClient(unittest.TestCase):

    def setUp(self):
        self.config = MirrorConfig.from_env()
        self.config.github_token = "gh_test_token"
        self.client = GitHubClient(self.config)

    @patch("urllib.request.urlopen")
    def test_get_release_by_tag_found(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "id": 12345,
            "tag_name": "v2026.11.13-rc1",
            "name": "Snigdha OS Decentralized 2026.11.13-rc1",
            "draft": False,
            "prerelease": True,
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        release = self.client.get_release_by_tag("v2026.11.13-rc1")
        self.assertIsNotNone(release)
        self.assertEqual(release["id"], 12345)
        self.assertEqual(release["tag_name"], "v2026.11.13-rc1")

    @patch("urllib.request.urlopen")
    def test_get_release_by_tag_not_found_returns_none(self, mock_urlopen):
        err_404 = urllib.error.HTTPError("url", 404, "Not Found", {}, io.BytesIO(b'{"message": "Not Found"}'))
        mock_urlopen.side_effect = err_404

        release = self.client.get_release_by_tag("v9999.99.99")
        self.assertIsNone(release)

    @patch("urllib.request.urlopen")
    def test_create_release(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.read.return_value = json.dumps({
            "id": 54321,
            "tag_name": "v2026.11.13",
            "draft": True,
            "prerelease": False,
            "upload_url": "https://uploads.github.com/repos/eshanized/org.snigdhaos.decentralize/releases/54321/assets{?name,label}",
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        new_rel = self.client.create_release(
            tag_name="v2026.11.13",
            name="Snigdha OS Decentralized 2026.11.13",
            body="Official stable release notes",
            draft=True,
            prerelease=False,
        )
        self.assertEqual(new_rel["id"], 54321)
        self.assertTrue(new_rel["draft"])

    @patch("urllib.request.urlopen")
    def test_update_release(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "id": 54321,
            "draft": False,
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        updated = self.client.update_release(54321, draft=False)
        self.assertFalse(updated["draft"])

    def test_asset_size_limit_rejection(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf_path = tf.name

        try:
            # Set max size to 10 bytes and write 20 bytes
            self.config.max_asset_size_bytes = 10
            with open(tf_path, "wb") as f:
                f.write(b"01234567890123456789") # 20 bytes

            with self.assertRaises(AssetOversizedError):
                self.client.upload_release_asset("https://uploads.github.com/assets", tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("urllib.request.urlopen")
    def test_upload_release_asset_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.read.return_value = json.dumps({
            "id": 999,
            "name": "test.iso",
            "size": 100,
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"sample bytes" * 10)
            tf_path = tf.name

        try:
            res = self.client.upload_release_asset(
                "https://uploads.github.com/repos/owner/repo/releases/1/assets{?name,label}",
                tf_path,
                asset_name="test.iso"
            )
            self.assertEqual(res["id"], 999)
            self.assertEqual(res["name"], "test.iso")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("urllib.request.urlopen")
    def test_pagination_via_link_header(self, mock_urlopen):
        # Page 1 response with Link header
        resp1 = MagicMock()
        resp1.status = 200
        resp1.read.return_value = json.dumps([{"id": 1}, {"id": 2}]).encode("utf-8")
        resp1.headers = {"Link": '<https://api.github.com/repos/owner/repo/releases?per_page=100&page=2>; rel="next"'}
        resp1.__enter__.return_value = resp1

        # Page 2 response without Link header
        resp2 = MagicMock()
        resp2.status = 200
        resp2.read.return_value = json.dumps([{"id": 3}]).encode("utf-8")
        resp2.headers = {}
        resp2.__enter__.return_value = resp2

        mock_urlopen.side_effect = [resp1, resp2]

        all_releases = self.client.list_all_releases()
        self.assertEqual(len(all_releases), 3)
        self.assertEqual([r["id"] for r in all_releases], [1, 2, 3])

    @patch("urllib.request.urlopen")
    def test_rate_limit_handling(self, mock_urlopen):
        err_rate = urllib.error.HTTPError(
            "url", 403, "rate limit exceeded",
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1000"},
            io.BytesIO(b'{"message": "API rate limit exceeded"}')
        )
        resp_success = MagicMock()
        resp_success.status = 200
        resp_success.read.return_value = b'{"id": 10}'
        resp_success.__enter__.return_value = resp_success

        mock_urlopen.side_effect = [err_rate, resp_success]

        with patch("time.sleep", return_value=None), patch("time.time", return_value=990):
            res = self.client._request("GET", "releases/10")
            self.assertEqual(res, {"id": 10})


if __name__ == "__main__":
    unittest.main()
