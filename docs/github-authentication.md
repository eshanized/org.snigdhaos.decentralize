# GitHub Authentication & Security Specification

**Project:** Snigdha OS Decentralized  
**Target Repository:** `https://github.com/eshanized/org.snigdhaos.decentralize`  
**License:** GPL-3.0-or-later  

---

## 1. Authentication Strategy

The release mirroring engine communicates with the GitHub REST API using a dedicated GitHub Personal Access Token (PAT) supplied via the `GITHUB_RELEASE_TOKEN` environment variable.

The system adheres to the Principle of Least Privilege:
- **No administrative rights** are requested.
- **No repository deletion** or setting modifications are permitted.
- The token is restricted strictly to release and content management on the target repository.

---

## 2. Token Permission Requirements

### 2.1 Fine-Grained Personal Access Token (Recommended)
When generating a Fine-Grained Personal Access Token under GitHub **Settings > Developer Settings > Personal access tokens > Fine-grained tokens**:

1. **Repository Access:** Select **Only select repositories** -> `eshanized/org.snigdhaos.decentralize`.
2. **Repository Permissions:**
   - **Contents:** `Read and Write` (Required to create releases and upload binary assets).
   - **Metadata:** `Read-only` (Mandatory default for all fine-grained tokens).
3. **Account Permissions:** None.

### 2.2 Classic Personal Access Token (Alternative)
If using a Classic Personal Access Token:
- Scope: `repo` (Full control of private repositories) or `public_repo` (Access to public repositories).

---

## 3. Secret Leak Prevention Rules

1. **Masked GitLab Variable:**
   The token must be configured in GitLab CI as **Masked** and **Protected**. This prevents GitLab runners from printing the secret string in pipeline traces even if an error occurs.
2. **In-Code Sanitization (`config.mask_secrets`):**
   The `release_mirror` codebase implements active regex-based token redacting across all logs, error traces, HTTP exception bodies, and debugging output.
3. **No Credential Persistence:**
   Tokens are passed directly in memory via HTTP request headers (`Authorization: Bearer <token>`). No tokens are written to disk, committed to Git, or stored in temporary directories.
4. **Isolated Keyrings:**
   GnuPG keyrings are created in ephemeral temporary folders and destroyed immediately upon task termination (`shutil.rmtree`).

---

## 4. Token Rotation Procedure

To rotate an expiring or compromised token:
1. Generate a new Fine-Grained PAT on GitHub with `Contents: Read and Write` on `eshanized/org.snigdhaos.decentralize`.
2. In GitLab, navigate to `https://gitlab.com/SnigdhaOS/decentralize/iso/-/settings/ci_cd`.
3. Expand **Variables**, locate `GITHUB_RELEASE_TOKEN`, click **Edit**, and replace the value.
4. Verify by running a dry-run test:
   ```bash
   release-mirror sync --tag <latest-tag> --dry-run
   ```
5. Revoke the old token on GitHub.
