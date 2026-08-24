# Compare token cost of graph encodings: JSON, edge list, adjacency matrix
# (0 = no edge, k = edge type id), incident list, and type-grouped pairs.
# Run: uv run --with tiktoken experiments/token_encoding_bench.py

import json
import random

import tiktoken

enc = tiktoken.get_encoding("cl100k_base")
random.seed(42)

EDGE_TYPES = ["knows", "works_at", "located_in", "authored", "cites"]


def make_graph(n_nodes, n_edges):
    nodes = [f"node{i}" for i in range(n_nodes)]
    edges = set()
    while len(edges) < n_edges:
        s, o = random.sample(range(n_nodes), 2)
        edges.add((s, random.randrange(len(EDGE_TYPES)), o))
    return nodes, sorted(edges)


def enc_json(nodes, edges):
    return json.dumps(
        {
            "nodes": nodes,
            "edges": [
                {"source": nodes[s], "type": EDGE_TYPES[t], "target": nodes[o]}
                for s, t, o in edges
            ],
        }
    )


def enc_edge_list(nodes, edges):
    lines = [f"{nodes[s]} {EDGE_TYPES[t]} {nodes[o]}" for s, t, o in edges]
    return "\n".join(lines)


def enc_edge_list_int(nodes, edges):
    legend = "types: " + " ".join(f"{i}={t}" for i, t in enumerate(EDGE_TYPES))
    lines = [f"{s} {t} {o}" for s, t, o in edges]
    return legend + "\n" + "\n".join(lines)


def enc_matrix(nodes, edges):
    n = len(nodes)
    m = [[0] * n for _ in range(n)]
    for s, t, o in edges:
        m[s][o] = t + 1
    legend = "types: " + " ".join(f"{i + 1}={t}" for i, t in enumerate(EDGE_TYPES))
    rows = "\n".join(" ".join(str(c) for c in row) for row in m)
    return legend + "\n" + rows


def enc_incident(nodes, edges):
    adj = {}
    for s, t, o in edges:
        adj.setdefault(s, []).append((t, o))
    lines = [
        f"{nodes[s]}: " + ", ".join(f"{EDGE_TYPES[t]} {nodes[o]}" for t, o in outs)
        for s, outs in sorted(adj.items())
    ]
    return "\n".join(lines)


def enc_type_grouped(nodes, edges):
    by_type = {}
    for s, t, o in edges:
        by_type.setdefault(t, []).append((s, o))
    lines = [
        f"{EDGE_TYPES[t]}: " + " ".join(f"{nodes[s]}>{nodes[o]}" for s, o in pairs)
        for t, pairs in sorted(by_type.items())
    ]
    return "\n".join(lines)


ENCODERS = {
    "JSON (pretty-typical)": enc_json,
    "edge list (names)": enc_edge_list,
    "edge list (int ids + legend)": enc_edge_list_int,
    "adjacency matrix (0/type-int)": enc_matrix,
    "incident list": enc_incident,
    "type-grouped pairs": enc_type_grouped,
}

for n_nodes, n_edges in [(30, 90), (100, 300), (300, 900), (100, 2000)]:
    nodes, edges = make_graph(n_nodes, n_edges)
    density = n_edges / (n_nodes * (n_nodes - 1))
    print(f"\n=== {n_nodes} nodes, {n_edges} edges (density {density:.1%}) ===")
    for name, fn in ENCODERS.items():
        toks = len(enc.encode(fn(nodes, edges)))
        print(f"{name:32s} {toks:7,d} tokens  ({toks / n_edges:5.1f}/edge)")
