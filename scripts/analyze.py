"""Parse experiment logs, compute metrics, and generate matplotlib plots."""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_events(results_dir: str) -> list[dict[str, Any]]:
    """Load all JSON-line events from a single experiment directory."""
    events: list[dict[str, Any]] = []
    for fname in os.listdir(results_dir):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(results_dir, fname)
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def compute_convergence_and_overhead(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute convergence time and message overhead from log events.

    Returns dict with keys: convergence_time (float|None), message_overhead (int).
    """
    # Find the GOSSIP_ORIGIN event
    origin_ts: float | None = None
    origin_msg_id: str | None = None
    for ev in events:
        if ev.get("event") == "GOSSIP_ORIGIN":
            origin_ts = ev["ts"]
            origin_msg_id = ev.get("msg_id")
            break

    if origin_ts is None or origin_msg_id is None:
        return {"convergence_time": None, "message_overhead": 0}

    # Collect per-node receive times for origin_msg_id
    # Key: node_id -> earliest recv ts
    recv_times: dict[str, float] = {}
    for ev in events:
        if ev.get("event") in ("GOSSIP_RECV", "GOSSIP_ORIGIN") and ev.get("msg_id") == origin_msg_id:
            nid = ev["node_id"]
            t = ev["ts"]
            if nid not in recv_times or t < recv_times[nid]:
                recv_times[nid] = t

    if not recv_times:
        return {"convergence_time": None, "message_overhead": 0}

    n = len(recv_times)
    target = math.ceil(0.95 * n)
    sorted_times = sorted(recv_times.values())

    if len(sorted_times) < target:
        convergence_ts = sorted_times[-1]
    else:
        convergence_ts = sorted_times[target - 1]

    convergence_time = convergence_ts - origin_ts

    # Count MSG_SENT between origin_ts and convergence_ts
    overhead = sum(
        1
        for ev in events
        if ev.get("event") == "MSG_SENT" and origin_ts <= ev["ts"] <= convergence_ts
    )

    return {"convergence_time": convergence_time, "message_overhead": overhead}


def scan_experiments(results_dir: str) -> list[dict[str, Any]]:
    """Scan a results directory and parse metrics from each sub-experiment."""
    experiments: list[dict[str, Any]] = []
    for dname in os.listdir(results_dir):
        dpath = os.path.join(results_dir, dname)
        if not os.path.isdir(dpath):
            continue
        # Expected format: mode_nN_fF_tT_sS
        parts = dname.split("_")
        meta: dict[str, Any] = {"dir": dpath, "name": dname}
        for part in parts:
            if part.startswith("n"):
                try:
                    meta["n"] = int(part[1:])
                except ValueError:
                    pass
            elif part.startswith("f"):
                try:
                    meta["fanout"] = int(part[1:])
                except ValueError:
                    pass
            elif part.startswith("t"):
                try:
                    meta["ttl"] = int(part[1:])
                except ValueError:
                    pass
            elif part.startswith("s"):
                try:
                    meta["seed"] = int(part[1:])
                except ValueError:
                    pass
            elif part in ("push", "hybrid"):
                meta["mode"] = part
        events = load_events(dpath)
        metrics = compute_convergence_and_overhead(events)
        meta.update(metrics)
        experiments.append(meta)
    return experiments


def mean_std(values: list[float]) -> tuple[float, float]:
    """Compute mean and std of a list of floats."""
    if not values:
        return 0.0, 0.0
    m = sum(values) / len(values)
    if len(values) == 1:
        return m, 0.0
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return m, variance ** 0.5


def plot_convergence_vs_n(experiments: list[dict], output_dir: str) -> None:
    """Plot convergence time vs N, one line per mode."""
    by_mode_n: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for exp in experiments:
        mode = exp.get("mode", "unknown")
        n = exp.get("n")
        ct = exp.get("convergence_time")
        if n is not None and ct is not None:
            by_mode_n[mode][n].append(ct)

    fig, ax = plt.subplots()
    for mode, n_map in sorted(by_mode_n.items()):
        ns = sorted(n_map)
        means = []
        stds = []
        for n in ns:
            m, s = mean_std(n_map[n])
            means.append(m)
            stds.append(s)
        ax.errorbar(ns, means, yerr=stds, label=mode, marker="o", capsize=4)

    ax.set_xlabel("Number of nodes (N)")
    ax.set_ylabel("Convergence time (s)")
    ax.set_title("Convergence Time vs N")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(output_dir, "convergence_vs_n.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_overhead_vs_n(experiments: list[dict], output_dir: str) -> None:
    """Plot message overhead vs N, one line per mode."""
    by_mode_n: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for exp in experiments:
        mode = exp.get("mode", "unknown")
        n = exp.get("n")
        oh = exp.get("message_overhead")
        if n is not None and oh is not None:
            by_mode_n[mode][n].append(float(oh))

    fig, ax = plt.subplots()
    for mode, n_map in sorted(by_mode_n.items()):
        ns = sorted(n_map)
        means = []
        stds = []
        for n in ns:
            m, s = mean_std(n_map[n])
            means.append(m)
            stds.append(s)
        ax.errorbar(ns, means, yerr=stds, label=mode, marker="o", capsize=4)

    ax.set_xlabel("Number of nodes (N)")
    ax.set_ylabel("Message overhead (count)")
    ax.set_title("Message Overhead vs N")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(output_dir, "overhead_vs_n.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_convergence_vs_fanout(experiments: list[dict], output_dir: str) -> None:
    """Plot convergence time vs fanout (for N=50), one line per mode."""
    by_mode_f: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for exp in experiments:
        n = exp.get("n")
        if n != 50:
            continue
        mode = exp.get("mode", "unknown")
        f = exp.get("fanout")
        ct = exp.get("convergence_time")
        if f is not None and ct is not None:
            by_mode_f[mode][f].append(ct)

    fig, ax = plt.subplots()
    for mode, f_map in sorted(by_mode_f.items()):
        fs = sorted(f_map)
        means = [mean_std(f_map[f])[0] for f in fs]
        stds = [mean_std(f_map[f])[1] for f in fs]
        ax.errorbar(fs, means, yerr=stds, label=mode, marker="o", capsize=4)

    ax.set_xlabel("Fanout")
    ax.set_ylabel("Convergence time (s)")
    ax.set_title("Convergence Time vs Fanout (N=50)")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(output_dir, "convergence_vs_fanout.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_overhead_vs_fanout(experiments: list[dict], output_dir: str) -> None:
    """Plot message overhead vs fanout (for N=50), one line per mode."""
    by_mode_f: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for exp in experiments:
        n = exp.get("n")
        if n != 50:
            continue
        mode = exp.get("mode", "unknown")
        f = exp.get("fanout")
        oh = exp.get("message_overhead")
        if f is not None and oh is not None:
            by_mode_f[mode][f].append(float(oh))

    fig, ax = plt.subplots()
    for mode, f_map in sorted(by_mode_f.items()):
        fs = sorted(f_map)
        means = [mean_std(f_map[f])[0] for f in fs]
        stds = [mean_std(f_map[f])[1] for f in fs]
        ax.errorbar(fs, means, yerr=stds, label=mode, marker="o", capsize=4)

    ax.set_xlabel("Fanout")
    ax.set_ylabel("Message overhead (count)")
    ax.set_title("Message Overhead vs Fanout (N=50)")
    ax.legend()
    fig.tight_layout()
    path = os.path.join(output_dir, "overhead_vs_fanout.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_push_vs_hybrid(experiments: list[dict], output_dir: str) -> None:
    """Grouped bar chart comparing push vs hybrid for each N."""
    by_mode_n_ct: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for exp in experiments:
        mode = exp.get("mode", "unknown")
        n = exp.get("n")
        ct = exp.get("convergence_time")
        if n is not None and ct is not None:
            by_mode_n_ct[mode][n].append(ct)

    all_ns = sorted({n for mode_map in by_mode_n_ct.values() for n in mode_map})
    modes = sorted(by_mode_n_ct.keys())
    x = list(range(len(all_ns)))
    width = 0.35

    fig, ax = plt.subplots()
    for i, mode in enumerate(modes):
        heights = [mean_std(by_mode_n_ct[mode].get(n, []))[0] for n in all_ns]
        errs = [mean_std(by_mode_n_ct[mode].get(n, []))[1] for n in all_ns]
        offsets = [xi + (i - len(modes) / 2 + 0.5) * width for xi in x]
        ax.bar(offsets, heights, width=width, label=mode, yerr=errs, capsize=4)

    ax.set_xlabel("Number of nodes (N)")
    ax.set_ylabel("Convergence time (s)")
    ax.set_title("Push vs Hybrid Convergence Time")
    ax.set_xticks(x)
    ax.set_xticklabels([str(n) for n in all_ns])
    ax.legend()
    fig.tight_layout()
    path = os.path.join(output_dir, "push_vs_hybrid.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze gossip experiment logs")
    parser.add_argument("--results-dir", type=str, default="results")
    parser.add_argument("--output-dir", type=str, default="results/plots")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    experiments = scan_experiments(args.results_dir)
    print(f"Found {len(experiments)} experiments in {args.results_dir}")

    plot_convergence_vs_n(experiments, args.output_dir)
    plot_overhead_vs_n(experiments, args.output_dir)
    plot_convergence_vs_fanout(experiments, args.output_dir)
    plot_overhead_vs_fanout(experiments, args.output_dir)
    plot_push_vs_hybrid(experiments, args.output_dir)


if __name__ == "__main__":
    main()
