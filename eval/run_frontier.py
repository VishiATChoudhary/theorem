"""Does the advantage survive a better model?

Every number in these docs is one small model, Haiku 4.5. The obvious
objection is that the language is scaffolding for weak models and a
frontier model writes Cypher well enough that none of it matters. That
objection is answerable, and this answers it: the same questions, the
same comparator, both arms, one frontier model.

It is a sample rather than the whole test set, because the whole test set
on a frontier model is 4,700 generations to answer a yes-or-no question.
The sample is stratified by graph and by match category and seeded, so it
is the same sample every time and the composition is written into the
results.

    uv run python -m eval.run_frontier gen  --model claude-sonnet-5
    uv run python -m eval.run_frontier exec --model claude-sonnet-5
    uv run python -m eval.run_frontier report --model claude-sonnet-5

`gen` needs the `claude` CLI. `exec` needs Docker for the Cypher arm.
Nothing here writes to the Haiku results.
"""

from __future__ import annotations

import argparse
import collections
import functools
import json
import random
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from eval.run_public import (
    DATA,
    EXEC_TIMEOUT_S,
    OUT,
    PUB,
    _alarm,
    questions_for,
    score,
)

FRONTIER = PUB / "frontier"
# The three smallest graphs by load time. The Cypher arm hosts each one
# in its own container, and a frontier check should not cost an hour of
# importing JSON to answer a question about model capability.
DEFAULT_GRAPHS = ["nba", "flight_accident", "fictional_character"]
SEED = 20260831


def sample(graphs: list[str], n: int) -> list[dict]:
    """A seeded, stratified sample: proportional by graph and category."""
    pool = [q for q in questions_for() if q["graph"] in graphs]
    by_stratum: dict[tuple, list[dict]] = collections.defaultdict(list)
    for q in pool:
        by_stratum[(q["graph"], q["from_template"]["match_category"])].append(q)

    rng = random.Random(SEED)
    picked: list[dict] = []
    for key in sorted(by_stratum):
        group = sorted(by_stratum[key], key=lambda q: q["qid"])
        take = max(1, round(n * len(group) / len(pool)))
        picked += rng.sample(group, min(take, len(group)))
    picked.sort(key=lambda q: q["qid"])
    return picked[:n]


def _schemas(graphs: list[str]) -> dict:
    from eval.load_graph import derive_schema

    return {
        g: derive_schema(json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in graphs
    }


def gen(model: str, graphs: list[str], n: int, workers: int) -> int:
    from eval.prompts import cypher_prompt, theorem_prompt
    from eval.run_eval import llm

    qs = sample(graphs, n)
    schemas = _schemas(graphs)
    cb = {g: json.loads((DATA / f"{g}_schema.json").read_text()) for g in graphs}
    print(f"generating {len(qs)} x 2 arms with {model} ({workers} workers)")

    def one(item):
        q, arm = item
        if arm == "theorem":
            prompt = theorem_prompt(schemas[q["graph"]], q["nl_question"])
        else:
            prompt = cypher_prompt(cb[q["graph"]], q["nl_question"])
        try:
            return arm, q["qid"], llm(prompt, model, f"frontier-{arm}-{q['qid']}")
        except Exception as e:
            return arm, q["qid"], RuntimeError(f"{type(e).__name__}: {e}")

    work = [(q, arm) for q in qs for arm in ("theorem", "cypher")]
    out: dict[str, dict[str, str]] = {"theorem": {}, "cypher": {}}
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (arm, qid, text) in enumerate(ex.map(one, work)):
            if isinstance(text, Exception):
                failed.append((arm, qid, str(text)))
            else:
                out[arm][qid] = text
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(work)}, {len(failed)} failed", flush=True)

    FRONTIER.mkdir(parents=True, exist_ok=True)
    if failed:
        for arm, qid, why in failed[:5]:
            print(f"  FAILED {arm} {qid}: {why}")
        print(
            f"{len(failed)} of {len(work)} calls failed; not writing the frozen "
            "files. Re-run `gen` to fill them (the rest are cached)."
        )
        return 1
    for arm in out:
        (FRONTIER / f"queries-{arm}-{model}.json").write_text(
            json.dumps(out[arm], indent=1)
        )
    (FRONTIER / f"sample-{model}.json").write_text(
        json.dumps(
            {
                "seed": SEED,
                "graphs": graphs,
                "n": len(qs),
                "qids": [q["qid"] for q in qs],
                "by_graph": dict(collections.Counter(q["graph"] for q in qs)),
                "by_category": dict(
                    collections.Counter(
                        q["from_template"]["match_category"] for q in qs
                    )
                ),
            },
            indent=1,
        )
    )
    print(f"wrote {FRONTIER}/queries-*-{model}.json ({len(qs)} questions)")
    return 0


def exec_theorem(model: str, graphs: list[str], n: int) -> None:
    from theorem.engine.executor import execute_rows, limits
    from theorem.engine.storage import Store
    from theorem.parser import parse
    from theorem.verifier import verify

    queries = json.loads((FRONTIER / f"queries-theorem-{model}.json").read_text())
    schemas = _schemas(graphs)
    signal.signal(signal.SIGALRM, _alarm)
    run_limits = functools.partial(limits, seconds=EXEC_TIMEOUT_S, max_rows=10**9)
    results = []
    for graph in graphs:
        store = Store(OUT / f"db-full-{graph}", lock=False)
        for q in sample(graphs, n):
            if q["graph"] != graph or q["qid"] not in queries:
                continue
            rec = {
                "qid": q["qid"],
                "graph": graph,
                "category": q["from_template"]["match_category"],
            }
            try:
                signal.alarm(EXEC_TIMEOUT_S)
                t0 = time.perf_counter()
                with run_limits():
                    rows = execute_rows(
                        verify(parse(queries[q["qid"]]), schemas[graph]),
                        store,
                        schemas[graph],
                    )
                rec["latency_ms"] = round(1000 * (time.perf_counter() - t0), 2)
                rec["executable"] = True
                rec["ex"] = score(rows, q["gold_cypher"], q["answer_json"])
            except (Exception, MemoryError) as e:
                rec["executable"] = False
                rec["ex"] = 0.0
                rec["error"] = f"{type(e).__name__}: {e}"[:300]
            finally:
                signal.alarm(0)
            results.append(rec)
        store.close()
        done = [r for r in results if r["graph"] == graph]
        print(
            f"[{graph}] theorem {len(done)} scored, "
            f"EX {sum(r['ex'] for r in done) / max(len(done), 1):.3f}",
            flush=True,
        )
    (FRONTIER / f"exec-theorem-{model}.json").write_text(json.dumps(results, indent=1))


def exec_cypher(model: str, graphs: list[str], n: int) -> None:
    from neo4j import Query

    from eval.run_cypher_public import (
        HOST_LOADED,
        connect,
        load_from_host,
        start_graph,
        stop_container,
    )

    queries = json.loads((FRONTIER / f"queries-cypher-{model}.json").read_text())
    results = []
    for graph in graphs:
        host_load = graph in HOST_LOADED
        start_graph(graph, host_load=host_load)
        driver = connect(expect_empty=host_load)
        if host_load:
            load_from_host(driver, graph)
        try:
            with driver.session() as s:
                for q in sample(graphs, n):
                    if q["graph"] != graph or q["qid"] not in queries:
                        continue
                    rec = {
                        "qid": q["qid"],
                        "graph": graph,
                        "category": q["from_template"]["match_category"],
                    }
                    try:
                        t0 = time.perf_counter()
                        rows = s.run(
                            Query(queries[q["qid"]], timeout=EXEC_TIMEOUT_S)
                        ).data()
                        rec["latency_ms"] = round(1000 * (time.perf_counter() - t0), 2)
                        rec["executable"] = True
                        rec["ex"] = score(rows, q["gold_cypher"], q["answer_json"])
                    except Exception as e:
                        rec["executable"] = False
                        rec["ex"] = 0.0
                        rec["error"] = f"{type(e).__name__}: {e}"[:300]
                    results.append(rec)
        finally:
            driver.close()
            stop_container()
        done = [r for r in results if r["graph"] == graph]
        print(
            f"[{graph}] cypher {len(done)} scored, "
            f"EX {sum(r['ex'] for r in done) / max(len(done), 1):.3f}",
            flush=True,
        )
    (FRONTIER / f"exec-cypher-{model}.json").write_text(json.dumps(results, indent=1))


def report(model: str) -> int:
    import math

    arms = {}
    for arm in ("theorem", "cypher"):
        path = FRONTIER / f"exec-{arm}-{model}.json"
        if not path.exists():
            sys.exit(f"no results for {arm}; run exec first")
        arms[arm] = {r["qid"]: r for r in json.loads(path.read_text())}
    shared = sorted(set(arms["theorem"]) & set(arms["cypher"]))
    if not shared:
        sys.exit("the two arms share no questions")

    print("| arm | n | EX | executable | median ms |")
    print("|---|---:|---:|---:|---:|")
    for arm, rows in arms.items():
        rs = [rows[q] for q in shared]
        lat = sorted(r.get("latency_ms", 0.0) for r in rs)
        print(
            f"| {arm} | {len(rs)} | {100 * sum(r['ex'] for r in rs) / len(rs):.1f}% "
            f"| {100 * sum(r['executable'] for r in rs) / len(rs):.1f}% "
            f"| {lat[len(lat) // 2]:.1f} |"
        )

    # McNemar on the questions the two arms disagree about, which is the
    # only comparison a paired design supports.
    only_t = sum(
        arms["theorem"][q]["ex"] == 1.0 and arms["cypher"][q]["ex"] != 1.0
        for q in shared
    )
    only_c = sum(
        arms["cypher"][q]["ex"] == 1.0 and arms["theorem"][q]["ex"] != 1.0
        for q in shared
    )
    m = only_t + only_c
    p = (
        sum(math.comb(m, k) for k in range(min(only_t, only_c) + 1)) / 2 ** (m - 1)
        if m
        else 1.0
    )
    print(
        f"\ntheorem only {only_t}, text2cypher only {only_c}, "
        f"discordant {m}, exact McNemar p = {min(p, 1.0):.4f}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "exec", "report", "sample"])
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--graphs", default=",".join(DEFAULT_GRAPHS))
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--arm", choices=["both", "theorem", "cypher"], default="both")
    args = ap.parse_args()
    graphs = args.graphs.split(",")

    if args.cmd == "sample":
        qs = sample(graphs, args.n)
        print(f"{len(qs)} questions")
        print(" by graph:", dict(collections.Counter(q["graph"] for q in qs)))
        print(
            " by category:",
            dict(collections.Counter(q["from_template"]["match_category"] for q in qs)),
        )
        return 0
    if args.cmd == "gen":
        return gen(args.model, graphs, args.n, args.workers)
    if args.cmd == "exec":
        if args.arm in ("both", "theorem"):
            exec_theorem(args.model, graphs, args.n)
        if args.arm in ("both", "cypher"):
            exec_cypher(args.model, graphs, args.n)
        return 0
    return report(args.model)


if __name__ == "__main__":
    raise SystemExit(main())
