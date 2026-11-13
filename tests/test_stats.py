"""
Tests for download statistics aggregation and JSON formatting.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from release_mirror.config import MirrorConfig
from release_mirror.stats import ReleaseStatsAggregator


class TestReleaseStatsAggregator(unittest.TestCase):

    def setUp(self):
        self.config = MirrorConfig.from_env()
        self.mock_client = MagicMock()
        self.aggregator = ReleaseStatsAggregator(self.config, client=self.mock_client)

    def test_aggregate_empty_releases(self):
        self.mock_client.list_all_releases.return_value = []
        stats = self.aggregator.generate_stats(use_cache=False)

        self.assertEqual(stats["totals"]["releases"], 0)
        self.assertEqual(stats["totals"]["iso_downloads"], 0)
        self.assertEqual(stats["totals"]["asset_downloads"], 0)
        self.assertEqual(len(stats["releases"]), 0)

    def test_aggregate_releases_metrics(self):
        self.mock_client.list_all_releases.return_value = [
            {
                "tag_name": "v2026.11.13",
                "name": "Snigdha OS Decentralized 2026.11.13",
                "prerelease": False,
                "draft": False,
                "published_at": "2026-11-13T10:00:00Z",
                "assets": [
                    {"name": "snigdhaos.iso", "size": 1500000000, "download_count": 500},
                    {"name": "SHA256SUMS", "size": 500, "download_count": 100},
                    {"name": "snigdhaos.iso.sig", "size": 800, "download_count": 100},
                ]
            },
            {
                "tag_name": "v2026.11.13-rc1",
                "name": "Snigdha OS Decentralized 2026.11.13-rc1",
                "prerelease": True,
                "draft": False,
                "published_at": "2026-11-12T10:00:00Z",
                "assets": [
                    {"name": "snigdhaos-rc1.iso", "size": 1500000000, "download_count": 200},
                    {"name": "SHA256SUMS", "size": 500, "download_count": 50},
                ]
            },
            {
                # Draft release should be excluded from public statistics
                "tag_name": "v2026.11.14-draft",
                "name": "Draft release",
                "prerelease": False,
                "draft": True,
                "assets": [
                    {"name": "draft.iso", "download_count": 10}
                ]
            }
        ]

        stats = self.aggregator.generate_stats(use_cache=False)

        # Totals
        totals = stats["totals"]
        self.assertEqual(totals["releases"], 2)
        self.assertEqual(totals["stable_releases"], 1)
        self.assertEqual(totals["prereleases"], 1)

        # ISO downloads: 500 (stable) + 200 (rc1) = 700
        self.assertEqual(totals["iso_downloads"], 700)
        self.assertEqual(totals["stable_iso_downloads"], 500)
        self.assertEqual(totals["prerelease_iso_downloads"], 200)

        # Total asset downloads: (500+100+100) + (200+50) = 700 + 250 = 950
        self.assertEqual(totals["asset_downloads"], 950)
        self.assertEqual(totals["stable_asset_downloads"], 700)
        self.assertEqual(totals["prerelease_asset_downloads"], 250)

        # Latest
        self.assertEqual(stats["latest"]["tag"], "v2026.11.13")
        self.assertEqual(stats["latest"]["version"], "2026.11.13")
        self.assertEqual(stats["latest"]["iso_downloads"], 500)

    def test_write_stats_json(self):
        self.mock_client.list_all_releases.return_value = []
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            out_path = tf.name

        try:
            self.aggregator.write_stats_json(out_path)
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("repository", data)
            self.assertIn("totals", data)
            self.assertIn("releases", data)
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)


if __name__ == "__main__":
    unittest.main()
