"""Re-run the frozen public queries and check the published scores still hold.

The benchmark numbers in `docs/benchmarks/` were produced by an engine
that has since changed. Nothing in this file generates a query or calls a
model: it replays exactly the queries that were scored, against exactly
the stores they were scored on, and reports any question whose score
moved. A silent change to a published number is the failure this exists
to catch.

    uv run python -m eval.verify_replay [graph ...]

Writes nothing. Exits non-zero if any score moved.
"""

from __future__ import annotations

import functools
import json
import signal
import sys
import time

from eval.run_public import (
    DATA,
    EXEC_TIMEOUT_S,
    OUT,
    PUB,
    _alarm,
    load_queries,
    questions_for,
    score,
)

MODEL = "claude-haiku-4-5-20251001"

GRAPHS = [
    "nba",
    "flight_accident",
    "fictional_character",
    "company",
    "geography",
    "movie",
    "politics",
]


def replay(graph: str, model: str) -> tuple[int, list[dict]]:
    from eval.load_graph import derive_schema
    from theorem.engine.executor import execute_rows, limits
    from theorem.engine.storage import Store
    from theorem.parser import parse
    from theorem.verifier import verify

    published_path = PUB / f"exec-{model}-{graph}.json"
    if not published_path.exists():
        print(f"[{graph}] no published run to check against, skipping")
        return 0, []
    published = {r["qid"]: r for r in json.loads(published_path.read_text())}
    queries = load_queries(model)
    schema = derive_schema(json.loads((DATA / f"{graph}_schema.json").read_text()))

    store = Store(OUT / f"db-full-{graph}", lock=False)
    if not store.nodes:
        print(f"[{graph}] store is empty; load it first")
        return 0, []
    # Reads no longer write: traffic telemetry is kept in memory and reaches
    # disk with the next snapshot (Store.touch). The harness used to disable
    # store.apply here, which meant the benchmark was measuring an engine the
    # shipped one was not.
    print(f"[{graph}] {len(store.nodes)} nodes, {len(published)} scored questions")

    signal.signal(signal.SIGALRM, _alarm)
    exec_limits = functools.partial(limits, seconds=EXEC_TIMEOUT_S, max_rows=10**9)
    moved: list[dict] = []
    checked = 0
    t0 = time.perf_counter()
    for q in questions_for(graph):
        qid = q["qid"]
        if qid not in published or qid not in queries:
            continue
        try:
            signal.alarm(EXEC_TIMEOUT_S)
            plans = verify(parse(queries[qid]), schema)
            with exec_limits():
                rows = execute_rows(plans, store, schema)
            now = score(rows, q["gold_cypher"], q["answer_json"])
        except (Exception, MemoryError) as e:
            now = 0.0
            err = f"{type(e).__name__}: {e}"[:200]
        else:
            err = ""
        checked += 1
        was = published[qid]["ex"]
        if now != was:
            moved.append(
                {
                    "graph": graph,
                    "qid": qid,
                    "was": was,
                    "now": now,
                    "error": err,
                    "query": queries[qid],
                }
            )
            print(f"[{graph}] MOVED {qid}: {was} -> {now} {err}", flush=True)
        if checked % 100 == 0:
            print(f"[{graph}] {checked} checked, {len(moved)} moved", flush=True)
    store.close()
    print(
        f"[{graph}] done: {checked} checked, {len(moved)} moved "
        f"in {time.perf_counter() - t0:.0f}s",
        flush=True,
    )
    return checked, moved


def main(argv: list[str]) -> int:
    graphs = argv or GRAPHS
    total, all_moved = 0, []
    for graph in graphs:
        checked, moved = replay(graph, MODEL)
        total += checked
        all_moved += moved
    print(f"\nchecked {total} questions across {len(graphs)} graphs")
    if all_moved:
        print(f"{len(all_moved)} scores moved:")
        for m in all_moved:
            print(f"  {m['graph']}/{m['qid']}: {m['was']} -> {m['now']} {m['error']}")
        return 1
    print("every published score reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
