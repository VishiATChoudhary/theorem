"""CypherBench slice eval: theorem grammar-prompting vs text2cypher.

Both conditions use the same model, the same questions, and one repair
retry on execution error. Scoring is execution accuracy: normalized
set-of-rows comparison against CypherBench gold answers.

Usage:
  uv run python -m eval.run_eval --n 60 [--graph nba] [--model MODEL]
  uv run python -m eval.run_eval --smoke        # 3 questions

Requires: claude CLI on PATH. Neo4j via docker for condition A
(started automatically; falls back to published-baseline mode if
docker is unavailable).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from eval.load_graph import derive_schema, load
from eval.prompts import cypher_prompt, repair_prompt, theorem_prompt
from theorem.engine.executor import (
    ReadContext,
    count_tokens,
    execute_read,
    execute_rows,
)
from theorem.engine.storage import Store
from theorem.parser import ParseError, parse
from theorem.verifier import VerifyError, verify

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "out"
CACHE = OUT / "cache"

# Question categories expressible in theorem v0 (no union, no optional
# match, no edge-property filters). Both conditions run on the SAME slice.
EXPRESSIBLE = {
    "basic_(n)",
    "basic_(n*)",
    "basic_(n)-(m0)",
    "basic_(n)-(m0*)",
    "basic_(n)-(m0)-(m1*)",
    "basic_(n)-(m0*),(n)-(m1*)",
    "special_three-node-groupby",
    "special_comparison",
}
MULTIHOP = {
    "basic_(n)-(m0)-(m1*)",
    "basic_(n)-(m0*),(n)-(m1*)",
    "special_three-node-groupby",
}

NEO4J_CONTAINER = "theorem-eval-neo4j"
NEO4J_AUTH = ("neo4j", "theoremeval1")
PUBLISHED_BASELINES = {
    "claude-3.5-sonnet": 61.6,
    "gpt-4o": 60.2,
}


def llm(prompt: str, model: str, cache_key: str) -> str:
    import hashlib

    CACHE.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()[:10]
    cache_file = CACHE / f"{cache_key}-{digest}.txt"
    if cache_file.exists():
        return cache_file.read_text()
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--max-turns", "1"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
    )
    text = _extract_query(result.stdout)
    cache_file.write_text(text)
    return text


GL_VERBS = (
    "find ",
    "follow ",
    "group ",
    "count ",
    "sum ",
    "avg ",
    "min ",
    "max ",
    "compute ",
    "return ",
    "continue ",
    "schema",
)
CY_STARTS = ("MATCH", "CALL", "WITH", "UNWIND", "OPTIONAL", "RETURN")


def _extract_query(raw: str) -> str:
    """Strip markdown fences and any prose before the first query line.
    Applied identically to both conditions."""
    text = raw.strip()
    fence = re.search(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.lower().startswith(GL_VERBS) or s.startswith(CY_STARTS):
            return "\n".join(lines[i:]).strip()
    return text


# ---- answer normalization and scoring ---------------------------------


def _norm_cell(v):
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f"{f:.4f}"
    return str(v).strip().casefold()


def norm_rows(rows) -> frozenset:
    out = set()
    for row in rows:
        if not isinstance(row, (list, tuple)):
            row = [row]
        flat = []
        for cell in row:
            if isinstance(cell, dict):  # neo4j node/map: use name-ish value
                cell = cell.get("name", json.dumps(cell, sort_keys=True))
            if isinstance(cell, list):
                cell = ", ".join(str(x) for x in cell)
            flat.append(_norm_cell(cell))
        out.add(tuple(flat))
    return frozenset(out)


def rows_match(got, gold) -> bool:
    """Strict normalized set comparison; no shape leniency."""
    return norm_rows(got) == norm_rows(gold)


# ---- condition B: theorem -------------------------------------------


def run_theorem(query: str, store: Store, schema) -> list[list]:
    plans = verify(parse(query), schema)
    return execute_rows(plans, store, schema)


def eval_theorem(question: dict, store: Store, schema, model: str) -> dict:
    q = question["nl_question"]
    qid = question["qid"]
    prompt = theorem_prompt(schema, q)
    query = llm(prompt, model, f"gl-{qid}")
    syntax_ok, error = True, None
    try:
        rows = run_theorem(query, store, schema)
    except (ParseError, VerifyError, Exception) as e:
        syntax_ok = False
        error = str(e)
        retry = llm(prompt + "\n" + repair_prompt(query, error), model, f"gl-{qid}-r")
        query = retry
        try:
            rows = run_theorem(retry, store, schema)
            syntax_ok = True
            error = None
        except Exception as e2:
            return {
                "qid": qid,
                "ok": False,
                "syntax_ok": False,
                "error": str(e2),
                "query": query,
                "rows": None,
            }
    gold = json.loads(question["answer_json"])
    ok = rows_match(rows, gold)
    # result token cost: rendered result for the winning query
    tokens = None
    try:
        rendered = execute_read(
            verify(parse(query), schema), store, schema, ReadContext()
        )
        tokens = count_tokens(rendered)
    except Exception:
        pass
    return {
        "qid": qid,
        "ok": ok,
        "syntax_ok": syntax_ok,
        "query": query,
        "rows": rows[:20],
        "gold": gold[:20],
        "result_tokens": tokens,
    }


# ---- condition A: text2cypher on Neo4j --------------------------------


def neo4j_available() -> bool:
    return (
        shutil.which("docker") is not None
        and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    )


def ensure_neo4j() -> None:
    running = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name={NEO4J_CONTAINER}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if running:
        return
    subprocess.run(["docker", "rm", "-f", NEO4J_CONTAINER], capture_output=True)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            NEO4J_CONTAINER,
            "-p",
            "7687:7687",
            "-p",
            "7474:7474",
            "-e",
            f"NEO4J_AUTH={NEO4J_AUTH[0]}/{NEO4J_AUTH[1]}",
            "neo4j:5",
        ],
        check=True,
        capture_output=True,
    )
    for _ in range(60):
        time.sleep(2)
        probe = subprocess.run(
            [
                "docker",
                "exec",
                NEO4J_CONTAINER,
                "cypher-shell",
                "-u",
                NEO4J_AUTH[0],
                "-p",
                NEO4J_AUTH[1],
                "RETURN 1;",
            ],
            capture_output=True,
        )
        if probe.returncode == 0:
            return
    raise RuntimeError("neo4j container did not become ready")


LAST_RAW_RESULT = {"text": ""}


def neo4j_query(cypher: str, timeout: int = 60) -> list[list]:
    """Run cypher via cypher-shell, parse its output rows. The raw textual
    output (what an agent would actually receive, header line included) is
    kept in LAST_RAW_RESULT for token accounting comparable to theorem's
    rendered output."""
    with tempfile.NamedTemporaryFile("w", suffix=".cypher", delete=False) as f:
        f.write(cypher if cypher.rstrip().endswith(";") else cypher + ";")
        path = f.name
    try:
        subprocess.run(
            ["docker", "cp", path, f"{NEO4J_CONTAINER}:/tmp/q.cypher"],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            [
                "docker",
                "exec",
                NEO4J_CONTAINER,
                "cypher-shell",
                "-u",
                NEO4J_AUTH[0],
                "-p",
                NEO4J_AUTH[1],
                "--format",
                "plain",
                "-f",
                "/tmp/q.cypher",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500])
    LAST_RAW_RESULT["text"] = result.stdout
    lines = result.stdout.strip().splitlines()
    if not lines:
        return []
    rows = []
    for line in lines[1:]:  # first line is the header
        cells = _split_shell_row(line)
        rows.append([_parse_shell_cell(c) for c in cells])
    return rows


def _split_shell_row(line: str) -> list[str]:
    cells, cur, depth, in_str = [], [], 0, False
    for ch in line:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif in_str:
            cur.append(ch)
        elif ch in "[{(":
            depth += 1
            cur.append(ch)
        elif ch in "]})":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def _parse_shell_cell(cell: str):
    cell = cell.strip()
    if cell.startswith('"') and cell.endswith('"'):
        return cell[1:-1].replace('""', '"')
    if cell in ("NULL", "null"):
        return None
    if cell in ("TRUE", "true"):
        return True
    if cell in ("FALSE", "false"):
        return False
    try:
        return int(cell)
    except ValueError:
        pass
    try:
        return float(cell)
    except ValueError:
        pass
    if cell.startswith("[") and cell.endswith("]"):
        inner = cell[1:-1].strip()
        if not inner:
            return []
        return [_parse_shell_cell(c) for c in _split_shell_row(inner)]
    return cell


def _cypher_literal(v) -> str:
    """JSON value -> Cypher literal (Cypher map keys are bare identifiers)."""
    if isinstance(v, dict):
        return (
            "{" + ", ".join(f"`{k}`: {_cypher_literal(x)}" for k, x in v.items()) + "}"
        )
    if isinstance(v, list):
        return "[" + ", ".join(_cypher_literal(x) for x in v) + "]"
    return json.dumps(v)


def load_neo4j(graph_json: Path) -> None:
    """Load the simplekg into neo4j with batched UNWIND statements."""
    marker = neo4j_query("MATCH (n) RETURN count(n)")
    kg = json.loads(graph_json.read_text())
    if marker and marker[0][0] == len(kg["entities"]):
        return  # already loaded
    neo4j_query("MATCH (n) DETACH DELETE n", timeout=300)
    by_label = defaultdict(list)
    for ent in kg["entities"]:
        props = {"name": ent.get("name") or ent["eid"], "eid": ent["eid"]}
        for k, v in (ent.get("properties") or {}).items():
            if v is not None:
                props[k] = v
        by_label[ent["label"]].append(props)
    for label, items in by_label.items():
        for i in range(0, len(items), 500):
            batch = _cypher_literal(items[i : i + 500])
            neo4j_query(
                f"UNWIND {batch} AS row CREATE (n:{label}) SET n = row", timeout=300
            )
        neo4j_query(
            f"CREATE INDEX {label.lower()}_eid IF NOT EXISTS FOR (n:{label}) ON (n.eid)"
        )
    rels = defaultdict(list)
    for rel in kg["relations"]:
        props = {
            k: v for k, v in (rel.get("properties") or {}).items() if v is not None
        }
        rels[rel["label"]].append({"s": rel["subj_id"], "o": rel["obj_id"], "p": props})
    for label, items in rels.items():
        for i in range(0, len(items), 500):
            batch = _cypher_literal(items[i : i + 500])
            neo4j_query(
                f"UNWIND {batch} AS row "
                f"MATCH (a {{eid: row.s}}), (b {{eid: row.o}}) "
                f"CREATE (a)-[r:{label}]->(b) SET r = row.p",
                timeout=600,
            )


def eval_cypher(question: dict, cb_schema: dict, model: str) -> dict:
    q = question["nl_question"]
    qid = question["qid"]
    prompt = cypher_prompt(cb_schema, q)
    query = llm(prompt, model, f"cy-{qid}")
    try:
        rows = neo4j_query(query)
        syntax_ok = True
    except Exception as e:
        retry = llm(prompt + "\n" + repair_prompt(query, str(e)), model, f"cy-{qid}-r")
        query = retry
        try:
            rows = neo4j_query(retry)
            syntax_ok = True
        except Exception as e2:
            return {
                "qid": qid,
                "ok": False,
                "syntax_ok": False,
                "error": str(e2)[:300],
                "query": query,
                "rows": None,
            }
    gold = json.loads(question["answer_json"])
    ok = rows_match(rows, gold)
    # comparable accounting: the full textual result each system hands the
    # agent (cypher-shell output with its header, like theorem's render)
    tokens = count_tokens(LAST_RAW_RESULT["text"])
    return {
        "qid": qid,
        "ok": ok,
        "syntax_ok": syntax_ok,
        "query": query,
        "rows": rows[:20],
        "gold": gold[:20],
        "result_tokens": tokens,
    }


# ---- harness ----------------------------------------------------------


def pick_questions(graph: str, n: int, seed: int = 7) -> list[dict]:
    tests = json.loads((DATA / "test.json").read_text())
    pool = [
        t
        for t in tests
        if t["graph"] == graph and t["from_template"]["match_category"] in EXPRESSIBLE
    ]
    by_cat = defaultdict(list)
    for t in pool:
        by_cat[t["from_template"]["match_category"]].append(t)
    rng = random.Random(seed)
    picked: list[dict] = []
    cats = sorted(by_cat)
    while len(picked) < min(n, len(pool)):
        for cat in cats:
            if by_cat[cat] and len(picked) < n:
                picked.append(by_cat[cat].pop(rng.randrange(len(by_cat[cat]))))
    return picked


def slice_of(question: dict) -> str:
    return (
        "multi-hop"
        if question["from_template"]["match_category"] in MULTIHOP
        else "1-hop"
    )


def summarize(results: list[dict], questions: list[dict]) -> dict:
    by_qid = {q["qid"]: q for q in questions}
    total = len(results)
    overall = sum(r["ok"] for r in results) / total if total else 0
    out = {"overall": round(100 * overall, 1), "n": total}
    for sl in ("multi-hop", "1-hop"):
        rs = [r for r in results if slice_of(by_qid[r["qid"]]) == sl]
        out[sl] = round(100 * sum(r["ok"] for r in rs) / len(rs), 1) if rs else None
        out[f"n_{sl}"] = len(rs)
    out["syntax_validity"] = (
        round(100 * sum(r["syntax_ok"] for r in results) / total, 1) if total else 0
    )
    toks = [r["result_tokens"] for r in results if r.get("result_tokens") is not None]
    out["mean_result_tokens"] = round(sum(toks) / len(toks), 1) if toks else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="nba")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--skip-cypher", action="store_true")
    ap.add_argument(
        "--tag", default=None, help="suffix for the results file: results-<tag>.json"
    )
    args = ap.parse_args()
    n = 3 if args.smoke else args.n

    questions = pick_questions(args.graph, n)
    print(
        f"{len(questions)} questions "
        f"({sum(slice_of(q) == 'multi-hop' for q in questions)} multi-hop)"
    )

    cb_schema = json.loads((DATA / f"{args.graph}_schema.json").read_text())
    schema = derive_schema(cb_schema)
    db = OUT / f"db-{args.graph}"
    store = Store(db)
    if not store.nodes:
        load(DATA / f"{args.graph}_simplekg.json", store)
    print(f"engine: {len(store.nodes)} nodes, {len(store.edge_index)} edges")

    gl_results = []
    for i, q in enumerate(questions):
        r = eval_theorem(q, store, schema, args.model)
        gl_results.append(r)
        print(
            f"[gl {i + 1}/{len(questions)}] {'OK ' if r['ok'] else 'MISS'} {q['nl_question'][:70]}"
        )

    cy_results = []
    cypher_mode = "live"
    if args.skip_cypher or not neo4j_available():
        cypher_mode = "published-baseline"
        print("cypher condition: docker unavailable, using published baselines")
    else:
        ensure_neo4j()
        load_neo4j(DATA / f"{args.graph}_simplekg.json")
        for i, q in enumerate(questions):
            r = eval_cypher(q, cb_schema, args.model)
            cy_results.append(r)
            print(
                f"[cy {i + 1}/{len(questions)}] {'OK ' if r['ok'] else 'MISS'} {q['nl_question'][:70]}"
            )

    excluded_note = (
        "categories excluded (not expressible in theorem v0): "
        "union, optional-match, time-sensitive/edge-properties; "
        "both conditions ran on the same expressible slice"
    )
    out = {
        "graph": args.graph,
        "model": args.model,
        "n": len(questions),
        "slice_note": excluded_note,
        "theorem": summarize(gl_results, questions),
        "text2cypher": summarize(cy_results, questions)
        if cy_results
        else {"mode": "published", **PUBLISHED_BASELINES},
        "cypher_mode": cypher_mode,
        "details": {"theorem": gl_results, "text2cypher": cy_results},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    name = f"results-{args.tag}.json" if args.tag else "results.json"
    (OUT / name).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "details"}, indent=1))


if __name__ == "__main__":
    main()
