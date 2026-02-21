"""Orchestrate full experiments: launch N nodes, inject gossip, collect logs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time


def send_trigger(port: int, data: str) -> None:
    """Send a TRIGGER UDP message to the node at localhost:port."""
    payload = {
        "version": 1,
        "msg_id": "trigger-00000000-0000-0000-0000-000000000000",
        "msg_type": "TRIGGER",
        "sender_id": "simulator",
        "sender_addr": "127.0.0.1:0",
        "timestamp_ms": int(time.time() * 1000),
        "ttl": 0,
        "payload": {"data": data},
    }
    data_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(data_bytes, ("127.0.0.1", port))
    finally:
        sock.close()


def run_experiment(
    n: int,
    fanout: int,
    ttl: int,
    mode: str,
    seed: int,
    peer_limit: int,
    ping_interval: float,
    peer_timeout: float,
    pow_k: int,
    stabilize_time: float,
    gossip_wait: float,
    log_dir: str,
    results_base: str,
) -> str:
    """Launch N nodes, inject gossip, wait, terminate, and move logs. Returns results path."""
    seed_log_dir = os.path.join(log_dir, str(seed))
    os.makedirs(seed_log_dir, exist_ok=True)

    python = sys.executable
    base_port = 9000
    processes: list[subprocess.Popen] = []

    # Launch bootstrap node (port 9000)
    bootstrap_cmd = [
        python, "-m", "gossip.node",
        "--port", str(base_port),
        "--fanout", str(fanout),
        "--ttl", str(ttl),
        "--seed", str(seed),
        "--mode", mode,
        "--pow-k", str(pow_k),
        "--peer-limit", str(peer_limit),
        "--ping-interval", str(ping_interval),
        "--peer-timeout", str(peer_timeout),
        "--log-dir", seed_log_dir,
    ]
    processes.append(subprocess.Popen(bootstrap_cmd, stdin=subprocess.DEVNULL))
    time.sleep(0.3)

    # Launch remaining nodes
    for i in range(1, n):
        port = base_port + i
        node_cmd = [
            python, "-m", "gossip.node",
            "--port", str(port),
            "--bootstrap", f"127.0.0.1:{base_port}",
            "--fanout", str(fanout),
            "--ttl", str(ttl),
            "--seed", str(seed),
            "--mode", mode,
            "--pow-k", str(pow_k),
            "--peer-limit", str(peer_limit),
            "--ping-interval", str(ping_interval),
            "--peer-timeout", str(peer_timeout),
            "--log-dir", seed_log_dir,
        ]
        processes.append(subprocess.Popen(node_cmd, stdin=subprocess.DEVNULL))
        time.sleep(0.05)

    print(f"  Launched {n} nodes, waiting {stabilize_time}s to stabilize...")
    time.sleep(stabilize_time)

    # Inject gossip via TRIGGER
    trigger_data = f"EXPERIMENT_PAYLOAD_{seed}"
    send_trigger(base_port, trigger_data)
    print(f"  Injected gossip: {trigger_data!r}, waiting {gossip_wait}s for propagation...")
    time.sleep(gossip_wait)

    # Graceful shutdown
    for proc in processes:
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass

    for proc in processes:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Move logs to results
    results_path = os.path.join(results_base, f"{mode}_n{n}_f{fanout}_t{ttl}_s{seed}")
    if os.path.exists(results_path):
        shutil.rmtree(results_path)
    shutil.move(seed_log_dir, results_path)
    print(f"  Logs saved to {results_path}")
    return results_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate gossip network experiments")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--fanout", type=int, default=3)
    parser.add_argument("--ttl", type=int, default=8)
    parser.add_argument("--mode", type=str, default="push", choices=["push", "hybrid"])
    parser.add_argument("--seeds", type=str, default="42,43,44,45,46")
    parser.add_argument("--peer-limit", type=int, default=20)
    parser.add_argument("--ping-interval", type=float, default=2.0)
    parser.add_argument("--peer-timeout", type=float, default=6.0)
    parser.add_argument("--pow-k", type=int, default=0)
    parser.add_argument("--stabilize-time", type=float, default=5.0)
    parser.add_argument("--gossip-wait", type=float, default=10.0)
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--results-dir", type=str, default="results")
    parser.add_argument("--run-all", action="store_true",
                        help="Run the full experiment suite: N×mode sweep and fanout sweep")
    args = parser.parse_args()

    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    os.makedirs(args.log_dir, exist_ok=True)
    os.makedirs(args.results_dir, exist_ok=True)

    if args.run_all:
        # Group 1: N=10,20,50 × mode=push,hybrid × seeds, fanout=3, ttl=8
        for n in [10, 20, 50]:
            for mode in ["push", "hybrid"]:
                for seed in seeds:
                    print(f"Running experiment: n={n}, fanout=3, ttl=8, mode={mode}, seed={seed}")
                    run_experiment(
                        n=n,
                        fanout=3,
                        ttl=8,
                        mode=mode,
                        seed=seed,
                        peer_limit=args.peer_limit,
                        ping_interval=args.ping_interval,
                        peer_timeout=args.peer_timeout,
                        pow_k=args.pow_k,
                        stabilize_time=args.stabilize_time,
                        gossip_wait=args.gossip_wait,
                        log_dir=args.log_dir,
                        results_base=args.results_dir,
                    )
        # Group 2: N=50 × fanout=2,5 × mode=push × seeds, ttl=8
        # (fanout=3 already covered in group 1)
        for fanout in [2, 5]:
            for seed in seeds:
                print(f"Running experiment: n=50, fanout={fanout}, ttl=8, mode=push, seed={seed}")
                run_experiment(
                    n=50,
                    fanout=fanout,
                    ttl=8,
                    mode="push",
                    seed=seed,
                    peer_limit=args.peer_limit,
                    ping_interval=args.ping_interval,
                    peer_timeout=args.peer_timeout,
                    pow_k=args.pow_k,
                    stabilize_time=args.stabilize_time,
                    gossip_wait=args.gossip_wait,
                    log_dir=args.log_dir,
                    results_base=args.results_dir,
                )
    else:
        for seed in seeds:
            print(f"Running experiment: n={args.n}, fanout={args.fanout}, ttl={args.ttl}, mode={args.mode}, seed={seed}")
            run_experiment(
                n=args.n,
                fanout=args.fanout,
                ttl=args.ttl,
                mode=args.mode,
                seed=seed,
                peer_limit=args.peer_limit,
                ping_interval=args.ping_interval,
                peer_timeout=args.peer_timeout,
                pow_k=args.pow_k,
                stabilize_time=args.stabilize_time,
                gossip_wait=args.gossip_wait,
                log_dir=args.log_dir,
                results_base=args.results_dir,
            )


if __name__ == "__main__":
    main()
