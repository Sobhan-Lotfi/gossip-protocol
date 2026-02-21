"""Build and visualize the network topology graph from TOPOLOGY_DUMP log events."""

from __future__ import annotations

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx


def load_topology_dumps(log_dir: str) -> dict[str, list[str]]:
    """Read TOPOLOGY_DUMP events from all .jsonl files in log_dir.

    Returns mapping node_id -> list of peer node_ids from the last dump per node.
    """
    last_dump: dict[str, list[str]] = {}
    for fname in os.listdir(log_dir):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(log_dir, fname)
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") == "TOPOLOGY_DUMP":
                    node_id = ev.get("node_id")
                    peers = ev.get("peers", [])
                    if node_id:
                        last_dump[node_id] = peers
    return last_dump


def build_graph(topology: dict[str, list[str]]) -> nx.DiGraph:
    """Build a directed graph from topology: edge A→B means A has B in peer list."""
    g = nx.DiGraph()
    for node_id in topology:
        g.add_node(node_id)
    for node_id, peers in topology.items():
        for peer_id in peers:
            g.add_edge(node_id, peer_id)
    return g


def compute_stats(g: nx.DiGraph) -> dict:
    """Compute and return graph statistics."""
    ug = g.to_undirected()
    in_degrees = [d for _, d in g.in_degree()]
    out_degrees = [d for _, d in g.out_degree()]
    avg_in = sum(in_degrees) / len(in_degrees) if in_degrees else 0.0
    avg_out = sum(out_degrees) / len(out_degrees) if out_degrees else 0.0

    try:
        diameter = nx.diameter(ug)
    except (nx.NetworkXError, nx.exception.NetworkXError):
        diameter = -1

    try:
        clustering = nx.average_clustering(ug)
    except ZeroDivisionError:
        clustering = 0.0

    return {
        "num_nodes": g.number_of_nodes(),
        "num_edges": g.number_of_edges(),
        "avg_in_degree": avg_in,
        "avg_out_degree": avg_out,
        "diameter": diameter,
        "clustering_coefficient": clustering,
    }


def visualize(g: nx.DiGraph, output_path: str) -> None:
    """Save a spring-layout visualization of the graph as PNG."""
    fig, ax = plt.subplots(figsize=(12, 10))
    pos = nx.spring_layout(g, seed=42)
    # Shorten labels for readability
    labels = {n: n[:8] for n in g.nodes()}
    nx.draw_networkx(
        g,
        pos=pos,
        labels=labels,
        ax=ax,
        node_size=300,
        font_size=6,
        arrows=True,
        arrowsize=10,
        edge_color="gray",
        node_color="steelblue",
        font_color="white",
    )
    ax.set_title("Gossip Network Topology")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Topology graph saved to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize gossip network topology")
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--output", type=str, default="results/plots/topology.png")
    args = parser.parse_args()

    topology = load_topology_dumps(args.log_dir)
    if not topology:
        print("No TOPOLOGY_DUMP events found in", args.log_dir)
        return

    g = build_graph(topology)
    stats = compute_stats(g)

    print(f"Nodes:                {stats['num_nodes']}")
    print(f"Edges:                {stats['num_edges']}")
    print(f"Avg in-degree:        {stats['avg_in_degree']:.2f}")
    print(f"Avg out-degree:       {stats['avg_out_degree']:.2f}")
    print(f"Diameter:             {stats['diameter']}")
    print(f"Clustering coeff:     {stats['clustering_coefficient']:.4f}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    visualize(g, args.output)


if __name__ == "__main__":
    main()
