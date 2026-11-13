# Operations & Maintenance Guide

**Project:** Snigdha OS Decentralized  
**Tool:** `release-mirror` CLI  
**License:** GPL-3.0-or-later  

---

## 1. Operational Overview

While the mirroring system runs automatically in GitLab CI, release managers can execute manual synchronizations, health inspections, and cryptographic verifications using the `release-mirror` CLI.

---

## 2. CLI Command Reference

### 2.1 Release Synchronization (`sync`)
Synchronizes a release from GitLab to GitHub.

```bash
# Basic synchronization
release-mirror sync --tag v2026.11.13-rc1

# Dry-run mode (validates metadata and logs planned actions without mutation)
release-mirror sync --tag v2026.11.13-rc1 --dry-run

# Synchronize without modifying GitLab release notes
release-mirror sync --tag v2026.11.13-rc1 --no-gitlab-update

# Verbose debug logging
release-mirror -v sync --tag v2026.11.13-rc1
```

---

### 2.2 Cryptographic Verification (`verify`)
Downloads assets directly from GitLab and executes the complete cryptographic validation suite against trusted keys.

```bash
release-mirror verify --tag v2026.11.13-rc1
```

*Example Output:*
```text
=== Cryptographic Verification for Tag: v2026.11.13-rc1 ===
Trusted Key Fingerprint: 2BDB00AE6CABEF0E40520A8F553FD42B02A8211A
  Downloading release-signing-key.asc...
  Downloading SHA256SUMS...
  Downloading SHA256SUMS.sig...
  Downloading snigdhaos-decentralize-2026.11.13-x86_64.iso...
  Downloading snigdhaos-decentralize-2026.11.13-x86_64.iso.sig...

=== Verification Verdict: PASS ===
All signatures and SHA-256 manifests verified against the trusted release key.
  ✓ snigdhaos-decentralize-2026.11.13-x86_64.iso: d478995adc24220c2995a78f7b0918f1c94b16d5af32e1ca141ddf9d1f65e197
  ✓ SHA256SUMS: verified (signature valid)
```

---

### 2.3 Download Statistics (`stats`)
Fetches public GitHub release metrics, aggregates downloads, and generates static JSON and badges.

```bash
# Display summary table in terminal
release-mirror stats

# Output raw JSON
release-mirror stats --format json

# Write stats.json and regenerate badges
release-mirror stats --output public/stats.json --badges-dir public/badges
```

---

### 2.4 Release Inspection (`inspect`)
Queries both GitLab and GitHub to compare synchronization state, asset counts, sizes, and published URLs.

```bash
release-mirror inspect --tag v2026.11.13-rc1
```

*Example Output:*
```text
=== Release Inspection for Tag: v2026.11.13-rc1 ===

--- GitLab Source Release ---
Title:        Snigdha OS Decentralized 2026.11.13-rc1 (Release Candidate 1)
Tag:          v2026.11.13-rc1
Created:      2026-11-13T05:30:12.442Z
Released:     2026-11-13T05:30:12.442Z
Asset links:  15
  • release-key.fpr -> https://gitlab.com/...
  • release-signing-key.asc -> https://gitlab.com/...
  • snigdhaos-decentralize-2026.11.13-x86_64.iso -> https://gitlab.com/...

--- GitHub Target Mirror Release ---
ID:           12345678
Title:        Snigdha OS Decentralized 2026.11.13-rc1 (Release Candidate 1)
Draft:        False
Prerelease:   True
HTML URL:     https://github.com/eshanized/org.snigdhaos.decentralize/releases/tag/v2026.11.13-rc1
Assets:       15
  • snigdhaos-decentralize-2026.11.13-x86_64.iso (1,482,342,400 bytes, 1420 downloads)
  • SHA256SUMS (370 bytes, 312 downloads)
```

---

## 3. Routine Maintenance & Health Checks

- **Daily Automation:** The GitHub Actions workflow `.github/workflows/stats-updater.yml` automatically updates `public/stats.json` and SVG badges every 6 hours.
- **Key Expiration Monitoring:** The canonical release signing key (`2BDB00AE6CABEF0E40520A8F553FD42B02A8211A`) expires on `2028-11-10`. Key ceremony extensions should be initiated 90 days prior to expiration.
