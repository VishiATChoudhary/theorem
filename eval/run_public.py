"""CypherBench public-protocol eval for theorem.

Protocol (matches the official benchmark, no curated slice):
- Full public test set: all 2,348 questions across the 7 test graphs.
- ALL match categories. There is no category filter, and nothing is
  excluded for being hard to express.
- Full (unsampled) simplekg graphs, the same ones the official Docker
  deployment loads, so gold answer_json values are directly comparable.
- Zero-shot, single generation, no repair retry, mirroring the official
  zero-shot baseline (cypherbench/baseline/zero_shot_nl2cypher.py).
- Scoring: the official execution-accuracy comparison (result_eq and
  helpers vendored verbatim below from megagonlabs/cypherbench,
  cypherbench/metrics/execution_accuracy.py, Apache-2.0), run against
  the published gold answer_json rows. order_matters iff the gold
  Cypher contains "order by", exactly as in the official metric.

Phases (LLM generation needs no graph in memory, execution does):
  uv run python -m eval.run_public gen    [--model M] [--workers K]
  uv run python -m eval.run_public exec   --graph G [--model M]
  uv run python -m eval.run_public report [--model M]
  uv run python -m eval.run_public all    [--model M]   # gen + per-graph exec subprocesses + report
"""

from __future__ import annotations

import argparse
import json
import functools
import signal
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "out"
PUB = OUT / "public"

TEST_GRAPHS = [
    "flight_accident",
    "nba",
    "fictional_character",
    "company",
    "geography",
    "politics",
    "movie",
]

EXEC_TIMEOUT_S = 120  # official metric's per-query timeout


# ---- official CypherBench comparison (vendored) -----------------------
# The functions below are copied from
# https://github.com/megagonlabs/cypherbench
# cypherbench/metrics/execution_accuracy.py (Apache-2.0), minus the
# neo4j driver types (gold rows here come from the published
# answer_json, which is already plain JSON). One deviation:
# to_hashable sorts with an explicit (type, str) key so mixed-type
# lists don't crash under Python 3; for homogeneous lists (all that
# occur in the gold answers) semantics are identical. Its neo4j temporal
# branch is duck-typed on iso_format rather than importing neo4j, so the
# theorem arm needs no driver installed, but it covers the same Date case
# the original handles.

import random
from typing import Dict, List, Set, Tuple


def to_hashable(obj, unorder_list=True):
    if isinstance(obj, (tuple, int, float, str, bool, type(None))):
        return obj
    elif hasattr(obj, "iso_format"):
        # neo4j temporal values (Date, DateTime, Time). The official
        # implementation converts Date this way; dropping it makes every
        # Cypher query that returns a date raise and score zero, which
        # penalises the control arm for a harness detail.
        return obj.iso_format()
    elif isinstance(obj, (list, tuple)):
        if unorder_list:
            return tuple(sorted((to_hashable(item) for item in obj), key=lambda x: (str(type(x)), str(x))))
        else:
            return tuple(to_hashable(item) for item in obj)
    elif isinstance(obj, set):
        return tuple(sorted((to_hashable(item) for item in obj), key=lambda x: (str(type(x)), str(x))))
    elif isinstance(obj, dict):
        return tuple(sorted((to_hashable(k), to_hashable(v)) for k, v in obj.items()))
    else:
        raise TypeError(f"Unhashable type: {type(obj)}")


def permute_tuple(element: Tuple, perm: Tuple) -> Tuple:
    assert len(element) == len(perm)
    return tuple([element[i] for i in perm])


def unorder_row(row: Tuple) -> Tuple:
    return tuple(sorted(row, key=lambda x: str(x) + str(type(x))))


def quick_rej(result1: List[Tuple], result2: List[Tuple], order_matters: bool) -> bool:
    s1 = [unorder_row(row) for row in result1]
    s2 = [unorder_row(row) for row in result2]
    if order_matters:
        return s1 == s2
    else:
        return set(s1) == set(s2)


def multiset_eq(l1: List, l2: List) -> bool:
    if len(l1) != len(l2):
        return False
    d = defaultdict(int)
    for e in l1:
        d[e] = d[e] + 1
    for e in l2:
        d[e] = d[e] - 1
        if d[e] < 0:
            return False
    return True


def get_constraint_permutation(tab1_sets_by_columns: List[Set], result2: List[Tuple]):
    num_cols = len(result2[0])
    perm_constraints = [{i for i in range(num_cols)} for _ in range(num_cols)]
    if num_cols <= 3:
        return product(*perm_constraints)
    for _ in range(20):
        random_tab2_row = random.choice(result2)
        for tab1_col in range(num_cols):
            for tab2_col in set(perm_constraints[tab1_col]):
                if random_tab2_row[tab2_col] not in tab1_sets_by_columns[tab1_col]:
                    perm_constraints[tab1_col].remove(tab2_col)
    return product(*perm_constraints)


def result_eq(result1: List[Tuple], result2: List[Tuple], order_matters: bool) -> bool:
    if len(result1) == 0 and len(result2) == 0:
        return True
    if len(result1) != len(result2):
        return False
    num_cols = len(result1[0])
    if len(result2[0]) != num_cols:
        return False
    if not quick_rej(result1, result2, order_matters):
        return False
    tab1_sets_by_columns = [{row[i] for row in result1} for i in range(num_cols)]
    for perm in get_constraint_permutation(tab1_sets_by_columns, result2):
        if len(perm) != len(set(perm)):
            continue
        if num_cols == 1:
            result2_perm = result2
        else:
            result2_perm = [permute_tuple(element, perm) for element in result2]
        if order_matters:
            if result1 == result2_perm:
                return True
        else:
            if set(result1) == set(result2_perm) and multiset_eq(result1, result2_perm):
                return True
    return False


def _compare_execution(
    pred_executed: list[dict], target_executed: list[dict], order_matters: bool
) -> float:
    if not pred_executed and not target_executed:
        return 1.0
    elif not pred_executed or not target_executed:
        return 0.0
    gold_tuples = to_tuples(target_executed)
    pred_tuples = to_tuples(pred_executed)
    return float(result_eq(gold_tuples, pred_tuples, order_matters=order_matters))


def to_tuples(result: List[Dict]) -> List[Tuple]:
    keys = list(result[0].keys())
    for row in result:
        assert set(row.keys()) == set(keys)
    return [tuple([row[key] for key in keys]) for row in result]


# ---- adapters ---------------------------------------------------------


def count_tokens_helper(text: str) -> int:
    """Same estimator theorem's own renderer uses, so both arms of the
    token comparison are counted identically."""
    from theorem.engine.executor import count_tokens

    return count_tokens(text)


def rows_to_records(rows: list) -> list[dict]:
    """Rows (list of lists) -> the record dicts the official comparator
    takes. Column names are positional; to_tuples discards them and
    result_eq searches column permutations, so names carry no signal."""
    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            row = [row]
        records.append({f"c{i}": to_hashable(v) for i, v in enumerate(row)})
    return records


def score(pred_rows: list, gold_cypher: str, answer_json: str) -> float:
    gold_rows = json.loads(answer_json)
    return _compare_execution(
        pred_executed=rows_to_records(pred_rows),
        target_executed=rows_to_records(gold_rows),
        order_matters="order by" in gold_cypher.lower(),
    )


# ---- phase 1: query generation ----------------------------------------


def questions_for(graph: str | None = None) -> list[dict]:
    tests = json.loads((DATA / "test.json").read_text())
    tests = [t for t in tests if t["graph"] in TEST_GRAPHS]
    if graph:
        tests = [t for t in tests if t["graph"] == graph]
    return tests


def gen(model: str, workers: int) -> None:
    from eval.load_graph import derive_schema
    from eval.prompts import theorem_prompt
    from eval.run_eval import llm

    schemas = {
        g: derive_schema(json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in TEST_GRAPHS
    }
    questions = questions_for()
    print(f"generating {len(questions)} queries with {model} ({workers} workers)")

    def one(q):
        prompt = theorem_prompt(schemas[q["graph"]], q["nl_question"])
        return q["qid"], llm(prompt, model, f"pub-{q['qid']}")

    queries = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (qid, text) in enumerate(ex.map(one, questions)):
            queries[qid] = text
            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(questions)}")
    PUB.mkdir(parents=True, exist_ok=True)
    out = frozen_path(model)
    out.write_text(json.dumps(queries, indent=1))
    print(f"wrote {out}")


def audit(model: str) -> int:
    """Delete cache entries that hold a failed call rather than a query.

    Generation runs for hours against a rate-limited CLI; a transport
    failure cached as an answer would be scored as a wrong answer and be
    invisible on re-runs. Anything that does not parse as theorem AND
    does not look like a query is dropped so the next gen refills it.
    """
    from eval.load_graph import derive_schema
    from theorem.parser import ParseError, parse

    schemas = {
        g: derive_schema(json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in TEST_GRAPHS
    }
    dropped = 0
    for q in questions_for():
        path = cache_path_for(q, model, schemas)
        if not path.exists():
            continue
        text = path.read_text().strip()
        bad = not text
        if not bad:
            try:
                parse(text)
            except ParseError:
                # A parse error is a legitimate model mistake, not a
                # transport failure, unless the text is not even an
                # attempt at a query.
                bad = not text.lower().startswith(GL_VERBS_STRIPPED)
            except Exception:
                bad = False
        if bad:
            path.unlink()
            dropped += 1
    print(f"audit: dropped {dropped} bad cache entries")
    return dropped


GL_VERBS_STRIPPED = ("find", "follow", "group", "count", "sum", "avg", "min", "max", "compute", "return", "continue", "schema")


def cache_path_for(q: dict, model: str, schemas: dict):
    import hashlib

    from eval.prompts import theorem_prompt
    from eval.run_eval import CACHE

    prompt = theorem_prompt(schemas[q["graph"]], q["nl_question"])
    digest = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()[:10]
    return CACHE / f"pub-{q['qid']}-{digest}.txt"


def prompt_fingerprint() -> str:
    """Short hash of the tutorial the queries were generated from."""
    import hashlib

    from eval.prompts import GRAPHLANG_TUTORIAL

    return hashlib.sha1(GRAPHLANG_TUTORIAL.encode()).hexdigest()[:8]


def frozen_path(model: str) -> Path:
    """The frozen query file for the CURRENT prompt.

    The prompt fingerprint is in the name so a file generated from an
    older tutorial is simply not found rather than being read as if it
    were current. Scoring last week's queries against this week's
    language looks like a result and is not one.
    """
    return PUB / f"queries-{model}-{prompt_fingerprint()}.json"


def load_queries(model: str) -> dict[str, str]:
    """Prefer the frozen queries file; fall back to the generation cache
    so execution can proceed (and resume) without a completed gen run."""
    frozen = frozen_path(model)
    if frozen.exists():
        queries = json.loads(frozen.read_text())
        print(f"loaded {len(queries)} queries from {frozen.name}")
        return queries
    from eval.load_graph import derive_schema

    schemas = {
        g: derive_schema(json.loads((DATA / f"{g}_schema.json").read_text()))
        for g in TEST_GRAPHS
    }
    queries = {}
    for q in questions_for():
        path = cache_path_for(q, model, schemas)
        if path.exists():
            queries[q["qid"]] = path.read_text()
    print(f"loaded {len(queries)} queries from generation cache")
    return queries


# ---- phase 2: execution + scoring -------------------------------------


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout(f"query exceeded {EXEC_TIMEOUT_S}s")


def exec_graph(graph: str, model: str) -> None:
    from eval.load_graph import derive_schema, load
    from eval.run_eval import Store
    from theorem.engine.executor import (
        ReadContext,
        count_tokens,
        execute_read,
        execute_rows,
        limits,
    )
    from theorem.parser import parse
    from theorem.verifier import verify

    queries = load_queries(model)
    schema = derive_schema(json.loads((DATA / f"{graph}_schema.json").read_text()))
    db = OUT / f"db-full-{graph}"
    print(f"[{graph}] loading store from {db} ...")
    store = Store(db)
    if not store.nodes:
        load(DATA / f"{graph}_simplekg.json", store)
        store.snapshot()
    print(f"[{graph}] {len(store.nodes)} nodes, {len(store.edge_index)} edges")

    # The read path's only write is query_traffic telemetry: one WAL
    # record per node touched by every follow (executor._follow). It has
    # no bearing on answer correctness and dominates runtime on the large
    # graphs, so it is disabled here. Verified to be the sole store.apply
    # call site in the read executor.
    store.apply = lambda record: 0

    signal.signal(signal.SIGALRM, _alarm)
    PUB.mkdir(parents=True, exist_ok=True)
    # The engine's own ceilings are tighter than the official metric's,
    # so pin them to it: the published number must be what the official
    # comparator's timeout allows, not what a default happens to be.
    exec_limits = functools.partial(limits, seconds=EXEC_TIMEOUT_S, max_rows=10**9)
    partial = PUB / f"exec-{model}-{graph}.partial.json"
    results = json.loads(partial.read_text()) if partial.exists() else []
    done = {r["qid"] for r in results}
    if done:
        print(f"[{graph}] resuming, {len(done)} already scored")
    questions = questions_for(graph)
    for i, q in enumerate(questions):
        if q["qid"] in done or q["qid"] not in queries:
            continue  # not yet generated; a later resume run picks it up
        query = queries[q["qid"]]
        rec = {
            "qid": q["qid"],
            "category": q["from_template"]["match_category"],
            "query": query,
        }
        try:
            signal.alarm(EXEC_TIMEOUT_S)
            t0 = time.perf_counter()
            plans = verify(parse(query), schema)
            with exec_limits():
                rows = execute_rows(plans, store, schema)
            rec["latency_ms"] = round(1000 * (time.perf_counter() - t0), 2)
            rec["executable"] = True
            rec["ex"] = score(rows, q["gold_cypher"], q["answer_json"])
            rec["n_rows"] = len(rows)
            rec["query_tokens"] = count_tokens(query)
            # What the agent actually receives back, rendered and subject
            # to the same token budget a real session would apply.
            try:
                with exec_limits():
                    rendered = execute_read(
                        verify(parse(query), schema), store, schema, ReadContext()
                    )
                rec["result_tokens"] = count_tokens(rendered)
            except Exception:
                pass
        except (Exception, MemoryError) as e:
            rec["executable"] = False
            rec["ex"] = 0.0
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
        finally:
            signal.alarm(0)
        results.append(rec)
        if len(results) % 25 == 0:
            partial.write_text(json.dumps(results, indent=1))
            ok = sum(r["ex"] for r in results)
            print(
                f"[{graph}] {len(results)}/{len(questions)} "
                f"EX so far {ok / len(results):.3f}",
                flush=True,
            )
    ex_score = sum(r["ex"] for r in results) / len(results) if results else 0.0
    if len(results) < len(questions):
        # Incomplete (generation still running): keep it as a partial so a
        # later run resumes, and never let report() read it as a result.
        partial.write_text(json.dumps(results, indent=1))
        print(
            f"[{graph}] INCOMPLETE {len(results)}/{len(questions)} scored, "
            f"EX so far {ex_score:.4f}; rerun after generation finishes",
            flush=True,
        )
        return
    out = PUB / f"exec-{model}-{graph}.json"
    out.write_text(json.dumps(results, indent=1))
    partial.unlink(missing_ok=True)
    print(f"[{graph}] EX {ex_score:.4f} over {len(results)} -> {out}", flush=True)


# ---- phase 3: report --------------------------------------------------


def report(model: str, strict: bool = True) -> None:
    all_results = []
    missing = []
    for g in TEST_GRAPHS:
        path = PUB / f"exec-{model}-{g}.json"
        if not path.exists():
            missing.append(g)
            continue
        for r in json.loads(path.read_text()):
            r["graph"] = g
            all_results.append(r)
    if missing and strict:
        print(f"missing graphs: {missing}; run exec --graph <g> for each")
        sys.exit(1)
    if not all_results:
        print("no completed graphs yet")
        return
    n = len(all_results)
    by = lambda key: sorted({r[key] for r in all_results})  # noqa: E731

    def ex_of(rs):
        return round(sum(r["ex"] for r in rs) / len(rs), 4) if rs else None

    # These two groups used to be unreachable no matter what query was
    # written, because list properties were flattened to strings and edge
    # properties were not loaded. Both are supported now, so this is kept
    # as a breakdown of the questions that were hardest to reach rather
    # than as a ceiling.
    import re as _re

    scored = {r["qid"] for r in all_results}
    list_gold, edge_prop = set(), set()
    for q in questions_for():
        if q["qid"] not in scored:
            continue
        if any(
            isinstance(c, list)
            for row in json.loads(q["answer_json"])
            for c in (row if isinstance(row, list) else [row])
        ):
            list_gold.add(q["qid"])
        if _re.search(r"\br\d+\.\w+", q["gold_cypher"]):
            edge_prop.add(q["qid"])
    unreachable = list_gold | edge_prop

    summary = {
        "benchmark": "CypherBench test set (megagonlabs/cypherbench)",
        "protocol": (
            "full test set, all 7 test graphs, all match categories "
            "(no slice), full unsampled graphs, zero-shot single "
            "generation, no repair retry, official execution-accuracy "
            "comparison vs published gold answers"
        ),
        "system": "theorem v0 grammar-prompting + theorem engine",
        "model": model,
        "graphs_completed": [g for g in TEST_GRAPHS if g not in missing],
        "graphs_missing": missing,
        "n": n,
        "overall_ex": ex_of(all_results),
        # The theorem prompt's worked examples and return-discipline rules
        # were written while iterating on the nba graph, so nba is the one
        # graph this system has effectively seen. The held-out figure
        # excludes it and is the number to quote.
        "held_out_ex": ex_of([r for r in all_results if r["graph"] != "nba"]),
        "held_out_n": sum(r["graph"] != "nba" for r in all_results),
        "executable_pct": round(
            sum(r["executable"] for r in all_results) / n, 4
        ),
        "hard_data_shapes": {
            "list_valued_gold": {
                "n": len(list_gold),
                "ex": ex_of([r for r in all_results if r["qid"] in list_gold]),
            },
            "needs_edge_properties": {
                "n": len(edge_prop),
                "ex": ex_of([r for r in all_results if r["qid"] in edge_prop]),
            },
            "note": (
                "multi-valued properties and properties on the edge itself; "
                "both were unanswerable before the language supported them"
            ),
        },
        "ex_excluding_hard_shapes": ex_of(
            [r for r in all_results if r["qid"] not in unreachable]
        ),
        "by_graph": {
            g: ex_of([r for r in all_results if r["graph"] == g]) for g in by("graph")
        },
        "by_category": {
            c: {
                "ex": ex_of([r for r in all_results if r["category"] == c]),
                "n": sum(r["category"] == c for r in all_results),
            }
            for c in by("category")
        },
    }
    out = PUB / f"results-public-{model}.json"
    out.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"wrote {out}")


# ---- orchestration ----------------------------------------------------


def run_all(model: str, workers: int) -> None:
    gen(model, workers)
    if audit(model):
        gen(model, workers)  # cache-backed: only refills what audit dropped
    for g in TEST_GRAPHS:
        if (PUB / f"exec-{model}-{g}.json").exists():
            print(f"[{g}] already executed, skipping")
            continue
        # per-graph subprocess so each big graph's memory is returned
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.run_public",
                "exec",
                "--graph",
                g,
                "--model",
                model,
            ],
        )
        if r.returncode != 0:
            print(f"[{g}] exec failed with {r.returncode}")
            sys.exit(1)
    report(model)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "exec", "report", "all", "audit"])
    ap.add_argument("--graph", default=None)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--partial",
        action="store_true",
        help="report on the graphs finished so far instead of requiring all 7",
    )
    args = ap.parse_args()
    if args.cmd == "gen":
        gen(args.model, args.workers)
    elif args.cmd == "audit":
        audit(args.model)
    elif args.cmd == "exec":
        if not args.graph:
            sys.exit("exec needs --graph")
        exec_graph(args.graph, args.model)
    elif args.cmd == "report":
        report(args.model, strict=not args.partial)
    else:
        run_all(args.model, args.workers)


if __name__ == "__main__":
    main()
