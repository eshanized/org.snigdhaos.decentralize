"""
Cryptographic verification engine for Snigdha OS Decentralized releases.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Set, Tuple

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import (
    ChecksumMismatchError,
    SignatureVerificationError,
    UntrustedKeyError,
    VerificationError,
)

logger = logging.getLogger("release_mirror.verifier")


class CryptographicVerifier:
    """Verifies file digests, manifests, and OpenPGP signatures."""

    def __init__(self, config: MirrorConfig):
        self.config = config
        self.trusted_fingerprint = config.trusted_signing_key_fingerprint.replace(" ", "").upper()
        self.gnupg_home: Optional[str] = None
        self._temp_gnupg = False

    def setup_gnupg(self, gnupg_dir: Optional[str] = None) -> str:
        """Create or configure an isolated GnuPG home directory."""
        if gnupg_dir and os.path.isdir(gnupg_dir):
            self.gnupg_home = gnupg_dir
            self._temp_gnupg = False
        else:
            self.gnupg_home = tempfile.mkdtemp(prefix="snigdha_gpg_")
            self._temp_gnupg = True
        return self.gnupg_home

    def cleanup_gnupg(self) -> None:
        """Clean up temporary GnuPG home directory."""
        if self._temp_gnupg and self.gnupg_home and os.path.exists(self.gnupg_home):
            try:
                shutil.rmtree(self.gnupg_home)
            except OSError:
                pass
            self.gnupg_home = None
            self._temp_gnupg = False

    def import_key(self, key_file: str) -> str:
        """
        Import an OpenPGP public key into the isolated keyring, verifying its
        primary fingerprint against the configured trusted fingerprint.
        """
        if not self.gnupg_home:
            self.setup_gnupg()

        if not os.path.isfile(key_file):
            raise FileNotFoundError(f"Key file not found: {key_file}")

        # Check key fingerprint before or during import
        cmd_show = ["gpg", "--with-colons", "--show-keys", key_file]
        proc_show = subprocess.run(
            cmd_show, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        if proc_show.returncode != 0:
            raise VerificationError(f"Failed to read GPG key: {proc_show.stderr}")

        imported_fpr = ""
        for line in proc_show.stdout.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr" and len(parts) >= 10:
                fpr = parts[9].strip().upper()
                if fpr == self.trusted_fingerprint:
                    imported_fpr = fpr
                    break
                elif not imported_fpr:
                    imported_fpr = fpr

        if imported_fpr != self.trusted_fingerprint:
            raise UntrustedKeyError(
                f"Release key fingerprint '{imported_fpr}' does NOT match configured trusted "
                f"fingerprint '{self.trusted_fingerprint}'! Untrusted key rejected."
            )

        env = os.environ.copy()
        env["GNUPGHOME"] = self.gnupg_home
        cmd_import = ["gpg", "--batch", "--quiet", "--import", key_file]
        proc = subprocess.run(cmd_import, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise VerificationError(f"Failed to import trusted key into keyring: {proc.stderr}")

        logger.info("Successfully imported and verified trusted key: %s", imported_fpr)
        return imported_fpr

    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA-256 digest of a local file in chunks."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(self.config.chunk_size_bytes):
                sha256.update(chunk)
        return sha256.hexdigest()

    def compute_blake2b(self, file_path: str) -> str:
        """Compute BLAKE2b digest of a local file in chunks."""
        b2 = hashlib.blake2b()
        with open(file_path, "rb") as f:
            while chunk := f.read(self.config.chunk_size_bytes):
                b2.update(chunk)
        return b2.hexdigest()

    def parse_checksum_file(self, manifest_path: str) -> Dict[str, str]:
        """Parse standard checksum file (SHA256SUMS / BLAKE2SUMS) into {filename: digest}."""
        checksums: Dict[str, str] = {}
        if not os.path.isfile(manifest_path):
            raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Line format: <digest>  <filename> or <digest> *<filename>
                parts = line.split(None, 1)
                if len(parts) == 2:
                    digest = parts[0].strip().lower()
                    fname = os.path.basename(parts[1].strip().lstrip("*"))
                    checksums[fname] = digest
        return checksums

    def verify_signature(self, sig_file: str, data_file: str) -> bool:
        """
        Verify a detached OpenPGP signature against data_file using the trusted keyring.
        Ensures the signing key primary fingerprint matches the trusted fingerprint.
        """
        if not self.gnupg_home:
            self.setup_gnupg()

        if not os.path.isfile(sig_file):
            raise FileNotFoundError(f"Signature file not found: {sig_file}")
        if not os.path.isfile(data_file):
            raise FileNotFoundError(f"Data file not found: {data_file}")

        env = os.environ.copy()
        env["GNUPGHOME"] = self.gnupg_home
        cmd = ["gpg", "--batch", "--status-fd", "1", "--verify", sig_file, data_file]
        proc = subprocess.run(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )

        valid_sig = False
        signer_fpr = ""
        good_sig = False

        for line in proc.stdout.splitlines():
            if line.startswith("[GNUPG:] GOODSIG"):
                good_sig = True
            elif line.startswith("[GNUPG:] VALIDSIG"):
                parts = line.split()
                if len(parts) >= 3:
                    signer_fpr = parts[2].strip().upper()
                if len(parts) >= 12 and parts[11].strip().upper() == self.trusted_fingerprint:
                    valid_sig = True
                elif signer_fpr == self.trusted_fingerprint:
                    valid_sig = True

        if proc.returncode != 0 or not good_sig:
            raise SignatureVerificationError(
                f"GPG signature verification failed for {os.path.basename(data_file)} with "
                f"signature {os.path.basename(sig_file)}.\nGPG output: {proc.stderr or proc.stdout}"
            )

        if not valid_sig:
            raise UntrustedKeyError(
                f"Signature on {os.path.basename(data_file)} made by untrusted key {signer_fpr}! "
                f"Expected primary fingerprint: {self.trusted_fingerprint}"
            )

        logger.info(
            "GPG signature verified: %s -> %s (trusted signer: %s)",
            os.path.basename(sig_file), os.path.basename(data_file), self.trusted_fingerprint
        )
        return True

    def verify_release_bundle(
        self,
        files_by_name: Dict[str, str],
        authoritative_manifest_name: str = "SHA256SUMS",
    ) -> Dict[str, str]:
        """
        Execute comprehensive cryptographic verification across the release bundle:
        1. Import trusted public key from release bundle (or key directory) and verify fingerprint.
        2. Verify detached signature of SHA256SUMS.
        3. Parse SHA256SUMS manifest.
        4. Verify ISO SHA-256 against SHA256SUMS.
        5. Verify ISO detached signature (.iso.sig).
        6. Verify all auxiliary files against SHA256SUMS.
        7. Verify additional detached signatures if available.

        Returns: Dict of verified {filename: sha256_digest}.
        """
        verified_digests: Dict[str, str] = {}

        # 1. Setup keyring and import key
        key_file = files_by_name.get("release-signing-key.asc")
        if key_file and os.path.isfile(key_file):
            self.import_key(key_file)
        else:
            raise VerificationError("Missing required signing key 'release-signing-key.asc' in release bundle.")

        # 2. Verify SHA256SUMS signature
        manifest_path = files_by_name.get(authoritative_manifest_name)
        manifest_sig = files_by_name.get(f"{authoritative_manifest_name}.sig")

        if not manifest_path or not os.path.isfile(manifest_path):
            raise VerificationError(f"Authoritative manifest '{authoritative_manifest_name}' is missing.")
        if not manifest_sig or not os.path.isfile(manifest_sig):
            raise VerificationError(f"Signature for manifest '{authoritative_manifest_name}.sig' is missing.")

        self.verify_signature(manifest_sig, manifest_path)
        manifest_digests = self.parse_checksum_file(manifest_path)

        # 3. Locate and verify ISO
        iso_name = None
        for name in files_by_name:
            if name.endswith(".iso"):
                iso_name = name
                break

        if not iso_name:
            raise VerificationError("No bootable ISO image found in release bundle.")

        iso_path = files_by_name[iso_name]
        iso_sig = files_by_name.get(f"{iso_name}.sig")

        if not iso_sig or not os.path.isfile(iso_sig):
            raise VerificationError(f"Missing detached signature for ISO: '{iso_name}.sig'")

        # Verify ISO detached signature
        self.verify_signature(iso_sig, iso_path)

        # Verify ISO SHA-256 digest
        computed_iso_sha256 = self.compute_sha256(iso_path)
        expected_iso_sha256 = manifest_digests.get(iso_name)
        if not expected_iso_sha256:
            raise VerificationError(f"ISO '{iso_name}' is not listed in {authoritative_manifest_name}!")
        if computed_iso_sha256.lower() != expected_iso_sha256.lower():
            raise ChecksumMismatchError(
                f"SHA-256 mismatch for ISO {iso_name}: "
                f"computed {computed_iso_sha256} != expected {expected_iso_sha256}"
            )
        verified_digests[iso_name] = computed_iso_sha256
        logger.info("ISO verified successfully: %s (%s)", iso_name, computed_iso_sha256)

        # 4. Verify all files listed in SHA256SUMS
        for filename, expected_digest in manifest_digests.items():
            if filename == iso_name:
                continue
            if filename in files_by_name:
                fpath = files_by_name[filename]
                comp_sha = self.compute_sha256(fpath)
                if comp_sha.lower() != expected_digest.lower():
                    raise ChecksumMismatchError(
                        f"SHA-256 mismatch for {filename}: computed {comp_sha} != expected {expected_digest}"
                    )
                verified_digests[filename] = comp_sha
                logger.info("Asset verified against manifest: %s (%s)", filename, comp_sha)

                # Check if asset has detached signature and verify it
                asset_sig = files_by_name.get(f"{filename}.sig")
                if asset_sig and os.path.isfile(asset_sig):
                    self.verify_signature(asset_sig, fpath)

        return verified_digests
