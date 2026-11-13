# Architecture Specification: Automated Release Mirroring

**Project:** Snigdha OS Decentralized  
**Source Repository (Canonical):** `https://gitlab.com/SnigdhaOS/decentralize/iso`  
**Mirror Repository (Target):** `https://github.com/eshanized/org.snigdhaos.decentralize`  
**License:** GPL-3.0-or-later  

---

## 1. Architectural Overview

Snigdha OS Decentralized enforces strict cryptographic boundaries and immutable release delivery. The build pipelines, packaging, signing keys, and source repositories reside canonically on **GitLab**.

GitHub acts exclusively as a **public binary mirror and authoritative download analytics provider**, leveraging GitHub's native release asset `download_count`.

```text
+-------------------------------------------------------------------+
|               GitLab Canonical Source (Build & Sign)              |
|                                                                   |
|   1. Build ISO (mkarchiso + EROFS)                                |
|   2. Generate SBOM & SLSA v1.0 Provenance                        |
|   3. Sign Manifests & ISO (GnuPG: 2BDB00AE6CABEF0E40520A8F...)     |
|   4. Publish Release (GitLab Releases API)                        |
+---------------------------------+---------------------------------+
                                  |
                                  | CI Trigger (stage: release-mirror)
                                  v
+-------------------------------------------------------------------+
|                    Release Mirroring Engine                       |
|                                                                   |
|   [Release Metadata Discovery]                                   |
|        Query GitLab Releases API v4                               |
|        Enumerate asset links and payload direct URLs              |
|                                                                   |
|   [Streaming Download & Local Staging]                            |
|        Stream chunks to disk with free disk space checks          |
|        Validate size against GitHub 2 GiB limit                   |
|                                                                   |
|   [Mandatory Cryptographic Verification]                          |
|        Import release-signing-key.asc into isolated keyring       |
|        Verify primary fingerprint == TRUSTED_FINGERPRINT          |
|        Verify detached signature on SHA256SUMS                    |
|        Verify ISO detached signature (*.iso.sig)                  |
|        Verify all file digests against signed SHA256SUMS          |
|                                                                   |
|   [GitHub Release Synchronization]                                |
|        Find or create GitHub Release (initially draft=true)       |
|        Upload verified assets using streaming octet-stream        |
|        Post-upload asset size & name verification                 |
|        Atomic publication (draft=false)                           |
|                                                                   |
|   [GitLab Release Description Enrichment]                         |
|        Update GitLab release notes with GitHub mirror links       |
|        and dynamic live download count badge                      |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                   Public Analytics & Distribution                 |
|                                                                   |
|   - Native GitHub asset download_count                            |
|   - Public stats endpoint: public/stats.json                      |
|   - Dynamic SVG & Shields badges: public/badges/                  |
|   - Real-time download metrics dashboard: public/index.html       |
+-------------------------------------------------------------------+
```

---

## 2. Core Invariants

1. **GitLab is the Sole Source of Truth:**
   GitHub never independently builds, rebuilds, patches, or modifies release artifacts. GitHub strictly mirrors bit-for-bit verified binaries.
2. **Cryptographic Gate Before Ingestion:**
   No artifact is ever uploaded to GitHub without:
   - Verification of the checksum manifest signature against the trusted release signing key.
   - Verification of the ISO signature.
   - Exact digest match against the signed manifest.
3. **Release Immutability:**
   Once a tag is published on GitHub with verified assets, subsequent synchronizations are idempotent no-ops. If upstream assets are modified under the same tag, the pipeline fails closed with `ReleaseImmutableMutationError` rather than overwriting published binaries or resetting download counters.
4. **Draft-Safe Atomic Publication:**
   Releases are initially created on GitHub with `draft: true`. Only after all assets have been uploaded and their sizes verified against local source files is the release published (`draft: false`). This guarantees that public users and automated scrapers never see partial or broken releases.
5. **Native Download Telemetry:**
   GitHub's native asset `download_count` is the authoritative public download metric. No third-party database or server-side telemetry is introduced.

---

## 3. Subsystem Breakdown

### 3.1 `release_mirror.gitlab_client.GitLabClient`
- Communicates with GitLab REST API v4 (`/api/v4/projects/:id/releases`).
- Discovers release assets (both direct project upload URLs and Git LFS raw links).
- Provides streaming downloads to disk with chunked hash calculations (SHA-256 and BLAKE2b).
- Manages exponential backoff with random jitter on HTTP 429 and 5xx responses.
- Updates GitLab release notes with enriched download sections.

### 3.2 `release_mirror.github_client.GitHubClient`
- Communicates with GitHub Releases REST API (`/repos/:owner/:repo/releases`).
- Manages draft and published release states.
- Implements streaming asset uploads via GitHub's uploads endpoint (`uploads.github.com`).
- Enforces strict size pre-validation against GitHub's 2 GiB upload limit.
- Manages pagination using RFC 5988 `Link` headers.
- Handles rate-limiting using `x-ratelimit-remaining` and `x-ratelimit-reset` headers.

### 3.3 `release_mirror.verifier.CryptographicVerifier`
- Maintains an ephemeral, isolated GnuPG home directory (`GNUPGHOME`).
- Validates that imported release keys strictly match the canonical fingerprint:
  `2BDB00AE6CABEF0E40520A8F553FD42B02A8211A`.
- Verifies OpenPGP detached signatures for manifests, ISOs, and supplementary artifacts.
- Verifies SHA-256 and BLAKE2b file hashes against authoritative signed manifests.

### 3.4 `release_mirror.syncer.ReleaseSyncer`
- Coordinates the end-to-end synchronization pipeline.
- Implements idempotency: verifies existing GitHub assets, avoiding duplicate uploads.
- Recovers safely from partial uploads (deleting stale or size-mismatched assets).
- Handles oversized assets gracefully (keeping GitLab origin for assets > 2 GiB).
- Formats enriched release notes for GitLab.
- Guarantees immediate cleanup of temporary working files and isolated keyrings.

### 3.5 `release_mirror.stats.ReleaseStatsAggregator` & `BadgeGenerator`
- Aggregates live public GitHub release statistics without requiring authentication.
- Distinguishes ISO downloads from supplementary files (checksums, SBOM, signatures).
- Segregates stable releases from candidate prereleases.
- Generates static `public/stats.json` for frontend consumption.
- Generates embeddable SVG badges and Shields.io endpoint JSON files.
