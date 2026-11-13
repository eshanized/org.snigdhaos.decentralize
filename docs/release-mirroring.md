# Release Mirroring Workflow Guide

**Project:** Snigdha OS Decentralized  
**Tool:** `release-mirror` CLI & Python Engine  
**License:** GPL-3.0-or-later  

---

## 1. Overview

The release mirroring workflow enables zero-touch synchronization of newly cut Snigdha OS releases from GitLab to GitHub. This document details the end-to-end execution flow, idempotency guarantees, and fail-safe mechanisms.

---

## 2. Step-by-Step Execution Sequence

```text
1. Tag Trigger (GitLab CI)
      │
2. Query GitLab Release Metadata ────────> GET /projects/:id/releases/:tag
      │
3. Enumerate Assets (URLs & Links)
      │
4. Immutability & Idempotency Check ─────> GET /repos/:owner/:repo/releases/tags/:tag
      ├─► If all assets exist & match ───► No-op / refresh metadata ──► EXIT (OK)
      └─► If asset mutated ──────────────► ABORT (ReleaseImmutableMutationError)
      │
5. Allocate Temporary Workspace ─────────► /tmp/mirror_vYYYY.MM.DD_XXXXXX
      │
6. Streaming Download from GitLab ───────► Track bytes, stream to disk
      ├─► Compute SHA-256 & BLAKE2b progressively
      └─► Check available disk space (require >= 5 GiB free)
      │
7. Size Check (< 2 GiB)
      ├─► If ISO <= 2 GiB ───────────────► Stage for GitHub upload
      └─► If ISO > 2 GiB ────────────────► Flag oversized, preserve GitLab origin
      │
8. Cryptographic Verification Gate
      ├─► Import release-signing-key.asc into ephemeral GNUPGHOME
      ├─► Verify fingerprint == 2BDB00AE6CABEF0E40520A8F553FD42B02A8211A
      ├─► Verify GPG detached signature on SHA256SUMS
      ├─► Verify GPG detached signature on ISO (*.iso.sig)
      └─► Verify all file hashes against signed SHA256SUMS
      │
9. GitHub Release Preparation
      ├─► Find or Create GitHub Release (draft: true, prerelease: is_rc)
      └─► Purge any stale/incomplete assets from prior failed attempts
      │
10. Stream Upload to GitHub ─────────────► POST uploads.github.com/repos/.../assets
      │
11. Post-Upload Verification
      ├─► Query GitHub release assets API
      └─► Verify all assets present and byte counts match source files
      │
12. Atomic Publication ──────────────────► PATCH /repos/.../releases/:id (draft: false)
      │
13. Enrich GitLab Release Notes ─────────► PUT /projects/:id/releases/:tag
      │
14. Workspace Teardown ──────────────────► Purge /tmp workspace & GNUPGHOME
```

---

## 3. Idempotency Guarantees

Running the mirroring process multiple times for the same release tag is guaranteed safe and produces identical results:

1. **Tag Discovery:**
   The mirror looks up existing GitHub releases by tag name. If an existing published release is found:
   - It fetches the published asset list from GitHub.
   - If every asset from the GitLab release exists on GitHub with identical names and byte lengths, the syncer performs a harmless metadata refresh and exits with status `already_mirrored`.
2. **Partial Upload Recovery:**
   If a previous mirroring run crashed midway through asset uploading:
   - The release remains in `draft: true` state on GitHub.
   - On the subsequent run, the mirror detects the draft release.
   - Assets already uploaded with matching sizes are skipped.
   - Incompletely uploaded or corrupted assets are purged via `DELETE /repos/:owner/:repo/releases/assets/:asset_id`.
   - Remaining assets are uploaded cleanly.
3. **No Duplicate Releases:**
   GitHub release creation is only invoked if `GET /repos/:owner/:repo/releases/tags/:tag` returns HTTP 404.

---

## 4. Size Limit Handling (2 GiB Limit)

GitHub Releases enforce a hard maximum limit of **2.00 GiB (2,147,483,648 bytes)** per individual asset.

The current Snigdha OS Decentralized ISO image is approximately **1.38 GiB (1,482,342,400 bytes)**, which is safely below this boundary.

However, if future ISOs exceed 2 GiB:
- The mirror engine will **never** silently truncate, chunk, or split the ISO into arbitrary multi-part files that cannot be booted.
- The oversized ISO is excluded from the GitHub upload queue.
- The GitLab release URL is preserved as the authoritative download link.
- All eligible supplementary assets (manifests, signatures, SBOM, provenance) are mirrored normally.
- The release description explicitly notes that the primary image is hosted directly on GitLab.

---

## 5. Security Fail-Closed Behavior

The mirror engine fails closed on any of the following conditions:
- **Untrusted Key:** The signing key fingerprint differs from `2BDB00AE6CABEF0E40520A8F553FD42B02A8211A`.
- **Bad Signature:** Manifest or ISO detached signature fails verification.
- **Checksum Mismatch:** Any downloaded file digest does not match the signed `SHA256SUMS`.
- **Upload Mismatch:** Post-upload GitHub asset size differs from the local verified asset.

Under any of these conditions:
- No unverified release is marked `draft: false`.
- The GitLab pipeline halts with an error exit code (1).
- Temporary files and private keyring allocations are immediately purged.
