"""
Tests for cryptographic verifier: digests, manifests, GPG signatures, and key trust.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from release_mirror.config import MirrorConfig
from release_mirror.exceptions import (
    ChecksumMismatchError,
    SignatureVerificationError,
    UntrustedKeyError,
    VerificationError,
)
from release_mirror.verifier import CryptographicVerifier


class TestCryptographicVerifier(unittest.TestCase):

    def setUp(self):
        self.config = MirrorConfig.from_env()
        self.config.trusted_signing_key_fingerprint = "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A"
        self.verifier = CryptographicVerifier(self.config)

    def tearDown(self):
        self.verifier.cleanup_gnupg()

    def test_compute_sha256_and_blake2b(self):
        content = b"Snigdha OS cryptographic verification test block"
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(content)
            tf_path = tf.name

        try:
            sha = self.verifier.compute_sha256(tf_path)
            b2 = self.verifier.compute_blake2b(tf_path)
            self.assertEqual(sha, hashlib.sha256(content).hexdigest())
            self.assertEqual(b2, hashlib.blake2b(content).hexdigest())
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_parse_checksum_file(self):
        manifest_content = (
            "d478995adc24220c2995a78f7b0918f1c94b16d5af32e1ca141ddf9d1f65e197  snigdhaos.iso\n"
            "594a762dcf97fb9b93b645ea7b26d3142645c945070730b83a0e8dd7c316ac8c *release-manifest.json\n"
            "# Comment line\n"
            "\n"
        )
        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write(manifest_content)
            tf_path = tf.name

        try:
            parsed = self.verifier.parse_checksum_file(tf_path)
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed["snigdhaos.iso"], "d478995adc24220c2995a78f7b0918f1c94b16d5af32e1ca141ddf9d1f65e197")
            self.assertEqual(parsed["release-manifest.json"], "594a762dcf97fb9b93b645ea7b26d3142645c945070730b83a0e8dd7c316ac8c")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("subprocess.run")
    def test_import_key_untrusted_fingerprint_rejection(self, mock_run):
        # Return a different fingerprint
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="fpr:::::::::1111222233334444555566667777888899990000:\n",
            stderr=""
        )

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf_path = tf.name

        try:
            with self.assertRaises(UntrustedKeyError):
                self.verifier.import_key(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("subprocess.run")
    def test_import_key_trusted_success(self, mock_run):
        trusted_fpr = "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A"
        mock_show = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"fpr:::::::::{trusted_fpr}:\n",
            stderr=""
        )
        mock_import = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        mock_run.side_effect = [mock_show, mock_import]

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf_path = tf.name

        try:
            imported = self.verifier.import_key(tf_path)
            self.assertEqual(imported, trusted_fpr)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("subprocess.run")
    def test_verify_signature_bad_signature_rejection(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="[GNUPG:] BADSIG 44F123CB101F8F0F\n",
            stderr="gpg: BAD signature"
        )
        with tempfile.NamedTemporaryFile(delete=False) as sig_f, tempfile.NamedTemporaryFile(delete=False) as data_f:
            sig_path = sig_f.name
            data_path = data_f.name

        try:
            with self.assertRaises(SignatureVerificationError):
                self.verifier.verify_signature(sig_path, data_path)
        finally:
            for p in (sig_path, data_path):
                if os.path.exists(p):
                    os.remove(p)

    @patch("subprocess.run")
    def test_verify_signature_trusted_signer_pass(self, mock_run):
        trusted_fpr = "2BDB00AE6CABEF0E40520A8F553FD42B02A8211A"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"[GNUPG:] GOODSIG 44F123CB101F8F0F test\n[GNUPG:] VALIDSIG {trusted_fpr} 2026-11-13 ... {trusted_fpr}\n",
            stderr=""
        )
        with tempfile.NamedTemporaryFile(delete=False) as sig_f, tempfile.NamedTemporaryFile(delete=False) as data_f:
            sig_path = sig_f.name
            data_path = data_f.name

        try:
            verified = self.verifier.verify_signature(sig_path, data_path)
            self.assertTrue(verified)
        finally:
            for p in (sig_path, data_path):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
