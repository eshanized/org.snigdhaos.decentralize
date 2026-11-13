"""
Tests for command-line interface parsing and command dispatch.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from release_mirror.cli import main


class TestCLI(unittest.TestCase):

    def test_help_exits_cleanly(self):
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout"):
                main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    @patch("release_mirror.cli.ReleaseSyncer")
    def test_sync_command_dispatch(self, mock_syncer_cls):
        mock_instance = MagicMock()
        mock_instance.sync_release.return_value = {
            "status": "success",
            "tag": "v2026.11.13",
            "assets_mirrored": 5,
        }
        mock_syncer_cls.return_value = mock_instance

        ret = main(["sync", "--tag", "v2026.11.13", "--dry-run"])
        self.assertEqual(ret, 0)
        mock_instance.sync_release.assert_called_once_with(
            tag="v2026.11.13", dry_run=True, update_gitlab_notes=True
        )

    @patch("release_mirror.cli.ReleaseStatsAggregator")
    def test_stats_command_dispatch(self, mock_aggregator_cls):
        mock_instance = MagicMock()
        mock_instance.generate_stats.return_value = {
            "totals": {"iso_downloads": 100, "asset_downloads": 200, "releases": 1},
            "latest": {"tag": "v1.0", "iso_downloads": 100},
            "releases": []
        }
        mock_aggregator_cls.return_value = mock_instance

        ret = main(["stats", "--format", "json"])
        self.assertEqual(ret, 0)
        mock_instance.generate_stats.assert_called_once()

    @patch("release_mirror.cli.GitLabClient")
    @patch("release_mirror.cli.GitHubClient")
    def test_inspect_command_dispatch(self, mock_gh_cls, mock_gl_cls):
        mock_gl = MagicMock()
        mock_gl.get_release.return_value = {"tag_name": "v1.0", "name": "V1", "assets": {"links": []}}
        mock_gl_cls.return_value = mock_gl

        mock_gh = MagicMock()
        mock_gh.get_release_by_tag.return_value = None
        mock_gh_cls.return_value = mock_gh

        ret = main(["inspect", "--tag", "v1.0"])
        self.assertEqual(ret, 0)
        mock_gl.get_release.assert_called_once_with("v1.0")
        mock_gh.get_release_by_tag.assert_called_once_with("v1.0")


if __name__ == "__main__":
    unittest.main()
