"""
Tests for badge generation and formatting.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import os
import tempfile
import unittest

from release_mirror.badges import BadgeGenerator, format_count, generate_svg_badge


class TestBadges(unittest.TestCase):

    def test_format_count(self):
        self.assertEqual(format_count(0), "0")
        self.assertEqual(format_count(999), "999")
        self.assertEqual(format_count(1000), "1k")
        self.assertEqual(format_count(1500), "1.5k")
        self.assertEqual(format_count(1000000), "1M")
        self.assertEqual(format_count(2500000), "2.5M")

    def test_generate_svg_badge(self):
        svg = generate_svg_badge("ISO downloads", "1.5k", color="#007ec6")
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)
        self.assertIn("ISO downloads", svg)
        self.assertIn("1.5k", svg)
        self.assertIn("#007ec6", svg)

    def test_badge_generator_all(self):
        stats = {
            "totals": {
                "iso_downloads": 1250,
                "asset_downloads": 4500,
                "releases": 3,
            },
            "latest": {
                "tag": "v2026.11.13",
                "version": "2026.11.13",
                "iso_downloads": 850,
            }
        }

        generator = BadgeGenerator(stats)
        temp_dir = tempfile.mkdtemp()

        try:
            generator.generate_all(temp_dir)
            expected_keys = [
                "total-iso-downloads",
                "latest-release-downloads",
                "total-downloads",
                "latest-version",
            ]
            for key in expected_keys:
                json_file = os.path.join(temp_dir, f"{key}.json")
                svg_file = os.path.join(temp_dir, f"{key}.svg")

                self.assertTrue(os.path.isfile(json_file), f"Missing {json_file}")
                self.assertTrue(os.path.isfile(svg_file), f"Missing {svg_file}")

                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.assertEqual(data["schemaVersion"], 1)
                    self.assertIn("label", data)
                    self.assertIn("message", data)
                    self.assertIn("color", data)

                with open(svg_file, "r", encoding="utf-8") as f:
                    svg_content = f.read()
                    self.assertTrue(svg_content.startswith("<svg"))
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
