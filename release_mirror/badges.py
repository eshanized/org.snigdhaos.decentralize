"""
Badge generation for Snigdha OS Decentralized download statistics.
Produces both Shields.io endpoint JSON and standalone SVG badges.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("release_mirror.badges")


def format_count(count: int) -> str:
    """Format large integers cleanly (e.g., 1200 -> 1.2k, 1250000 -> 1.25M)."""
    if count >= 1_000_000:
        val = count / 1_000_000
        return f"{val:.2f}".rstrip("0").rstrip(".") + "M"
    elif count >= 1_000:
        val = count / 1_000
        return f"{val:.1f}".rstrip("0").rstrip(".") + "k"
    return str(count)


def generate_svg_badge(label: str, message: str, color: str = "#007ec6") -> str:
    """Render a standalone flat SVG badge without external dependencies."""
    # Approximate width based on character counts
    char_width_label = 6.5
    char_width_message = 7.0
    padding = 12

    label_width = int(len(label) * char_width_label + padding)
    message_width = int(len(message) * char_width_message + padding)
    total_width = label_width + message_width
    height = 20

    label_x = label_width // 2
    message_x = label_width + (message_width // 2)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{height}" role="img" aria-label="{label}: {message}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="{height}" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="{height}" fill="#555"/>
    <rect x="{label_width}" width="{message_width}" height="{height}" fill="{color}"/>
    <rect width="{total_width}" height="{height}" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text aria-hidden="true" x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x}" y="14">{label}</text>
    <text aria-hidden="true" x="{message_x}" y="15" fill="#010101" fill-opacity=".3">{message}</text>
    <text x="{message_x}" y="14">{message}</text>
  </g>
</svg>"""


class BadgeGenerator:
    """Generates standard Shields JSON and SVG badges from release statistics."""

    def __init__(self, stats: Dict[str, Any]):
        self.stats = stats
        self.totals = stats.get("totals", {})
        self.latest = stats.get("latest", {})

    def get_badge_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Return dictionary of badge keys and their configuration."""
        iso_downloads = self.totals.get("iso_downloads", 0)
        total_downloads = self.totals.get("asset_downloads", 0)
        latest_downloads = self.latest.get("iso_downloads", 0)
        latest_version = self.latest.get("version", "unknown")

        return {
            "total-iso-downloads": {
                "label": "ISO downloads",
                "message": format_count(iso_downloads),
                "color": "#007ec6", # Blue
                "svg_color": "#007ec6",
            },
            "latest-release-downloads": {
                "label": "latest downloads",
                "message": format_count(latest_downloads),
                "color": "#4c1", # Bright green
                "svg_color": "#44cc11",
            },
            "total-downloads": {
                "label": "total downloads",
                "message": format_count(total_downloads),
                "color": "#97ca00", # Green
                "svg_color": "#97ca00",
            },
            "latest-version": {
                "label": "version",
                "message": latest_version,
                "color": "#fe7d37", # Orange
                "svg_color": "#fe7d37",
            },
        }

    def generate_all(self, output_dir: str) -> None:
        """Write JSON endpoints and SVG files for all badges to output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        badges = self.get_badge_definitions()

        for key, badge in badges.items():
            # 1. Write Shields.io endpoint schema JSON
            shields_data = {
                "schemaVersion": 1,
                "label": badge["label"],
                "message": badge["message"],
                "color": badge["color"],
            }
            json_path = os.path.join(output_dir, f"{key}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(shields_data, f, indent=2)

            # 2. Write SVG badge
            svg_content = generate_svg_badge(
                label=badge["label"],
                message=badge["message"],
                color=badge["svg_color"]
            )
            svg_path = os.path.join(output_dir, f"{key}.svg")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            logger.info("Generated badge: %s (.json & .svg)", key)
