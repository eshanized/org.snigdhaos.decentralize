"""
Command-line interface (CLI) for Snigdha OS Decentralized release mirroring.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from typing import List, Optional

from release_mirror.badges import BadgeGenerator
from release_mirror.config import MirrorConfig
from release_mirror.exceptions import MirrorError
from release_mirror.github_client import GitHubClient
from release_mirror.gitlab_client import GitLabClient
from release_mirror.stats import ReleaseStatsAggregator
from release_mirror.syncer import ReleaseSyncer
from release_mirror.verifier import CryptographicVerifier


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging format and level."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)


def cmd_sync(args: argparse.Namespace, config: MirrorConfig) -> int:
    """Execute release-mirror sync --tag <tag>."""
    tag = args.tag.strip()
    if not tag:
        print("Error: --tag is required.", file=sys.stderr)
        return 1

    syncer = ReleaseSyncer(config)
    try:
        res = syncer.sync_release(
            tag=tag,
            dry_run=args.dry_run,
            update_gitlab_notes=not args.no_gitlab_update,
        )
        print("\n=== Synchronization Completed Successfully ===")
        print(f"Status:          {res.get('status')}")
        print(f"Tag:             {res.get('tag')}")
        if res.get("html_url"):
            print(f"GitHub Release:  {res.get('html_url')}")
        print(f"Assets Mirrored: {res.get('assets_mirrored', 0)}")
        if res.get("oversized_assets"):
            print(f"Oversized (kept on GitLab): {', '.join(res['oversized_assets'])}")
        return 0
    except MirrorError as e:
        print(f"\n[FAIL] Mirroring failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[FAIL] Unexpected error: {e}", file=sys.stderr)
        return 1


def cmd_verify(args: argparse.Namespace, config: MirrorConfig) -> int:
    """Execute release-mirror verify --tag <tag>."""
    tag = args.tag.strip()
    if not tag:
        print("Error: --tag is required.", file=sys.stderr)
        return 1

    gitlab = GitLabClient(config)
    verifier = CryptographicVerifier(config)

    print(f"=== Cryptographic Verification for Tag: {tag} ===")
    print(f"Trusted Key Fingerprint: {config.trusted_signing_key_fingerprint}")

    temp_dir = tempfile.mkdtemp(prefix=f"verify_{tag}_")
    try:
        release = gitlab.get_release(tag)
        links = release.get("assets", {}).get("links", [])
        if not links:
            print("No assets found in GitLab release.", file=sys.stderr)
            return 1

        downloaded: dict = {}
        for link in links:
            name = link.get("name")
            url = link.get("url")
            if not name or not url:
                continue
            dest = os.path.join(temp_dir, name)
            print(f"  Downloading {name}...")
            gitlab.download_asset(url, dest)
            downloaded[name] = dest

        verifier.setup_gnupg()
        verified_digests = verifier.verify_release_bundle(downloaded)

        print("\n=== Verification Verdict: PASS ===")
        print("All signatures and SHA-256 manifests verified against the trusted release key.")
        for fname, digest in verified_digests.items():
            print(f"  ✓ {fname}: {digest}")
        return 0
    except MirrorError as e:
        print(f"\n[FAIL] Cryptographic verification failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[FAIL] Unexpected error during verification: {e}", file=sys.stderr)
        return 1
    finally:
        verifier.cleanup_gnupg()
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def cmd_stats(args: argparse.Namespace, config: MirrorConfig) -> int:
    """Execute release-mirror stats."""
    aggregator = ReleaseStatsAggregator(config)
    try:
        stats = aggregator.generate_stats(use_cache=not args.no_cache)

        if args.output:
            aggregator.write_stats_json(args.output)
            print(f"Statistics written to {args.output}")

        if args.badges_dir:
            generator = BadgeGenerator(stats)
            generator.generate_all(args.badges_dir)
            print(f"Badges generated in {args.badges_dir}")

        if args.format == "json":
            print(json.dumps(stats, indent=2))
        else:
            totals = stats.get("totals", {})
            latest = stats.get("latest", {})
            print(f"\n=== Download Statistics for {config.github_repository} ===")
            print(f"Generated at:      {stats.get('generated_at')}")
            print(f"Total ISO DLs:     {totals.get('iso_downloads', 0):,}")
            print(f"Total Asset DLs:   {totals.get('asset_downloads', 0):,}")
            print(f"Releases Count:    {totals.get('releases', 0)} ({totals.get('stable_releases', 0)} stable, {totals.get('prereleases', 0)} prerelease)")
            print(f"Latest Version:    {latest.get('tag', 'None')} ({latest.get('iso_downloads', 0):,} ISO downloads)")
            print("\nPer-Release Breakdown:")
            for r in stats.get("releases", []):
                rel_type = "PRERELEASE" if r["prerelease"] else "STABLE"
                print(f"  - {r['tag']} [{rel_type}]: {r['iso_downloads']:,} ISO DLs, {r['asset_downloads']:,} Total Asset DLs")
        return 0
    except Exception as e:
        print(f"Error gathering statistics: {e}", file=sys.stderr)
        return 1


def cmd_inspect(args: argparse.Namespace, config: MirrorConfig) -> int:
    """Execute release-mirror inspect --tag <tag>."""
    tag = args.tag.strip()
    if not tag:
        print("Error: --tag is required.", file=sys.stderr)
        return 1

    gitlab = GitLabClient(config)
    github = GitHubClient(config)

    print(f"\n=== Release Inspection for Tag: {tag} ===")

    # GitLab inspection
    print("\n--- GitLab Source Release ---")
    try:
        gl_release = gitlab.get_release(tag)
        print(f"Title:        {gl_release.get('name')}")
        print(f"Tag:          {gl_release.get('tag_name')}")
        print(f"Created:      {gl_release.get('created_at')}")
        print(f"Released:     {gl_release.get('released_at')}")
        links = gl_release.get("assets", {}).get("links", [])
        print(f"Asset links:  {len(links)}")
        for l in links:
            print(f"  • {l.get('name')} -> {l.get('url')}")
    except Exception as e:
        print(f"GitLab query error: {e}")

    # GitHub inspection
    print("\n--- GitHub Target Mirror Release ---")
    try:
        gh_release = github.get_release_by_tag(tag)
        if not gh_release:
            print("Status: NOT MIRRORED YET (Release not found on GitHub)")
        else:
            print(f"ID:           {gh_release.get('id')}")
            print(f"Title:        {gh_release.get('name')}")
            print(f"Draft:        {gh_release.get('draft')}")
            print(f"Prerelease:   {gh_release.get('prerelease')}")
            print(f"HTML URL:     {gh_release.get('html_url')}")
            assets = gh_release.get("assets", [])
            print(f"Assets:       {len(assets)}")
            for a in assets:
                print(f"  • {a.get('name')} ({a.get('size'):,} bytes, {a.get('download_count')} downloads)")
    except Exception as e:
        print(f"GitHub query error: {e}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point dispatcher."""
    parser = argparse.ArgumentParser(
        prog="release-mirror",
        description="Automated GitLab -> GitHub Release Mirroring and Analytics CLI for Snigdha OS Decentralized",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to execute")

    # Command: sync
    sync_p = subparsers.add_parser("sync", help="Synchronize a release from GitLab to GitHub")
    sync_p.add_argument("--tag", required=True, help="Release tag name to synchronize (e.g. v2026.11.13-rc1)")
    sync_p.add_argument("--dry-run", action="store_true", help="Simulate release synchronization without changes")
    sync_p.add_argument("--no-gitlab-update", action="store_true", help="Do not update GitLab release notes")

    # Command: verify
    verify_p = subparsers.add_parser("verify", help="Cryptographically verify release assets against trusted keys")
    verify_p.add_argument("--tag", required=True, help="Release tag name to verify")

    # Command: stats
    stats_p = subparsers.add_parser("stats", help="Retrieve public GitHub release download statistics")
    stats_p.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    stats_p.add_argument("--output", help="Path to write stats.json file")
    stats_p.add_argument("--badges-dir", help="Directory to generate Shields JSON and SVG badges")
    stats_p.add_argument("--no-cache", action="store_true", help="Bypass API response cache")

    # Command: inspect
    inspect_p = subparsers.add_parser("inspect", help="Inspect release status across both GitLab and GitHub")
    inspect_p.add_argument("--tag", required=True, help="Release tag to inspect")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    config = MirrorConfig.from_env()

    if args.command == "sync":
        return cmd_sync(args, config)
    elif args.command == "verify":
        return cmd_verify(args, config)
    elif args.command == "stats":
        return cmd_stats(args, config)
    elif args.command == "inspect":
        return cmd_inspect(args, config)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
