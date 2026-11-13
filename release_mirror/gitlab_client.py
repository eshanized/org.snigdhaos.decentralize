"""
GitLab REST API client for release discovery, asset download, and release note updates.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import json
import logging
import os
import random
import shutil
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import (
    ConfigurationError,
    DiskSpaceError,
    GitLabAPIError,
)

logger = logging.getLogger("release_mirror.gitlab")


class GitLabClient:
    """Client for GitLab Releases REST API v4."""

    def __init__(self, config: MirrorConfig):
        self.config = config
        self.host = config.gitlab_host.strip("/")
        self.project_path = config.gitlab_project
        self.encoded_project = urllib.parse.quote(self.project_path, safe="")
        self.base_url = f"https://{self.host}/api/v4/projects/{self.encoded_project}"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "SnigdhaOS-ReleaseMirror/1.0",
        }
        if self.config.gitlab_token:
            headers["PRIVATE-TOKEN"] = self.config.gitlab_token
        return headers

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        expected_status: Tuple[int, ...] = (200,),
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = self._get_headers()
        body_bytes = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body_bytes = json.dumps(data).encode("utf-8")

        for attempt in range(1, self.config.max_retries + 1):
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    resp_data = resp.read().decode("utf-8")
                    if resp.status not in expected_status:
                        raise GitLabAPIError(
                            f"Unexpected HTTP status {resp.status} for {method} {url}",
                            status_code=resp.status,
                            response_body=resp_data,
                        )
                    if not resp_data.strip():
                        return {}
                    return json.loads(resp_data)
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass

                # Handle rate limits or temporary server errors
                if e.code in (429, 500, 502, 503, 504) and attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "GitLab API HTTP %d (attempt %d/%d). Retrying in %.2fs...",
                        e.code, attempt, self.config.max_retries, sleep_time
                    )
                    time.sleep(sleep_time)
                    continue

                masked_msg = self.config.mask_secrets(f"HTTP {e.code}: {e.reason} - {err_body}")
                raise GitLabAPIError(masked_msg, status_code=e.code, response_body=err_body)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "GitLab API connection error: %s (attempt %d/%d). Retrying in %.2fs...",
                        str(e), attempt, self.config.max_retries, sleep_time
                    )
                    time.sleep(sleep_time)
                    continue
                masked_msg = self.config.mask_secrets(str(e))
                raise GitLabAPIError(f"Network error contacting GitLab: {masked_msg}")

    def get_release(self, tag: str) -> Dict[str, Any]:
        """Fetch release metadata for a specific tag."""
        encoded_tag = urllib.parse.quote(tag, safe="")
        return self._request("GET", f"releases/{encoded_tag}")

    def list_releases(self, page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
        """List releases from the GitLab project with pagination."""
        return self._request("GET", f"releases?page={page}&per_page={per_page}")

    def get_release_assets(self, tag: str) -> List[Dict[str, Any]]:
        """Discover all release asset links associated with a release tag."""
        release = self.get_release(tag)
        assets_dict = release.get("assets", {})
        links = assets_dict.get("links", [])
        return links

    def update_release_description(self, tag: str, description: str) -> Dict[str, Any]:
        """Update the description of an existing GitLab release."""
        encoded_tag = urllib.parse.quote(tag, safe="")
        data = {"description": description}
        logger.info("Updating GitLab release description for tag %s", tag)
        return self._request("PUT", f"releases/{encoded_tag}", data=data)

    def download_asset(
        self,
        asset_url: str,
        destination_path: str,
        expected_size: Optional[int] = None,
    ) -> Tuple[str, str, int]:
        """
        Stream an asset from GitLab directly to local disk.
        Returns: (sha256_hex, blake2b_hex, size_bytes)
        """
        dest_dir = os.path.dirname(os.path.abspath(destination_path))
        os.makedirs(dest_dir, exist_ok=True)

        # Check free disk space before downloading
        usage = shutil.disk_usage(dest_dir)
        if expected_size and usage.free < (expected_size + self.config.min_free_disk_bytes):
            raise DiskSpaceError(
                f"Insufficient disk space in {dest_dir}: {usage.free} bytes free, "
                f"need at least {expected_size + self.config.min_free_disk_bytes} bytes."
            )

        headers = {
            "User-Agent": "SnigdhaOS-ReleaseMirror/1.0",
        }
        if self.config.gitlab_token:
            headers["PRIVATE-TOKEN"] = self.config.gitlab_token

        for attempt in range(1, self.config.max_retries + 1):
            sha256 = hashlib.sha256()
            blake2b = hashlib.blake2b()
            total_bytes = 0

            req = urllib.request.Request(asset_url, headers=headers)
            try:
                logger.info(
                    "Downloading %s -> %s (attempt %d/%d)",
                    os.path.basename(destination_path), destination_path, attempt, self.config.max_retries
                )
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    with open(destination_path, "wb") as f_out:
                        while True:
                            chunk = resp.read(self.config.chunk_size_bytes)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            sha256.update(chunk)
                            blake2b.update(chunk)
                            total_bytes += len(chunk)

                # If download completed, return digests and size
                return sha256.hexdigest(), blake2b.hexdigest(), total_bytes

            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
                # Remove partially downloaded file on failure
                if os.path.exists(destination_path):
                    try:
                        os.remove(destination_path)
                    except OSError:
                        pass

                if attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "Download failure (%s): %s (retrying in %.2fs)",
                        os.path.basename(destination_path), str(e), sleep_time
                    )
                    time.sleep(sleep_time)
                    continue

                masked_msg = self.config.mask_secrets(str(e))
                raise GitLabAPIError(f"Failed to download asset from {asset_url}: {masked_msg}")
