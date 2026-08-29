"""Re-score the frozen theorem queries with set-valued `return`.

Same queries, same graphs, same comparator as run_public; the only
difference is that duplicate rows collapse before scoring. Writes
`setwise-<model>-<graph>.json` next to the originals.

  uv run python -m eval.run_setwise --graph G [--model M]
"""

from __future__ import annotations

import argparse
import json
import signal
import sys

from eval.run_public import (
    DATA,
    EXEC_TIMEOUT_S,
    OUT,
    PUB,
    TEST_GRAPHS,
    _alarm,
    load_queries,
    questions_for,
    score,
)
from eval.setwise import execute_rows_setwise


def exec_graph(graph: str, model: str) -> None:
    from eval.load_graph import derive_schema, load
    from theorem.engine.storage import Store
    from theorem.parser import parse
    from theorem.verifier import verify

    queries = load_queries(model)
    schema = derive_schema(json.loads((DATA / f"{graph}_schema.json").read_text()))
    store = Store(OUT / f"db-full-{graph}")
    if not store.nodes:
        load(DATA / f"{graph}_simplekg.json", store)
        store.snapshot()
    store.apply = lambda record: 0
    print(f"[{graph}] {len(store.nodes)} nodes, {len(store.edge_index)} edges")

    signal.signal(signal.SIGALRM, _alarm)
    # Deduplicating a wide fanout holds every row key at once, which was
    # enough to get the movie graph's process OOM-killed outright. Saving
    # as we go means a kill costs one question, not the whole graph.
    partial = PUB / f"setwise-{model}-{graph}.partial.json"
    results = json.loads(partial.read_text()) if partial.exists() else []
    done = {r["qid"] for r in results}
    questions = questions_for(graph)
    for q in questions:
        if q["qid"] not in queries or q["qid"] in done:
            continue
        query = queries[q["qid"]]
        rec = {
            "qid": q["qid"],
            "category": q["from_template"]["match_category"],
            "query": query,
        }
        # Record the question as failed *before* running it. Some queries
        # exhaust memory badly enough that the OS kills the process, which
        # no except clause can catch; without this the next run would
        # restart on the same question forever. A success overwrites the
        # placeholder immediately after.
        rec["executable"] = False
        rec["ex"] = 0.0
        rec["error"] = "process did not survive this query"
        results.append(rec)
        partial.write_text(json.dumps(results, indent=1))
        try:
            signal.alarm(EXEC_TIMEOUT_S)
            rows = execute_rows_setwise(verify(parse(query), schema), store, schema)
            rec["executable"] = True
            rec["ex"] = score(rows, q["gold_cypher"], q["answer_json"])
            rec["n_rows"] = len(rows)
            rec.pop("error", None)
        except (Exception, MemoryError) as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
        finally:
            signal.alarm(0)
        if len(results) % 25 == 0:
            partial.write_text(json.dumps(results, indent=1))
            print(f"[{graph}] {len(results)}/{len(questions)}", flush=True)
    out = PUB / f"setwise-{model}-{graph}.json"
    out.write_text(json.dumps(results, indent=1))
    partial.unlink(missing_ok=True)
    ex = sum(r["ex"] for r in results) / len(results)
    print(f"[{graph}] setwise EX {ex:.4f} over {len(results)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=None)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    args = ap.parse_args()
    graphs = [args.graph] if args.graph else TEST_GRAPHS
    for g in graphs:
        if g not in TEST_GRAPHS:
            sys.exit(f"unknown graph {g}")
        exec_graph(g, args.model)


if __name__ == "__main__":
    main()
