"""Same-model text2cypher control on the CypherBench public test set.

The published Table 3 baselines were run on 2024 models. To attribute any
difference to the query language rather than to the model, this runs the
official zero-shot text2cypher setup with the SAME model used for the
theorem run, on the same questions, scored by the same comparator.

Faithful to the official baseline:
- Prompt is NL2CYPHER_PROMPT_DEFAULT verbatim from
  cypherbench/baseline/zero_shot_nl2cypher.py.
- Schema string reproduces PropertyGraphSchema.from_json(...).to_sorted()
  .to_str(exclude_description=True): a "name" str property is added first
  to every entity, entities sort by label, relations by
  (label, subj_label, obj_label), properties by key, entity descriptions
  are dropped, and the whole thing is json.dumps(indent=2).
- Zero-shot, single generation, no repair retry.
- Queries run against the graph loaded by the official
  megagonlabs/neo4j-with-loader image from the same simplekg JSON, with
  the official 120s timeout.
- Scoring reuses the vendored official comparator in run_public.

Graphs are hosted one at a time so peak memory stays bounded.

  uv run python -m eval.run_cypher_public gen  [--model M] [--workers K]
  uv run python -m eval.run_cypher_public exec --graph G [--model M]
  uv run python -m eval.run_cypher_public report [--model M]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eval.run_public import (
    DATA,
    EXEC_TIMEOUT_S,
    PUB,
    TEST_GRAPHS,
    _compare_execution,
    questions_for,
    rows_to_records,
    to_hashable,
)

CONTAINER = "cypherbench-eval"
BOLT_PORT = 17687
AUTH = ("neo4j", "cypherbencheval1")

NL2CYPHER_PROMPT_DEFAULT = """Translate the question to Cypher query based on the schema of a Neo4j knowledge graph.
- Output the Cypher query in a single line, without any additional output or explanation. Do not wrap the query with any formatting like ```.
- Perform graph pattern matching in the `MATCH` clause if possible.
- Avoid listing the same entity multiple times in the results. However, if multiple distinct entities share the same name, their names should be repeated as separate entries.
- Do not return node objects. Instead, return entity names or properties.

Graph Schema:
{schema}

Question: {question}
Cypher: """


def official_schema_str(graph: str) -> str:
    """Reproduce PropertyGraphSchema.from_json(...).to_sorted().to_str(
    exclude_description=True) without pulling in the cypherbench package."""
    raw = json.loads((DATA / f"{graph}_schema.json").read_text())
    entities = []
    for ent in sorted(raw["entities"], key=lambda x: x["label"]):
        props = {"name": "str", **ent.get("properties", {})}
        entities.append(
            {"label": ent["label"], "properties": dict(sorted(props.items()))}
        )
    relations = []
    for rel in sorted(
        raw["relations"], key=lambda x: (x["label"], x["subj_label"], x["obj_label"])
    ):
        relations.append(
            {
                "label": rel["label"],
                "subj_label": rel["subj_label"],
                "obj_label": rel["obj_label"],
                "properties": dict(sorted(rel.get("properties", {}).items())),
            }
        )
    return json.dumps(
        {"name": raw["name"], "entities": entities, "relations": relations}, indent=2
    )


# ---- phase 1: generation ----------------------------------------------


def gen(model: str, workers: int) -> None:
    from eval.run_eval import llm

    schemas = {g: official_schema_str(g) for g in TEST_GRAPHS}
    questions = questions_for()
    print(f"generating {len(questions)} cypher queries with {model}")

    def one(q):
        prompt = NL2CYPHER_PROMPT_DEFAULT.format(
            schema=schemas[q["graph"]], question=q["nl_question"]
        )
        return q["qid"], llm(prompt, model, f"pubcy-{q['qid']}")

    queries = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (qid, text) in enumerate(ex.map(one, questions)):
            queries[qid] = text
            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(questions)}", flush=True)
    PUB.mkdir(parents=True, exist_ok=True)
    (PUB / f"cypher-queries-{model}.json").write_text(json.dumps(queries, indent=1))


def load_cypher_queries(model: str) -> dict[str, str]:
    import hashlib

    from eval.run_eval import CACHE

    frozen = PUB / f"cypher-queries-{model}.json"
    if frozen.exists():
        return json.loads(frozen.read_text())
    schemas = {g: official_schema_str(g) for g in TEST_GRAPHS}
    queries = {}
    for q in questions_for():
        prompt = NL2CYPHER_PROMPT_DEFAULT.format(
            schema=schemas[q["graph"]], question=q["nl_question"]
        )
        digest = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()[:10]
        path = CACHE / f"pubcy-{q['qid']}-{digest}.txt"
        if path.exists():
            queries[q["qid"]] = path.read_text()
    print(f"loaded {len(queries)} cypher queries from cache")
    return queries


# ---- neo4j hosting ----------------------------------------------------


def stop_container() -> None:
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)


def start_graph(graph: str) -> None:
    """Host one graph with the official loader image and wait for it."""
    stop_container()
    graph_path = (DATA / f"{graph}_simplekg.json").resolve()
    subprocess.run(
        [
            "docker", "run", "-d", "--name", CONTAINER,
            "-v", f"{graph_path}:/init/graph.json",
            "-p", f"{BOLT_PORT}:7687",
            "-e", f"NEO4J_AUTH={AUTH[0]}/{AUTH[1]}",
            # Must fit the Docker VM (7.6G here); Neo4j refuses to start
            # if heap + pagecache exceeds physical memory.
            "-e", "NEO4J_server_memory_heap_max__size=4G",
            "-e", "NEO4J_server_memory_pagecache_size=1G",
            "megagonlabs/neo4j-with-loader:2.4",
        ],
        check=True,
        capture_output=True,
    )
    print(f"[{graph}] container started, waiting for load ...", flush=True)


def connect(timeout_s: int = 3600):
    """Wait for the graph to finish loading, then return a driver.

    The loader image imports the JSON on first boot, so a successful
    connection is not enough: we wait until the node count stops growing.
    """
    from neo4j import GraphDatabase

    uri = f"bolt://localhost:{BOLT_PORT}"
    deadline = time.time() + timeout_s
    driver = None
    while time.time() < deadline:
        try:
            driver = GraphDatabase.driver(uri, auth=AUTH)
            driver.verify_connectivity()
            break
        except Exception:
            if driver is not None:
                driver.close()
                driver = None
            time.sleep(5)
    if driver is None:
        raise RuntimeError("neo4j never became reachable")
    last, stable = -1, 0
    while time.time() < deadline:
        with driver.session() as s:
            n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        if n == last and n > 0:
            stable += 1
            if stable >= 3:
                print(f"  loaded, {n} nodes", flush=True)
                return driver
        else:
            stable = 0
        last = n
        time.sleep(10)
    raise RuntimeError("graph did not finish loading")


def run_cypher(driver, cypher: str):
    """Mirrors Neo4jConnector.run_query: the timeout rides on the Query
    object (a bare session.run kwarg would be sent as a query parameter),
    and rows come back through result.data() as the official metric expects."""
    from neo4j import Query

    with driver.session(database="neo4j") as s:
        return s.run(Query(cypher, timeout=EXEC_TIMEOUT_S)).data()


# ---- phase 2: execution -----------------------------------------------


def exec_graph(graph: str, model: str) -> None:
    queries = load_cypher_queries(model)
    partial = PUB / f"cyexec-{model}-{graph}.partial.json"
    PUB.mkdir(parents=True, exist_ok=True)
    results = json.loads(partial.read_text()) if partial.exists() else []
    done = {r["qid"] for r in results}
    questions = questions_for(graph)

    start_graph(graph)
    driver = connect()
    try:
        for q in questions:
            if q["qid"] in done or q["qid"] not in queries:
                continue
            cypher = queries[q["qid"]].strip()
            rec = {
                "qid": q["qid"],
                "category": q["from_template"]["match_category"],
                "query": cypher,
            }
            try:
                raw = run_cypher(driver, cypher)
                pred = [
                    {k: to_hashable(v) for k, v in record.items()} for record in raw
                ]
                rec["executable"] = True
                gold = json.loads(q["answer_json"])
                rec["ex"] = _compare_execution(
                    pred_executed=pred,
                    target_executed=rows_to_records(gold),
                    order_matters="order by" in q["gold_cypher"].lower(),
                )
            except Exception as e:
                rec["executable"] = False
                rec["ex"] = 0.0
                rec["error"] = f"{type(e).__name__}: {e}"[:300]
            results.append(rec)
            if len(results) % 25 == 0:
                partial.write_text(json.dumps(results, indent=1))
                ok = sum(r["ex"] for r in results)
                print(
                    f"[{graph}] {len(results)}/{len(questions)} "
                    f"EX so far {ok / len(results):.3f}",
                    flush=True,
                )
    finally:
        driver.close()
        stop_container()

    ex_score = sum(r["ex"] for r in results) / len(results) if results else 0.0
    if len(results) < len(questions):
        partial.write_text(json.dumps(results, indent=1))
        print(
            f"[{graph}] INCOMPLETE {len(results)}/{len(questions)}, "
            f"EX so far {ex_score:.4f}",
            flush=True,
        )
        return
    out = PUB / f"cyexec-{model}-{graph}.json"
    out.write_text(json.dumps(results, indent=1))
    partial.unlink(missing_ok=True)
    print(f"[{graph}] cypher EX {ex_score:.4f} over {len(results)}", flush=True)


def report(model: str) -> None:
    all_results = []
    missing = []
    for g in TEST_GRAPHS:
        path = PUB / f"cyexec-{model}-{g}.json"
        if not path.exists():
            missing.append(g)
            continue
        for r in json.loads(path.read_text()):
            r["graph"] = g
            all_results.append(r)
    if not all_results:
        print("no cypher results yet")
        return
    n = len(all_results)

    def ex_of(rs):
        return round(sum(r["ex"] for r in rs) / len(rs), 4) if rs else None

    summary = {
        "benchmark": "CypherBench test set (megagonlabs/cypherbench)",
        "system": "text2cypher on Neo4j (official zero-shot prompt)",
        "model": model,
        "graphs_completed": [g for g in TEST_GRAPHS if g not in missing],
        "graphs_missing": missing,
        "n": n,
        "overall_ex": ex_of(all_results),
        "executable_pct": round(sum(r["executable"] for r in all_results) / n, 4),
        "by_graph": {
            g: ex_of([r for r in all_results if r["graph"] == g])
            for g in sorted({r["graph"] for r in all_results})
        },
        "by_category": {
            c: {
                "ex": ex_of([r for r in all_results if r["category"] == c]),
                "n": sum(r["category"] == c for r in all_results),
            }
            for c in sorted({r["category"] for r in all_results})
        },
    }
    (PUB / f"results-cypher-{model}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "exec", "report", "all"])
    ap.add_argument("--graph", default=None)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.cmd == "gen":
        gen(args.model, args.workers)
    elif args.cmd == "exec":
        if not args.graph:
            sys.exit("exec needs --graph")
        exec_graph(args.graph, args.model)
    elif args.cmd == "report":
        report(args.model)
    else:
        gen(args.model, args.workers)
        for g in TEST_GRAPHS:
            if (PUB / f"cyexec-{args.model}-{g}.json").exists():
                continue
            r = subprocess.run(
                [sys.executable, "-m", "eval.run_cypher_public", "exec",
                 "--graph", g, "--model", args.model]
            )
            if r.returncode != 0:
                print(f"[{g}] cypher exec failed ({r.returncode})")
        report(args.model)


if __name__ == "__main__":
    main()
