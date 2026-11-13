"""
Public download statistics aggregation engine for Snigdha OS Decentralized.
Queries GitHub Releases REST API and computes authoritative download metrics.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional

from release_mirror.config import MirrorConfig
from release_mirror.github_client import GitHubClient

logger = logging.getLogger("release_mirror.stats")


class ReleaseStatsAggregator:
    """Aggregates and formats GitHub release download analytics."""

    def __init__(self, config: MirrorConfig, client: Optional[GitHubClient] = None):
        self.config = config
        self.client = client or GitHubClient(config)
        self._cached_data: Optional[Dict[str, Any]] = None
        self._cached_time: Optional[float] = None

    def fetch_releases(self, use_cache: bool = True, cache_ttl_seconds: int = 60) -> List[Dict[str, Any]]:
        """Fetch raw release list from GitHub API with optional caching."""
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if use_cache and self._cached_data and self._cached_time:
            if (now - self._cached_time) < cache_ttl_seconds:
                return self._cached_data.get("raw_releases", [])

        raw_releases = self.client.list_all_releases()
        self._cached_time = now
        if not self._cached_data:
            self._cached_data = {}
        self._cached_data["raw_releases"] = raw_releases
        return raw_releases

    def generate_stats(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Aggregate public GitHub release download metrics into standard schema.
        """
        raw_releases = self.fetch_releases(use_cache=use_cache)
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        total_iso_downloads = 0
        total_asset_downloads = 0
        total_prerelease_iso_downloads = 0
        total_stable_iso_downloads = 0
        total_prerelease_asset_downloads = 0
        total_stable_asset_downloads = 0

        parsed_releases: List[Dict[str, Any]] = []

        for rel in raw_releases:
            if rel.get("draft", False):
                # Omit drafts from public release download statistics
                continue

            tag = rel.get("tag_name", "")
            name = rel.get("name") or tag
            is_prerelease = bool(rel.get("prerelease", False) or "-rc" in tag.lower())
            published_at = rel.get("published_at") or rel.get("created_at") or ""
            html_url = rel.get("html_url", "")

            rel_iso_downloads = 0
            rel_asset_downloads = 0
            assets_summary: List[Dict[str, Any]] = []

            for asset in rel.get("assets", []):
                aname = asset.get("name", "")
                asize = asset.get("size", 0)
                acount = asset.get("download_count", 0)
                adownload_url = asset.get("browser_download_url", "")
                is_iso = aname.lower().endswith(".iso")

                if is_iso:
                    rel_iso_downloads += acount
                rel_asset_downloads += acount

                assets_summary.append({
                    "name": aname,
                    "size": asize,
                    "download_count": acount,
                    "browser_download_url": adownload_url,
                    "is_iso": is_iso,
                })

            total_iso_downloads += rel_iso_downloads
            total_asset_downloads += rel_asset_downloads

            if is_prerelease:
                total_prerelease_iso_downloads += rel_iso_downloads
                total_prerelease_asset_downloads += rel_asset_downloads
            else:
                total_stable_iso_downloads += rel_iso_downloads
                total_stable_asset_downloads += rel_asset_downloads

            parsed_releases.append({
                "tag": tag,
                "name": name,
                "prerelease": is_prerelease,
                "published_at": published_at,
                "html_url": html_url,
                "iso_downloads": rel_iso_downloads,
                "asset_downloads": rel_asset_downloads,
                "assets": assets_summary,
            })

        latest_release_tag = ""
        latest_release_downloads = 0
        latest_version = ""
        if parsed_releases:
            # First release is the latest published release from GitHub
            latest_rel = parsed_releases[0]
            latest_release_tag = latest_rel["tag"]
            latest_version = latest_rel["tag"].lstrip("v")
            latest_release_downloads = latest_rel["iso_downloads"]

        stats = {
            "repository": self.config.github_repository,
            "generated_at": now_iso,
            "totals": {
                "iso_downloads": total_iso_downloads,
                "asset_downloads": total_asset_downloads,
                "releases": len(parsed_releases),
                "stable_releases": len([r for r in parsed_releases if not r["prerelease"]]),
                "prereleases": len([r for r in parsed_releases if r["prerelease"]]),
                "stable_iso_downloads": total_stable_iso_downloads,
                "prerelease_iso_downloads": total_prerelease_iso_downloads,
                "stable_asset_downloads": total_stable_asset_downloads,
                "prerelease_asset_downloads": total_prerelease_asset_downloads,
            },
            "latest": {
                "tag": latest_release_tag,
                "version": latest_version,
                "iso_downloads": latest_release_downloads,
            },
            "releases": parsed_releases,
            "disclaimer": (
                "Metrics represent native GitHub-reported asset download counts "
                "via GitHub Releases REST API and do not imply unique visitors or "
                "verified successful system installations."
            )
        }
        return stats

    def write_stats_json(self, output_path: str) -> None:
        """Write current stats to a static JSON file."""
        stats = self.generate_stats(use_cache=False)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
        logger.info("Wrote statistics JSON to %s", output_path)
