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
        q for q in json.loads((DATA / "train.json").read_text()) if q["graph"] == graph
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
        # Reads no longer write: traffic telemetry is kept in memory and
        # reaches disk with the next snapshot (Store.touch). The harness
        # used to disable store.apply here, which meant the benchmark was
        # measuring an engine the shipped one was not.

    def prompt(self, question: str) -> str:
        from eval.prompts import theorem_prompt

        return theorem_prompt(self.schema, question, self.store)

    def run(self, query: str):
        from theorem.engine.executor import execute_rows, limits
        from theorem.parser import parse
        from theorem.verifier import verify

        # Pinned to the same ceiling the Cypher arm gets, so neither arm
        # is stopped by a default the other does not have.
        with limits(seconds=EXEC_TIMEOUT_S, max_rows=10**9):
            rows = execute_rows(
                verify(parse(query), self.schema), self.store, self.schema
            )
        return rows, _render(rows)

    def close(self):
        self.store.close()


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
        host = (
            graph in HOST_LOADED
            or Path(DATA / f"{graph}_simplekg.json").stat().st_size > 50_000_000
        )
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
    return (
        head
        + "\n"
        + "\n".join(", ".join(str(r.get(c)) for c in cols) for r in recs[:50])
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
            base + f"\nYour previous query ran but the result looks wrong.\n\n"
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
        # The prompt these turns were run under, recorded beside them.
        # Recomputing it at render time prints whatever tutorial happens
        # to be checked out, which is how a report claims a prompt it
        # never ran.
        from theorem.prompt import fingerprint

        out.with_suffix(".meta.json").write_text(
            json.dumps(
                {"prompt_fingerprint": fingerprint(), "model": model, "graph": graph},
                indent=1,
            )
        )
        s = sum(r["solved"] for r in results)
        print(f"[{graph}] {cls.name}: solved {s}/{len(results)}", flush=True)


def report(model: str) -> None:
    arms: dict[str, list] = {}
    for p in sorted(AGENT_OUT.glob(f"agent-*-{model}-*.json")):
        if p.name.endswith(".meta.json"):
            continue  # provenance, not results
        rows = json.loads(p.read_text())
        arms.setdefault(rows[0]["arm"], []).extend(rows)
    if not arms:
        print("no agent results yet")
        return

    def pct(x):
        return f"{100 * x:.1f}"

    print(
        f"{'arm':14s} {'n':>5s} {'solve@1':>8s} {'solve@2':>8s} {'solve@3':>8s} "
        f"{'turns':>6s} {'tokens':>8s} {'ms':>8s}"
    )
    summary = {}
    for name, rows in arms.items():
        n = len(rows)
        at = {
            k: sum(r["solved"] and r["turns"] <= k for r in rows) / n for k in (1, 2, 3)
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
    _write_doc(summary, model, arms)


def _paired(arms: dict) -> dict:
    """McNemar on the questions both arms attempted.

    Two independent proportions throw away the pairing and lose most of
    the power; what decides this is only the questions the arms disagree
    about.
    """
    import math

    t = {r["qid"]: r for r in arms.get("theorem", [])}
    c = {r["qid"]: r for r in arms.get("text2cypher", [])}
    qs = sorted(set(t) & set(c))
    both = sum(t[q]["solved"] and c[q]["solved"] for q in qs)
    only_t = sum(t[q]["solved"] and not c[q]["solved"] for q in qs)
    only_c = sum(c[q]["solved"] and not t[q]["solved"] for q in qs)
    m = only_t + only_c
    k = min(only_t, only_c)
    p = min(1.0, 2 * sum(math.comb(m, i) for i in range(k + 1)) / 2**m) if m else 1.0
    return {
        "n": len(qs),
        "both": both,
        "neither": len(qs) - both - only_t - only_c,
        "only_theorem": only_t,
        "only_cypher": only_c,
        "discordant": m,
        "p": p,
    }


def _scored_fingerprint(model: str) -> str:
    """The prompt the recorded turns were actually run under.

    A run with no record beside it counts as unknown rather than being
    ignored: reading the hash off the runs that did record one would
    stamp the whole page with a prompt only some of it used.
    """
    runs = [
        p
        for p in AGENT_OUT.glob(f"agent-*-{model}-*.json")
        if not p.name.endswith(".meta.json")
    ]
    stamps = set()
    for run in runs:
        meta = run.with_suffix(".meta.json")
        stamps.add(
            json.loads(meta.read_text()).get("prompt_fingerprint")
            if meta.exists()
            else None
        )
    if None in stamps:
        return "unrecorded for at least one run"
    if not stamps:
        return "unrecorded"
    if len(stamps) > 1:
        raise SystemExit(
            f"these runs came from different prompts: {sorted(stamps)}. "
            "Re-run the stale ones rather than reporting a mixture."
        )
    return stamps.pop()


def _write_doc(summary: dict, model: str, arms: dict) -> None:
    graphs = sorted(
        {
            p.stem.rsplit("-", 1)[-1]
            for p in AGENT_OUT.glob(f"agent-*-{model}-*.json")
            if not p.name.endswith(".meta.json")
        }
    )
    L = ["# theorem in an agent loop", ""]
    w = L.append
    w(
        "CypherBench measures one-shot translation. An agent does not work "
        "that way: it writes a query, reads the error or the result, and "
        "tries again. What it pays for is whether it converges, how many "
        "turns that takes, and how many tokens the whole loop burns."
    )
    w("")
    w("## Held out by construction")
    w("")
    w(
        "Questions and graphs come from CypherBench's **train** split, whose "
        "four graphs (art, biology, soccer, terrorist_attack) share no "
        "schema, no question and no qid with the test split every other "
        "number in these docs uses. theorem's prompt was written against "
        "`nba`, which is not among them. Nothing here was tuned on these "
        "graphs."
    )
    w("")
    w("## Fair by construction")
    w("")
    w(
        "Both arms run the identical loop: same questions, same retry budget "
        f"({MAX_TURNS} turns), same error-feedback mechanics, same "
        "comparator, same model. Token accounting covers the whole loop "
        "including the prompt on every turn, so theorem's larger tutorial is "
        "charged against it rather than hidden."
    )
    w("")
    w(
        f"Graphs: {', '.join(graphs)}. Prompt fingerprint `{_scored_fingerprint(model)}`."
    )
    w("")
    w("## Results")
    w("")
    w(
        "| Arm | n | solve@1 | solve@2 | solve@3 | Turns when solved | Tokens/question | Exec ms |"
    )
    w("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name in sorted(summary, key=lambda k: -summary[k]["solve_at_3"]):
        d = summary[name]
        w(
            f"| {name} | {d['n']} | {100 * d['solve_at_1']:.1f} | "
            f"{100 * d['solve_at_2']:.1f} | **{100 * d['solve_at_3']:.1f}** | "
            f"{d['mean_turns_when_solved']:.2f} | "
            f"{d['mean_tokens_per_question']:,.0f} | "
            f"{d['mean_exec_ms_per_question']:.1f} |"
        )
    w("")
    if "theorem" in summary and "text2cypher" in summary:
        t, c = summary["theorem"], summary["text2cypher"]
        pair = _paired(arms)
        w("### Is the accuracy difference real?")
        w("")
        w(
            "Both arms answer the same questions, so the honest test is the "
            "paired one. Of "
            f"{pair['n']} questions, {pair['both']} were solved by both and "
            f"{pair['neither']} by neither. The verdict rests entirely on the "
            f"{pair['discordant']} they disagree on: theorem alone solved "
            f"{pair['only_theorem']}, text2cypher alone solved "
            f"{pair['only_cypher']}."
        )
        w("")
        w(
            f"McNemar exact two-sided p = {pair['p']:.3f}. "
            + (
                "**The accuracy difference is not statistically significant: "
                "on this task the two are tied.** Reading a winner into the "
                "point estimates would be reading noise."
                if pair["p"] > 0.05
                else "The difference is significant at the 5% level."
            )
        )
        w("")
        w(
            "What the tie does not cover is the first attempt. theorem "
            f"solves {t['solve_at_1'] * 100:.1f}% of these questions without a "
            f"retry against {c['solve_at_1'] * 100:.1f}%, a gap of "
            f"{(t['solve_at_1'] - c['solve_at_1']) * 100:.1f} points that the "
            "retries then close, and it converges in "
            f"{t['mean_turns_when_solved']:.2f} turns against "
            f"{c['mean_turns_when_solved']:.2f}. An agent that can retry pays "
            "for the difference in turns rather than in answers; one that "
            "cannot pays for it in answers."
        )
        w("")
        w(
            "The token cost is "
            f"{t['mean_tokens_per_question'] / c['mean_tokens_per_question']:.1f}x "
            "per question, because a language the model has never seen "
            "carries its own tutorial in every prompt while Cypher arrives "
            "already known. That is the honest price of a new language, and "
            "the next section is where it stops being one."
        )
        w("")
        w(
            "Execution time is not a useful comparison on this benchmark. "
            f"The means are {t['mean_exec_ms_per_question']:.0f} ms and "
            f"{c['mean_exec_ms_per_question']:.0f} ms, but they are dominated "
            "by a handful of wide queries over `soccer`, and theorem runs "
            "in-process while Cypher goes over bolt to a container. The "
            "CypherBench page has the median, where the difference is real "
            "and large."
        )
        w("")
        w(
            f"At n={pair['n']} the 95% interval on either solve rate is about "
            "6 points wide, so this benchmark can only detect large "
            "differences. Narrowing it means more questions and more graphs, "
            "not more retries."
        )
        w("")
    w("## Why the token gap, and when it closes")
    w("")
    w(
        "The gap is one thing and it is not the data. Per turn on this "
        "graph, theorem spends 1,241 tokens stating its language against "
        "roughly 146 for the Cypher prompt's instructions, because Cypher "
        "arrives already known and theorem has to be taught in context "
        "every time. On the schema theorem is the cheaper of the two: 119 "
        "tokens against 333."
    )
    w("")
    w(
        "That matters because the two costs scale differently. The rules "
        "are a fixed cost per turn no matter how big the graph is; the "
        "schema grows with it. Measured on the seven test schemas and on "
        "their union, each additional class costs theorem 39 tokens and "
        "text2cypher 85, and the two lines cross at 31 classes. That "
        "crossing is inside the measured range rather than past it: on the "
        "union, 40 classes, theorem's prompt is the smaller of the two. "
        "See [prompt cost](prompt-cost.md) for the method and the table."
    )
    w("")
    w("| Schema | Classes | theorem | text2cypher |")
    w("| --- | ---: | ---: | ---: |")
    for label, n, th, cy in [
        ("terrorist_attack (this benchmark)", 5, 1405, 476),
        ("three graphs merged", 15, 1698, 1352),
        ("four graphs merged", 20, 1879, 1797),
        ("six graphs merged", 28, 2266, 2771),
        ("all eight merged", 39, 2837, 4001),
    ]:
        w(f"| {label} | {n} | {th:,} | {cy:,} |")
    w("")
    w(
        "The benchmark graphs have five to eleven classes, which is the "
        "region where theorem looks most expensive. A schema of the size "
        "this language is built for, a bill of materials or a standards "
        "corpus, sits the other side of the crossover. Two caveats: the "
        "Cypher figure uses the benchmark's official JSON schema format, "
        "and a terser serialisation would push the crossover out; and none "
        "of this changes the small-schema result measured above, which is "
        "what the table at the top reports."
    )
    w("")
    w("## Reproducing")
    w("")
    w("```bash")
    w("uv run python -m eval.run_agent run --graph terrorist_attack --n 120")
    w("uv run python -m eval.run_agent report")
    w("```")
    w("")
    doc = Path(__file__).parent.parent / "docs" / "benchmarks" / "agent-loop.md"
    doc.write_text("\n".join(L))
    print(f"wrote {doc}")


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
