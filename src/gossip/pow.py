"""Proof of Work: compute, verify, and benchmark SHA-256 based PoW."""

from __future__ import annotations

import hashlib
import statistics
import time


def _sha256_hex(node_id: str, nonce: int) -> str:
    """Return hex digest of SHA-256(node_id + str(nonce))."""
    data = f"{node_id}{nonce}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_pow(node_id: str, difficulty_k: int) -> tuple[int, str]:
    """Find nonce where SHA256(node_id + str(nonce)) hex starts with k zeros.

    Returns (nonce, digest_hex).
    """
    prefix = "0" * difficulty_k
    nonce = 0
    while True:
        digest = _sha256_hex(node_id, nonce)
        if digest.startswith(prefix):
            return nonce, digest
        nonce += 1


def verify_pow(node_id: str, nonce: int, digest_hex: str, difficulty_k: int) -> bool:
    """Verify that the given nonce and digest constitute a valid PoW proof."""
    expected = _sha256_hex(node_id, nonce)
    if expected != digest_hex:
        return False
    return digest_hex.startswith("0" * difficulty_k)


def benchmark_pow(difficulty_k: int, trials: int = 10) -> dict:
    """Return mean, std, min, max times in seconds for compute_pow at given difficulty."""
    times: list[float] = []
    test_id = "benchmark_node"
    for i in range(trials):
        start = time.time()
        compute_pow(f"{test_id}_{i}", difficulty_k)
        times.append(time.time() - start)
    return {
        "difficulty_k": difficulty_k,
        "trials": trials,
        "mean": statistics.mean(times),
        "std": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min": min(times),
        "max": max(times),
    }
