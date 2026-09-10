"""HMAC X-Hub-Signature-256 verification tests (webhook_receiver.github)."""

from __future__ import annotations

import hashlib
import hmac

from webhook_receiver.github import compute_signature, verify_signature

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"
BODY = b'{"action": "labeled"}'


class TestComputeSignature:
    def test_matches_hmac_sha256(self) -> None:
        expected = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        assert compute_signature(BODY, SECRET) == f"sha256={expected}"

    def test_differs_per_body(self) -> None:
        assert compute_signature(BODY, SECRET) != compute_signature(b"other", SECRET)


class TestVerifySignature:
    def test_valid_signature_accepted(self) -> None:
        sig = compute_signature(BODY, SECRET)
        assert verify_signature(BODY, sig, SECRET) is True

    def test_wrong_secret_rejected(self) -> None:
        sig = compute_signature(BODY, "other-secret")
        assert verify_signature(BODY, sig, SECRET) is False

    def test_tampered_body_rejected(self) -> None:
        sig = compute_signature(BODY, SECRET)
        assert verify_signature(b'{"action": "hacked"}', sig, SECRET) is False

    def test_missing_header_rejected(self) -> None:
        assert verify_signature(BODY, None, SECRET) is False

    def test_empty_header_rejected(self) -> None:
        assert verify_signature(BODY, "", SECRET) is False

    def test_non_sha256_prefix_rejected(self) -> None:
        assert verify_signature(BODY, "md5=deadbeef", SECRET) is False

    def test_malformed_hex_rejected(self) -> None:
        assert verify_signature(BODY, "sha256=zzzz-not-hex", SECRET) is False
