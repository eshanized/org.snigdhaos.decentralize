"""
GitHub REST API client for release mirroring, asset uploading, and download statistics.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import (
    AssetOversizedError,
    ConfigurationError,
    GitHubAPIError,
)

logger = logging.getLogger("release_mirror.github")


class GitHubClient:
    """Client for GitHub Releases REST API."""

    def __init__(self, config: MirrorConfig):
        self.config = config
        self.repository = config.github_repository.strip("/")
        if "/" not in self.repository:
            raise ConfigurationError(
                f"Invalid GitHub repository '{self.repository}'. Expected 'owner/repo'."
            )
        self.owner, self.repo = self.repository.split("/", 1)
        self.base_url = f"https://api.github.com/repos/{self.owner}/{self.repo}"

    def _get_headers(self, content_type: Optional[str] = "application/json") -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SnigdhaOS-ReleaseMirror/1.0",
        }
        if self.config.github_token:
            headers["Authorization"] = f"Bearer {self.config.github_token}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        expected_status: Tuple[int, ...] = (200,),
        full_url: Optional[str] = None,
        headers_override: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = full_url if full_url else f"{self.base_url}/{path.lstrip('/')}"
        headers = headers_override or self._get_headers()
        body_bytes = None
        if data is not None and headers.get("Content-Type") == "application/json":
            body_bytes = json.dumps(data).encode("utf-8")

        for attempt in range(1, self.config.max_retries + 1):
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    resp_data = resp.read().decode("utf-8")
                    if resp.status not in expected_status:
                        raise GitHubAPIError(
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

                # If checking for existing release, 404 is an expected condition
                if e.code == 404 and 404 in expected_status:
                    return None

                # Handle rate limits
                rate_remaining = e.headers.get("x-ratelimit-remaining")
                rate_reset = e.headers.get("x-ratelimit-reset")
                if e.code == 403 and rate_remaining == "0" and rate_reset:
                    wait_seconds = max(1, int(rate_reset) - int(time.time()) + 1)
                    logger.warning(
                        "GitHub API rate limit exhausted. Waiting %d seconds for reset...",
                        wait_seconds
                    )
                    time.sleep(min(wait_seconds, 60))
                    continue

                if e.code in (429, 500, 502, 503, 504) and attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "GitHub API HTTP %d (attempt %d/%d). Retrying in %.2fs...",
                        e.code, attempt, self.config.max_retries, sleep_time
                    )
                    time.sleep(sleep_time)
                    continue

                masked_msg = self.config.mask_secrets(f"HTTP {e.code}: {e.reason} - {err_body}")
                raise GitHubAPIError(masked_msg, status_code=e.code, response_body=err_body)
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "GitHub API connection error: %s (attempt %d/%d). Retrying in %.2fs...",
                        str(e), attempt, self.config.max_retries, sleep_time
                    )
                    time.sleep(sleep_time)
                    continue
                masked_msg = self.config.mask_secrets(str(e))
                raise GitHubAPIError(f"Network error contacting GitHub: {masked_msg}")

    def get_release_by_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        """Retrieve release metadata for a tag, returning None if not found (404)."""
        encoded_tag = urllib.parse.quote(tag, safe="")
        return self._request("GET", f"releases/tags/{encoded_tag}", expected_status=(200, 404))

    def create_release(
        self,
        tag_name: str,
        name: str,
        body: str,
        draft: bool = True,
        prerelease: bool = False,
        target_commitish: str = "master",
    ) -> Dict[str, Any]:
        """Create a new release on GitHub."""
        payload = {
            "tag_name": tag_name,
            "target_commitish": target_commitish,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
        }
        logger.info(
            "Creating GitHub release: tag=%s, draft=%s, prerelease=%s",
            tag_name, draft, prerelease
        )
        return self._request("POST", "releases", data=payload, expected_status=(201,))

    def update_release(
        self,
        release_id: int,
        name: Optional[str] = None,
        body: Optional[str] = None,
        draft: Optional[bool] = None,
        prerelease: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update an existing GitHub release's metadata or status."""
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if body is not None:
            payload["body"] = body
        if draft is not None:
            payload["draft"] = draft
        if prerelease is not None:
            payload["prerelease"] = prerelease

        logger.info("Updating GitHub release ID %d (keys: %s)", release_id, list(payload.keys()))
        return self._request("PATCH", f"releases/{release_id}", data=payload, expected_status=(200,))

    def get_release_assets(self, release_id: int) -> List[Dict[str, Any]]:
        """List assets associated with a release ID."""
        return self._request("GET", f"releases/{release_id}/assets", expected_status=(200,))

    def delete_release_asset(self, asset_id: int) -> bool:
        """Delete an existing release asset."""
        logger.info("Deleting release asset ID %d", asset_id)
        self._request("DELETE", f"releases/assets/{asset_id}", expected_status=(204,))
        return True

    def upload_release_asset(
        self,
        upload_url_template: str,
        file_path: str,
        asset_name: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        """
        Upload a file as a GitHub release asset using streaming file reading.
        Validates size does not exceed the 2 GiB upload limit.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Asset file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size > self.config.max_asset_size_bytes:
            raise AssetOversizedError(
                f"Asset {file_path} size ({file_size} bytes) exceeds GitHub's limit of "
                f"{self.config.max_asset_size_bytes} bytes (2 GiB)."
            )

        name = asset_name or os.path.basename(file_path)

        # Base upload URL: strip template variable {?name,label}
        base_upload_url = re.sub(r'\{.*?\}', '', upload_url_template)
        upload_url = f"{base_upload_url}?name={urllib.parse.quote(name)}"

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SnigdhaOS-ReleaseMirror/1.0",
            "Content-Type": content_type,
            "Content-Length": str(file_size),
        }
        if self.config.github_token:
            headers["Authorization"] = f"Bearer {self.config.github_token}"

        logger.info("Uploading asset '%s' (%d bytes) to GitHub...", name, file_size)

        for attempt in range(1, self.config.max_retries + 1):
            try:
                with open(file_path, "rb") as f_in:
                    req = urllib.request.Request(
                        upload_url,
                        data=f_in,
                        headers=headers,
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                        resp_data = resp.read().decode("utf-8")
                        if resp.status != 201:
                            raise GitHubAPIError(
                                f"Failed uploading asset {name}, status {resp.status}",
                                status_code=resp.status,
                                response_body=resp_data
                            )
                        logger.info("Successfully uploaded asset '%s' to GitHub", name)
                        return json.loads(resp_data)
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass

                # If duplicate (422 already_exists), return error or retry
                if e.code in (429, 500, 502, 503, 504) and attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "Upload error HTTP %d for %s (attempt %d/%d). Retrying in %.2fs...",
                        e.code, name, attempt, self.config.max_retries, sleep_time
                    )
                    time.sleep(sleep_time)
                    continue

                masked_msg = self.config.mask_secrets(f"HTTP {e.code}: {e.reason} - {err_body}")
                raise GitHubAPIError(masked_msg, status_code=e.code, response_body=err_body)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < self.config.max_retries:
                    sleep_time = (self.config.backoff_factor ** attempt) + random.uniform(0.1, 1.0)
                    logger.warning(
                        "Network error during upload of %s: %s (retrying in %.2fs)",
                        name, str(e), sleep_time
                    )
                    time.sleep(sleep_time)
                    continue
                masked_msg = self.config.mask_secrets(str(e))
                raise GitHubAPIError(f"Network error during asset upload: {masked_msg}")

    def list_all_releases(self) -> List[Dict[str, Any]]:
        """
        List all releases from the GitHub repository, handling pagination
        via the Link header. Can be called without authentication.
        """
        releases: List[Dict[str, Any]] = []
        url: Optional[str] = f"{self.base_url}/releases?per_page=100"

        while url:
            headers = self._get_headers()
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list):
                        releases.extend(data)

                    # Parse next page from Link header
                    link_header = resp.headers.get("Link", "")
                    next_url = None
                    if link_header:
                        for part in link_header.split(","):
                            section = part.split(";")
                            if len(section) >= 2 and 'rel="next"' in section[1]:
                                match = re.search(r'<([^>]+)>', section[0])
                                if match:
                                    next_url = match.group(1)
                                    break
                    url = next_url
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                masked_msg = self.config.mask_secrets(f"HTTP {e.code}: {e.reason} - {err_body}")
                raise GitHubAPIError(masked_msg, status_code=e.code, response_body=err_body)
            except Exception as e:
                masked_msg = self.config.mask_secrets(str(e))
                raise GitHubAPIError(f"Error fetching GitHub releases: {masked_msg}")

        return releases
