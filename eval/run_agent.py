"""Agent-loop benchmark: convergence under retry, on unseen graphs.

CypherBench measures one-shot translation. An agent does not work that
way: it writes a query, reads the error or the result, and tries again.
What matters is whether it converges, how many turns it costs, and how
many tokens the whole loop burns. A language can be worse at one-shot and
better at that, or the reverse, and only the second one is the thing an
agent actually pays for.

Held out by construction:
- Questions and graphs come from CypherBench's TRAIN split, whose four
  graphs (art, biology, soccer, terrorist_attack) share no schema, no
  question and no qid with the test split every earlier number here used.
  theorem's prompt was written against `nba`, which is not among them.

Fair by construction:
- Both arms run the identical loop: same question, same retry budget,
  same error-feedback mechanics, same comparator, same model.
- Token accounting covers the WHOLE loop including the prompt, so
  theorem's much larger tutorial is charged against it every turn.

  uv run python -m eval.run_agent --graph terrorist_attack [--n 100]
  uv run python -m eval.run_agent report
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from eval.run_public import (
    DATA,
    EXEC_TIMEOUT_S,
    OUT,
    PUB,
    _alarm,
    count_tokens_helper as count_tokens,
    score,
)

TRAIN_GRAPHS = ["terrorist_attack", "soccer"]
MAX_TURNS = 3
AGENT_OUT = PUB / "agent"


def questions(graph: str, n: int, seed: int = 11) -> list[dict]:
    """A stratified sample of train questions for one graph.

    Stratified by match category so a graph's easy majority cannot decide
    the result, and seeded so both arms see exactly the same questions.
    """
    import random
    from collections import defaultdict

    all_q = [
        q
        for q in json.loads((DATA / "train.json").read_text())
        if q["graph"] == graph
    ]
    by_cat = defaultdict(list)
    for q in all_q:
        by_cat[q["from_template"]["match_category"]].append(q)
    rng = random.Random(seed)
    for v in by_cat.values():
        rng.shuffle(v)
    picked: list[dict] = []
    cats = sorted(by_cat)
    while len(picked) < min(n, len(all_q)):
        added = False
        for c in cats:
            if by_cat[c] and len(picked) < n:
                picked.append(by_cat[c].pop())
                added = True
        if not added:
            break
    return picked


# ---- arms -------------------------------------------------------------


class TheoremArm:
    name = "theorem"

    def __init__(self, graph: str):
        from eval.load_graph import derive_schema, load
        from theorem.engine.storage import Store

        self.cb_schema = json.loads((DATA / f"{graph}_schema.json").read_text())
        self.schema = derive_schema(self.cb_schema)
        self.store = Store(OUT / f"db-full-{graph}")
        if not self.store.nodes:
            load(DATA / f"{graph}_simplekg.json", self.store)
            self.store.snapshot()
        self.store.apply = lambda record: 0

    def prompt(self, question: str) -> str:
        from eval.prompts import theorem_prompt

        return theorem_prompt(self.schema, question)

    def run(self, query: str):
        from theorem.engine.executor import execute_rows
        from theorem.parser import parse
        from theorem.verifier import verify

        rows = execute_rows(verify(parse(query), self.schema), self.store, self.schema)
        return rows, _render(rows)

    def close(self):
        pass


class CypherArm:
    name = "text2cypher"

    def __init__(self, graph: str):
        from eval.run_cypher_public import (
            HOST_LOADED,
            connect,
            load_from_host,
            official_schema_str,
            start_graph,
        )

        self.schema_str = official_schema_str(graph)
        host = graph in HOST_LOADED or Path(
            DATA / f"{graph}_simplekg.json"
        ).stat().st_size > 50_000_000
        start_graph(graph, host_load=host)
        self.driver = connect(expect_empty=host)
        if host:
            load_from_host(self.driver, graph)

    def prompt(self, question: str) -> str:
        from eval.run_cypher_public import NL2CYPHER_PROMPT_DEFAULT

        return NL2CYPHER_PROMPT_DEFAULT.format(
            schema=self.schema_str, question=question
        )

    def run(self, query: str):
        from eval.run_cypher_public import run_cypher

        recs = run_cypher(self.driver, query)
        rows = [list(r.values()) for r in recs]
        return rows, _render_cypher(recs)

    def close(self):
        from eval.run_cypher_public import stop_container

        self.driver.close()
        stop_container()


def _render(rows) -> str:
    if not rows:
        return "results: 0 of 0, complete"
    head = f"results: {len(rows)} of {len(rows)}, complete"
    return head + "\n" + "\n".join(", ".join(str(c) for c in r) for r in rows[:50])


def _render_cypher(recs) -> str:
    if not recs:
        return "results: 0 of 0, complete"
    cols = list(recs[0].keys())
    head = f"results: {len(recs)} of {len(recs)}, complete\ncolumns: " + ", ".join(cols)
    return head + "\n" + "\n".join(
        ", ".join(str(r.get(c)) for c in cols) for r in recs[:50]
    )


REPAIR = (
    "Your previous query failed.\n\nQuery:\n{q}\n\nError:\n{e}\n\n"
    "Write a corrected query. Output ONLY the query text, no explanation, "
    "no code fences.\n"
)


# ---- the loop ---------------------------------------------------------


def solve(arm, q: dict, model: str) -> dict:
    """Let the arm try up to MAX_TURNS times, feeding errors back."""
    from eval.run_eval import llm

    base = arm.prompt(q["nl_question"])
    rec = {
        "qid": q["qid"],
        "arm": arm.name,
        "category": q["from_template"]["match_category"],
        "turns": 0,
        "solved": False,
        "tokens": 0,
        "latency_ms": 0.0,
        "errors": [],
    }
    prompt = base
    query = ""
    for turn in range(1, MAX_TURNS + 1):
        rec["turns"] = turn
        rec["tokens"] += count_tokens(prompt)
        query = llm(prompt, model, f"agent-{arm.name}-{q['qid']}-t{turn}")
        rec["tokens"] += count_tokens(query)
        try:
            signal.alarm(EXEC_TIMEOUT_S)
            t0 = time.perf_counter()
            rows, rendered = arm.run(query)
            rec["latency_ms"] += 1000 * (time.perf_counter() - t0)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:400]
            rec["errors"].append(err)
            rec["tokens"] += count_tokens(err)
            prompt = base + "\n" + REPAIR.format(q=query, e=err)
            continue
        finally:
            signal.alarm(0)
        rec["tokens"] += count_tokens(rendered)
        if score(rows, q["gold_cypher"], q["answer_json"]) == 1.0:
            rec["solved"] = True
            rec["query"] = query
            return rec
        # Ran but wrong. An agent cannot see the gold answer, so all it
        # can do is look at what came back; feed that and let it reconsider.
        prompt = (
            base
            + f"\nYour previous query ran but the result looks wrong.\n\n"
            f"Query:\n{query}\n\nResult:\n{rendered[:600]}\n\n"
            "Write a corrected query. Output ONLY the query text.\n"
        )
    rec["query"] = query
    return rec


def run_graph(graph: str, n: int, model: str, which: str) -> None:
    AGENT_OUT.mkdir(parents=True, exist_ok=True)
    qs = questions(graph, n)
    print(f"[{graph}] {len(qs)} train questions, up to {MAX_TURNS} turns each")
    signal.signal(signal.SIGALRM, _alarm)
    for cls in (TheoremArm, CypherArm):
        if which != "both" and cls.name != which:
            continue
        out = AGENT_OUT / f"agent-{cls.name}-{model}-{graph}.json"
        if out.exists():
            print(f"[{graph}] {cls.name} already done")
            continue
        arm = cls(graph)
        results = []
        try:
            for i, q in enumerate(qs):
                results.append(solve(arm, q, model))
                if (i + 1) % 20 == 0:
                    s = sum(r["solved"] for r in results)
                    print(
                        f"  [{cls.name}] {i + 1}/{len(qs)} solved {s / len(results):.2f}",
                        flush=True,
                    )
        finally:
            arm.close()
        out.write_text(json.dumps(results, indent=1))
        s = sum(r["solved"] for r in results)
        print(f"[{graph}] {cls.name}: solved {s}/{len(results)}", flush=True)


def report(model: str) -> None:
    arms: dict[str, list] = {}
    for p in sorted(AGENT_OUT.glob(f"agent-*-{model}-*.json")):
        rows = json.loads(p.read_text())
        arms.setdefault(rows[0]["arm"], []).extend(rows)
    if not arms:
        print("no agent results yet")
        return

    def pct(x):
        return f"{100 * x:.1f}"

    print(f"{'arm':14s} {'n':>5s} {'solve@1':>8s} {'solve@2':>8s} {'solve@3':>8s} "
          f"{'turns':>6s} {'tokens':>8s} {'ms':>8s}")
    summary = {}
    for name, rows in arms.items():
        n = len(rows)
        at = {
            k: sum(r["solved"] and r["turns"] <= k for r in rows) / n
            for k in (1, 2, 3)
        }
        solved = [r for r in rows if r["solved"]]
        turns = sum(r["turns"] for r in solved) / len(solved) if solved else 0
        toks = sum(r["tokens"] for r in rows) / n
        ms = sum(r["latency_ms"] for r in rows) / n
        print(
            f"{name:14s} {n:5d} {pct(at[1]):>8s} {pct(at[2]):>8s} {pct(at[3]):>8s} "
            f"{turns:6.2f} {toks:8.0f} {ms:8.1f}"
        )
        summary[name] = {
            "n": n,
            "solve_at_1": round(at[1], 4),
            "solve_at_2": round(at[2], 4),
            "solve_at_3": round(at[3], 4),
            "mean_turns_when_solved": round(turns, 3),
            "mean_tokens_per_question": round(toks, 1),
            "mean_exec_ms_per_question": round(ms, 2),
        }
    (AGENT_OUT / f"summary-{model}.json").write_text(json.dumps(summary, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "report"])
    ap.add_argument("--graph", default="terrorist_attack")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--arm", default="both", choices=["both", "theorem", "text2cypher"])
    args = ap.parse_args()
    if args.cmd == "report":
        report(args.model)
        return
    if args.graph not in TRAIN_GRAPHS:
        sys.exit(f"--graph must be one of {TRAIN_GRAPHS} (the held-out split)")
    run_graph(args.graph, args.n, args.model, args.arm)


if __name__ == "__main__":
    main()
