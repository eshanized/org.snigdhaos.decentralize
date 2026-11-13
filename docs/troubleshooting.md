# Troubleshooting & Diagnostics Guide

**Project:** Snigdha OS Decentralized  
**Tool:** `release-mirror` CLI & Python Engine  
**License:** GPL-3.0-or-later  

---

## 1. Common Operational Errors & Resolutions

### 1.1 `UntrustedKeyError: Release key fingerprint does NOT match`
- **Cause:** The `release-signing-key.asc` attached to the GitLab release does not match the canonical primary fingerprint `2BDB00AE6CABEF0E40520A8F553FD42B02A8211A`.
- **Diagnostic Command:**
  ```bash
  gpg --show-keys release-signing-key.asc
  ```
- **Resolution:** Verify whether dev or production keys were used during `make trust-sign`. Ensure the GitLab CI variable `TRUSTED_SIGNING_KEY_FINGERPRINT` matches the signing authority.

---

### 1.2 `ChecksumMismatchError: SHA-256 mismatch for ...`
- **Cause:** An asset was modified or regenerated after `SHA256SUMS` was generated and signed.
- **Diagnostic Command:**
  ```bash
  sha256sum <filename>
  grep <filename> SHA256SUMS
  ```
- **Resolution:** Re-execute the upstream supply-chain signing pipeline (`make trust-sign` and `scripts/release-publish.sh --force-tag`) to ensure all manifests and detached signatures are generated atomically against identical files.

---

### 1.3 `GitHubAPIError [403]: API rate limit exceeded`
- **Cause:** Unauthenticated GitHub API calls exceeded the 60 requests/hour IP limit, or a GitHub Actions runner made high volumes of requests.
- **Resolution:**
  - Provide a valid token in `GITHUB_RELEASE_TOKEN` or `GITHUB_TOKEN` to elevate the limit to 5,000 requests/hour.
  - The client automatically checks `x-ratelimit-reset` and pauses until the quota resets.

---

### 1.4 `GitHubAPIError [401]: Bad credentials`
- **Cause:** The GitHub PAT is missing, expired, or revoked.
- **Resolution:** Follow [docs/github-authentication.md](file:///home/snigdha/Desktop/gh/org.snigdhaos.decentralize/docs/github-authentication.md) to generate a new Fine-Grained token with `Contents: Read and Write` and update `GITHUB_RELEASE_TOKEN` in GitLab CI variables.

---

### 1.5 `AssetOversizedError: Asset size exceeds GitHub's limit`
- **Cause:** An ISO or archive exceeded GitHub's single asset ceiling of 2.00 GiB (2,147,483,648 bytes).
- **Resolution:**
  - The mirror engine automatically leaves oversized ISOs hosted on GitLab and notes this in the release description.
  - Optimize the root filesystem in `profile/airootfs` or review included packages in `profile/packages.x86_64`.

---

### 1.6 Interrupted / Stale Partial Release Drafts
- **Cause:** A network failure or timeout interrupted asset uploads midway through synchronization.
- **Resolution:**
  - Simply re-run the mirror command:
    ```bash
    release-mirror sync --tag <tag>
    ```
  - The syncer detects the existing draft, cleans up any size-mismatched assets, uploads missing files, and publishes the release atomically once all files verify.
