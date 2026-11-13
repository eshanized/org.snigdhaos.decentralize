"""
Tests for GitLab client: release discovery, pagination, retry logic, and downloads.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import GitLabAPIError
from release_mirror.gitlab_client import GitLabClient


class TestGitLabClient(unittest.TestCase):

    def setUp(self):
        self.config = MirrorConfig.from_env()
        self.client = GitLabClient(self.config)

    @patch("urllib.request.urlopen")
    def test_get_release(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_payload = {
            "tag_name": "v2026.11.13-rc1",
            "name": "Snigdha OS Decentralized 2026.11.13-rc1",
            "description": "Release notes",
            "assets": {
                "links": [
                    {"id": 1, "name": "snigdhaos.iso", "url": "https://gitlab.com/download/iso"}
                ]
            }
        }
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        release = self.client.get_release("v2026.11.13-rc1")
        self.assertEqual(release["tag_name"], "v2026.11.13-rc1")
        self.assertEqual(len(release["assets"]["links"]), 1)

    @patch("urllib.request.urlopen")
    def test_get_release_assets_discovery(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_payload = {
            "tag_name": "v2026.11.13",
            "assets": {
                "links": [
                    {"id": 101, "name": "SHA256SUMS", "url": "https://gitlab.com/files/SHA256SUMS"},
                    {"id": 102, "name": "SHA256SUMS.sig", "url": "https://gitlab.com/files/SHA256SUMS.sig"}
                ]
            }
        }
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        links = self.client.get_release_assets("v2026.11.13")
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0]["name"], "SHA256SUMS")

    @patch("urllib.request.urlopen")
    def test_pagination(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_payload = [{"tag_name": "v1.0"}, {"tag_name": "v2.0"}]
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        releases = self.client.list_releases(page=2, per_page=2)
        self.assertEqual(len(releases), 2)

    @patch("urllib.request.urlopen")
    def test_network_failure_retry(self, mock_urlopen):
        # Fail first with 502, then succeed with 200
        err_502 = urllib.error.HTTPError("url", 502, "Bad Gateway", {}, io.BytesIO(b"gateway error"))
        mock_success = MagicMock()
        mock_success.status = 200
        mock_success.read.return_value = b'{"status": "ok"}'
        mock_success.__enter__.return_value = mock_success

        mock_urlopen.side_effect = [err_502, mock_success]

        with patch("time.sleep", return_value=None):
            result = self.client.get_release("v2026.11.13")
            self.assertEqual(result, {"status": "ok"})
            self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_download_asset_streaming_and_digests(self, mock_urlopen):
        content = b"Mock ISO and binary payload data for Snigdha OS"
        mock_response = MagicMock()
        mock_response.read.side_effect = [content, b""]
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            dest = tf.name

        try:
            sha256, blake2b, size = self.client.download_asset("https://gitlab.com/file", dest)
            self.assertEqual(size, len(content))
            self.assertEqual(sha256, hashlib.sha256(content).hexdigest())
            self.assertEqual(blake2b, hashlib.blake2b(content).hexdigest())
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), content)
        finally:
            if os.path.exists(dest):
                os.remove(dest)

    @patch("urllib.request.urlopen")
    def test_update_release_description(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"tag_name": "v1.0", "description": "updated"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = self.client.update_release_description("v1.0", "updated")
        self.assertEqual(res["description"], "updated")


if __name__ == "__main__":
    unittest.main()
