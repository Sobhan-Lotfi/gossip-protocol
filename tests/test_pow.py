"""Tests for Proof of Work compute, verify, and benchmark functions."""

import pytest

from gossip.pow import benchmark_pow, compute_pow, verify_pow


def test_compute_pow_k1():
    nonce, digest = compute_pow("test-node-id", 1)
    assert digest.startswith("0")
    assert digest == _sha256(f"test-node-id{nonce}")


def test_compute_pow_k2():
    nonce, digest = compute_pow("node-abc", 2)
    assert digest.startswith("00")
    assert digest == _sha256(f"node-abc{nonce}")


def test_compute_pow_k3():
    nonce, digest = compute_pow("short", 3)
    assert digest.startswith("000")


def test_compute_pow_k0():
    """k=0 means any nonce is valid (starts with '' which everything does)."""
    nonce, digest = compute_pow("any-node", 0)
    assert nonce == 0  # first nonce always matches


def test_verify_pow_accepts_valid():
    nonce, digest = compute_pow("test-node-id", 2)
    assert verify_pow("test-node-id", nonce, digest, 2)


def test_verify_pow_rejects_tampered_nonce():
    nonce, digest = compute_pow("test-node-id", 2)
    assert not verify_pow("test-node-id", nonce + 1, digest, 2)


def test_verify_pow_rejects_wrong_digest():
    nonce, digest = compute_pow("test-node-id", 2)
    assert not verify_pow("test-node-id", nonce, "00" + "x" * 62, 2)


def test_verify_pow_rejects_insufficient_zeros():
    nonce, digest = compute_pow("test-node-id", 2)
    # The digest starts with '00', but we require 3 zeros → should fail
    assert not verify_pow("test-node-id", nonce, digest, 3)


def test_verify_pow_rejects_wrong_node_id():
    nonce, digest = compute_pow("test-node-id", 2)
    assert not verify_pow("wrong-node-id", nonce, digest, 2)


def test_benchmark_pow_returns_expected_keys():
    result = benchmark_pow(1, trials=3)
    assert "mean" in result
    assert "std" in result
    assert "min" in result
    assert "max" in result
    assert result["trials"] == 3
    assert result["difficulty_k"] == 1
    assert result["mean"] >= 0
    assert result["min"] <= result["mean"] <= result["max"]


# ── Helper ────────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
