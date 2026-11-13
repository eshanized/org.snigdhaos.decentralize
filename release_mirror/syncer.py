"""
End-to-end synchronization workflow orchestrator for GitLab -> GitHub release mirroring.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import logging
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import (
    AssetOversizedError,
    ConfigurationError,
    ReleaseImmutableMutationError,
    VerificationError,
)
from release_mirror.github_client import GitHubClient
from release_mirror.gitlab_client import GitLabClient
from release_mirror.verifier import CryptographicVerifier

logger = logging.getLogger("release_mirror.syncer")


class ReleaseSyncer:
    """Orchestrates secure, idempotent GitLab to GitHub release mirroring."""

    def __init__(
        self,
        config: MirrorConfig,
        gitlab_client: Optional[GitLabClient] = None,
        github_client: Optional[GitHubClient] = None,
        verifier: Optional[CryptographicVerifier] = None,
    ):
        self.config = config
        self.gitlab = gitlab_client or GitLabClient(config)
        self.github = github_client or GitHubClient(config)
        self.verifier = verifier or CryptographicVerifier(config)

    def format_gitlab_description_with_downloads(
        self,
        original_description: str,
        tag: str,
        iso_name: Optional[str],
        iso_oversized: bool = False,
    ) -> str:
        """
        Enrich GitLab release description with GitHub download links and live badge,
        preserving all existing notes and verification instructions.
        """
        gh_repo = self.config.github_repository
        gh_release_url = f"https://github.com/{gh_repo}/releases/tag/{tag}"

        download_block_lines = ["\n## Downloads\n"]
        if iso_name and not iso_oversized:
            gh_iso_url = f"https://github.com/{gh_repo}/releases/download/{tag}/{iso_name}"
            download_block_lines.append(f"- **[Download ISO from GitHub (Fast Mirror)]({gh_iso_url})**")
        elif iso_oversized:
            download_block_lines.append(
                f"- **ISO Image:** Hosted directly on GitLab (exceeds GitHub single-asset 2 GiB limit)."
            )

        badge_url = (
            f"https://raw.githubusercontent.com/{gh_repo}/master/public/badges/total-iso-downloads.svg"
        )
        download_block_lines.append(
            f"\n**Mirror Downloads:** [![Total Downloads]({badge_url})]({gh_release_url})\n"
        )
        download_block_lines.append(f"- [View all release assets on GitHub]({gh_release_url})\n")
        download_block = "\n".join(download_block_lines)

        # If a Downloads section already exists from a previous run, replace it cleanly
        if re.search(r'##\s+Downloads.*?(?=\n##|\Z)', original_description, re.DOTALL):
            new_desc = re.sub(
                r'##\s+Downloads.*?(?=\n##|\Z)',
                download_block.strip() + "\n",
                original_description,
                flags=re.DOTALL
            )
        else:
            new_desc = original_description.rstrip() + "\n\n" + download_block.strip() + "\n"

        return new_desc

    def sync_release(
        self,
        tag: str,
        dry_run: bool = False,
        update_gitlab_notes: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute full synchronization of release `tag` from GitLab to GitHub.
        Guarantees idempotency, atomic publication, immutability, and cleanup.
        """
        logger.info("Starting synchronization for tag: %s", tag)

        # 1. Discover GitLab Release Metadata
        gl_release = self.gitlab.get_release(tag)
        gl_tag_name = gl_release.get("tag_name", tag)
        gl_name = gl_release.get("name") or gl_tag_name
        gl_description = gl_release.get("description") or ""
        upcoming = gl_release.get("upcoming_release", False)
        is_prerelease = bool(upcoming or "-rc" in gl_tag_name.lower())

        gl_links = gl_release.get("assets", {}).get("links", [])
        if not gl_links:
            raise VerificationError(f"No release asset links found in GitLab release '{tag}'.")

        logger.info(
            "Discovered GitLab release '%s' (title: '%s', %d asset links, prerelease: %s)",
            gl_tag_name, gl_name, len(gl_links), is_prerelease
        )

        # 2. Check Existing GitHub Release for Idempotency & Immutability
        existing_gh_release = self.github.get_release_by_tag(gl_tag_name)
        if existing_gh_release and not existing_gh_release.get("draft", False):
            logger.info("GitHub release for %s already exists and is published.", gl_tag_name)
            gh_assets = self.github.get_release_assets(existing_gh_release["id"])
            gh_asset_map = {a["name"]: a for a in gh_assets}

            # Check if all GitLab assets exist with matching names
            all_present = True
            for link in gl_links:
                name = link.get("name", "")
                if name not in gh_asset_map:
                    all_present = False
                    break

            if all_present:
                logger.info(
                    "Idempotent check passed: all assets present in published GitHub release %s. "
                    "Refreshing metadata safely.",
                    gl_tag_name
                )
                if not dry_run:
                    self.github.update_release(
                        release_id=existing_gh_release["id"],
                        name=gl_name,
                        prerelease=is_prerelease,
                    )
                return {
                    "status": "already_mirrored",
                    "tag": gl_tag_name,
                    "release_id": existing_gh_release["id"],
                    "html_url": existing_gh_release.get("html_url", ""),
                    "assets_mirrored": len(gh_assets),
                }

        if dry_run:
            logger.info("[dry-run] Would mirror %d assets for release %s", len(gl_links), gl_tag_name)
            return {
                "status": "dry_run",
                "tag": gl_tag_name,
                "assets_count": len(gl_links),
            }

        # 3. Create Temporary Workspace & Download Assets
        temp_dir = tempfile.mkdtemp(prefix=f"mirror_{gl_tag_name}_", dir=self.config.temp_dir)
        downloaded_files: Dict[str, str] = {}
        oversized_assets: List[str] = []
        iso_name: Optional[str] = None
        iso_oversized = False

        try:
            self.verifier.setup_gnupg()

            for link in gl_links:
                name = link.get("name")
                url = link.get("url")
                if not name or not url:
                    continue

                if name.endswith(".iso"):
                    iso_name = name

                dest_path = os.path.join(temp_dir, name)
                sha256, blake2b, size = self.gitlab.download_asset(url, dest_path)
                logger.info("Downloaded %s (%d bytes, sha256: %s)", name, size, sha256)

                if size > self.config.max_asset_size_bytes:
                    logger.warning(
                        "Asset '%s' exceeds GitHub 2 GiB limit (%d bytes). Will preserve GitLab origin.",
                        name, size
                    )
                    oversized_assets.append(name)
                    if name.endswith(".iso"):
                        iso_oversized = True
                else:
                    downloaded_files[name] = dest_path

            # 4. Cryptographic Verification
            # Even if the ISO is oversized, we must verify its integrity
            # Include all downloaded files for bundle verification
            all_downloaded = {**downloaded_files}
            for oversized_name in oversized_assets:
                all_downloaded[oversized_name] = os.path.join(temp_dir, oversized_name)

            logger.info("Executing cryptographic bundle verification...")
            verified_digests = self.verifier.verify_release_bundle(all_downloaded)
            logger.info("All release assets cryptographically verified against trusted keys!")

            # 5. Create or Reuse Draft GitHub Release
            gh_release_id: int
            upload_url: str

            if existing_gh_release:
                gh_release_id = existing_gh_release["id"]
                upload_url = existing_gh_release["upload_url"]
                logger.info("Using existing GitHub draft release ID: %d", gh_release_id)
            else:
                new_rel = self.github.create_release(
                    tag_name=gl_tag_name,
                    name=gl_name,
                    body=gl_description,
                    draft=True, # Start as draft until assets are uploaded and verified
                    prerelease=is_prerelease,
                )
                gh_release_id = new_rel["id"]
                upload_url = new_rel["upload_url"]

            # 6. Upload Verified Eligible Assets to GitHub
            existing_gh_assets = self.github.get_release_assets(gh_release_id)
            existing_map = {a["name"]: a for a in existing_gh_assets}

            uploaded_assets_summary: List[Dict[str, Any]] = []

            for asset_name, asset_path in downloaded_files.items():
                local_size = os.path.getsize(asset_path)

                # Check if asset already exists on GitHub
                if asset_name in existing_map:
                    gh_asset = existing_map[asset_name]
                    if gh_asset.get("size") == local_size:
                        logger.info("Asset '%s' already uploaded with matching size. Skipping.", asset_name)
                        uploaded_assets_summary.append({
                            "name": asset_name,
                            "size": local_size,
                            "sha256": verified_digests.get(asset_name, ""),
                        })
                        continue
                    else:
                        logger.warning(
                            "Asset '%s' exists on GitHub with mismatched size (%s != %s). Removing corrupted asset...",
                            asset_name, gh_asset.get("size"), local_size
                        )
                        self.github.delete_release_asset(gh_asset["id"])

                content_type = "application/x-iso9660-image" if asset_name.endswith(".iso") else "application/octet-stream"
                up_res = self.github.upload_release_asset(
                    upload_url_template=upload_url,
                    file_path=asset_path,
                    asset_name=asset_name,
                    content_type=content_type,
                )
                uploaded_assets_summary.append({
                    "name": asset_name,
                    "size": local_size,
                    "sha256": verified_digests.get(asset_name, ""),
                    "id": up_res.get("id"),
                })

            # 7. Post-Upload Verification
            final_gh_assets = self.github.get_release_assets(gh_release_id)
            final_map = {a["name"]: a for a in final_gh_assets}

            for asset_name, asset_path in downloaded_files.items():
                if asset_name not in final_map:
                    raise VerificationError(f"Post-upload verification failed: missing asset '{asset_name}' on GitHub.")
                if final_map[asset_name]["size"] != os.path.getsize(asset_path):
                    raise VerificationError(
                        f"Post-upload verification failed: size mismatch for '{asset_name}' on GitHub."
                    )

            logger.info("Post-upload verification successful for all %d assets.", len(downloaded_files))

            # 8. Atomic Publication: Update Draft -> Published
            published_rel = self.github.update_release(
                release_id=gh_release_id,
                name=gl_name,
                body=gl_description,
                draft=False, # Now public
                prerelease=is_prerelease,
            )
            logger.info("Published GitHub release '%s' (ID %d)", gl_tag_name, gh_release_id)

            # 9. Update GitLab Release Page with Download Links & Badges
            if update_gitlab_notes and not dry_run:
                try:
                    enriched_desc = self.format_gitlab_description_with_downloads(
                        gl_description, gl_tag_name, iso_name, iso_oversized
                    )
                    self.gitlab.update_release_description(gl_tag_name, enriched_desc)
                    logger.info("Updated GitLab release description with GitHub download links.")
                except Exception as e:
                    logger.warning("Failed to update GitLab release notes: %s", str(e))

            return {
                "status": "success",
                "tag": gl_tag_name,
                "release_id": gh_release_id,
                "html_url": published_rel.get("html_url", ""),
                "assets_mirrored": len(downloaded_files),
                "oversized_assets": oversized_assets,
                "verified_digests": verified_digests,
            }

        finally:
            # 10. Guaranteed Cleanup of temporary files and keyring
            self.verifier.cleanup_gnupg()
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info("Cleaned up temporary workspace: %s", temp_dir)
