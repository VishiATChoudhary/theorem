"""How often does a wrong query look like a right answer?

Execution accuracy counts the queries a model gets right. It says nothing
about what happens when the model gets one wrong, and the two languages
behave very differently there. A Cypher query naming a label that does
not exist is legal Cypher: it matches nothing and returns an empty
result, which is indistinguishable from a question whose true answer is
empty. theorem verifies the whole query against the live schema first, so
the same mistake is refused with a message naming it.

This measures that difference directly. Start from a query known to be
correct, break it in a way models actually break queries, and record what
the caller sees:

    rejected  an error before or instead of an answer
    empty     ran, returned nothing, looks like a true empty answer
    wrong     ran, returned rows that are not the right rows
    inert     the mutation did not change the answer; not counted

`rejected` is the good outcome: the caller knows. `empty` and `wrong`
are the bad ones, and `empty` is the worse of the two, because nothing
about the result suggests looking again.

    uv run python -m eval.run_silent [--graph nba] [--arm both]

Needs Docker for the Cypher arm, nothing but the store for theorem's.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from eval.run_public import DATA, OUT, PUB, questions_for

SEED = 20260831
MUTATIONS = ("class", "edge", "property", "direction")


@dataclass
class Tally:
    arm: str
    mutation: str
    rejected: int = 0
    empty: int = 0
    wrong: int = 0
    inert: int = 0
    skipped: int = 0
    # Neo4j returns the rows and separately notifies the driver that a
    # label was unrecognised. That is a warning on a successful call, not
    # an error, and a caller reading rows never sees it; counting it
    # keeps the comparison honest about what the database did offer.
    warned: int = 0
    examples: list[dict] = field(default_factory=list)

    @property
    def counted(self) -> int:
        return self.rejected + self.empty + self.wrong

    def record(self, outcome: str, example: dict, warned: bool = False) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        if warned and outcome in ("empty", "wrong"):
            self.warned += 1
        if outcome in ("empty", "wrong") and len(self.examples) < 5:
            self.examples.append(example)


# ---- mutating a theorem query ----------------------------------------


def _theorem_mutants(query: str, schema, rng) -> dict[str, str]:
    """One mutant per kind, or nothing when the query has no such token."""
    lines = query.strip().splitlines()
    out: dict[str, str] = {}

    for i, line in enumerate(lines):
        parts = line.split()
        if parts and parts[0] == "find" and len(parts) > 1 and "class" not in out:
            cls = parts[1]
            if cls in schema.classes:
                out["class"] = _swap_line(lines, i, cls, cls + "s")
        if parts and parts[0] == "follow" and len(parts) > 3:
            edge, role = parts[2], parts[3]
            if edge in schema.edges and "edge" not in out:
                out["edge"] = _swap_line(lines, i, edge, edge + "s")
            if edge in schema.edges and "direction" not in out:
                roles = list(schema.edges[edge].roles)
                if role in roles and len(roles) == 2:
                    other = roles[0] if roles[1] == role else roles[1]
                    out["direction"] = _swap_line(lines, i, role, other, whole=True)
        m = re.search(r"where\s+(?!via\.)([a-z_][a-z0-9_]*)\s*(=|!=|<|>|<=|>=)", line)
        if m and "property" not in out:
            out["property"] = _swap_line(lines, i, m.group(1), m.group(1) + "_x")
    return out


def _swap_line(
    lines: list[str], i: int, old: str, new: str, whole: bool = False
) -> str:
    lines = list(lines)
    pattern = rf"\b{re.escape(old)}\b" if whole else re.escape(old)
    lines[i] = re.sub(pattern, new, lines[i], count=1)
    return "\n".join(lines)


# ---- mutating a Cypher query -----------------------------------------

_LABEL = re.compile(r":([A-Z][A-Za-z0-9_]*)")
_RELTYPE = re.compile(r"\[(\w*):([a-zA-Z_][A-Za-z0-9_]*)")
_PROP = re.compile(r"\.([a-z_][a-z0-9_]*)")
_ARROW_R = re.compile(r"-(\[[^\]]*\])->")
_ARROW_L = re.compile(r"<-(\[[^\]]*\])-")


def _cypher_mutants(query: str) -> dict[str, str]:
    out: dict[str, str] = {}
    label = _LABEL.search(query)
    if label:
        out["class"] = query.replace(f":{label.group(1)}", f":{label.group(1)}s", 1)
    rel = _RELTYPE.search(query)
    if rel:
        out["edge"] = query.replace(f":{rel.group(2)}", f":{rel.group(2)}s", 1)
    prop = _PROP.search(query)
    if prop:
        out["property"] = query.replace(f".{prop.group(1)}", f".{prop.group(1)}_x", 1)
    if _ARROW_R.search(query):
        out["direction"] = _ARROW_R.sub(lambda m: f"<-{m.group(1)}-", query, count=1)
    elif _ARROW_L.search(query):
        out["direction"] = _ARROW_L.sub(lambda m: f"-{m.group(1)}->", query, count=1)
    return out


# ---- running one arm --------------------------------------------------


def _classify(ran: bool, rows, baseline) -> str:
    if not ran:
        return "rejected"
    if not rows:
        return "empty"
    if _same(rows, baseline):
        return "inert"
    return "wrong"


def _same(a, b) -> bool:
    try:
        return sorted(map(repr, a)) == sorted(map(repr, b))
    except TypeError:
        return repr(a) == repr(b)


def theorem_arm(graph: str, queries: dict[str, str], limit: int) -> list[Tally]:
    from eval.load_graph import derive_schema
    from theorem.engine.executor import execute_rows, limits
    from theorem.engine.storage import Store
    from theorem.parser import parse
    from theorem.verifier import verify

    schema = derive_schema(json.loads((DATA / f"{graph}_schema.json").read_text()))
    store = Store(OUT / f"db-full-{graph}", lock=False)
    if not store.nodes:
        sys.exit(f"store for {graph} is empty; run the benchmark loader first")
    # Reads no longer write: traffic telemetry is kept in memory and reaches
    # disk with the next snapshot (Store.touch). The harness used to disable
    # store.apply here, which meant the benchmark was measuring an engine the
    # shipped one was not.
    rng = random.Random(SEED)
    tallies = {m: Tally("theorem", m) for m in MUTATIONS}

    def run(q):
        with limits(seconds=120, max_rows=10**9):
            return execute_rows(verify(parse(q), schema), store, schema)

    for n, (qid, query) in enumerate(queries.items()):
        if n >= limit:
            break
        try:
            baseline = run(query)
        except Exception:
            continue  # only mutate queries that work
        for kind, mutant in _theorem_mutants(query, schema, rng).items():
            if mutant.strip() == query.strip():
                tallies[kind].skipped += 1
                continue
            try:
                rows = run(mutant)
                ran = True
            except Exception:
                rows, ran = [], False
            tallies[kind].record(
                _classify(ran, rows, baseline),
                {"qid": qid, "query": query, "mutant": mutant},
            )
    store.close()
    return list(tallies.values())


def cypher_arm(graph: str, questions: list[dict], limit: int) -> list[Tally]:
    from neo4j import Query

    from eval.run_cypher_public import (
        EXEC_TIMEOUT_S,
        HOST_LOADED,
        connect,
        load_from_host,
        start_graph,
        stop_container,
    )

    host_load = graph in HOST_LOADED
    start_graph(graph, host_load=host_load)
    driver = connect(expect_empty=host_load)
    if host_load:
        load_from_host(driver, graph)
    tallies = {m: Tally("text2cypher", m) for m in MUTATIONS}
    try:
        with driver.session() as s:

            def run(q):
                result = s.run(Query(q, timeout=EXEC_TIMEOUT_S))
                rows = result.data()
                notes = result.consume().notifications or []
                return rows, bool(notes)

            for n, q in enumerate(questions):
                if n >= limit:
                    break
                gold = q["gold_cypher"]
                try:
                    baseline, _ = run(gold)
                except Exception:
                    continue
                for kind, mutant in _cypher_mutants(gold).items():
                    if mutant.strip() == gold.strip():
                        tallies[kind].skipped += 1
                        continue
                    try:
                        rows, warned = run(mutant)
                        ran = True
                    except Exception:
                        rows, ran, warned = [], False, False
                    tallies[kind].record(
                        _classify(ran, rows, baseline),
                        {"qid": q["qid"], "query": gold, "mutant": mutant},
                        warned=warned,
                    )
    finally:
        driver.close()
        stop_container()
    return list(tallies.values())


def correct_theorem_queries(
    graph: str, queries_path: Path | None, exec_path: Path | None
) -> dict[str, str]:
    """The generated queries for this graph that scored exactly right.

    Mutating a query that was already wrong measures nothing: the point
    is what a *correct* query does once one token is broken, which is the
    same footing the Cypher arm gets by mutating the gold query.
    """
    from eval.run_public import load_queries

    queries = (
        json.loads(queries_path.read_text())
        if queries_path
        else load_queries("claude-haiku-4-5-20251001")
    )
    exec_path = exec_path or _newest_exec(graph)
    correct = None
    if exec_path and exec_path.exists():
        correct = {
            r["qid"] for r in json.loads(exec_path.read_text()) if r.get("ex") == 1.0
        }
        print(f"[{graph}] {len(correct)} queries scored right in {exec_path.name}")
    qids = {q["qid"] for q in questions_for(graph)}
    return {
        qid: text
        for qid, text in queries.items()
        if qid in qids and (correct is None or qid in correct)
    }


def _newest_exec(graph: str) -> Path | None:
    model = "claude-haiku-4-5-20251001"
    current = PUB / f"exec-{model}-{graph}.json"
    if current.exists():
        return current
    archives = sorted(OUT.glob(f"public-archive-*/exec-{model}-{graph}.json"))
    return archives[-1] if archives else None


# ---- reporting --------------------------------------------------------


def render(tallies: list[Tally]) -> str:
    by_arm: dict[str, list[Tally]] = {}
    for t in tallies:
        by_arm.setdefault(t.arm, []).append(t)
    out = [
        "| arm | mutation | mutants | rejected | empty | wrong | warned | undetectable |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, ts in by_arm.items():
        total = Tally(arm, "all")
        for t in sorted(ts, key=lambda t: t.mutation):
            for f in ("rejected", "empty", "wrong", "inert", "skipped", "warned"):
                setattr(total, f, getattr(total, f) + getattr(t, f))
            out.append(_row(t))
        out.append(_row(total, bold=True))
    return "\n".join(out)


def _row(t: Tally, bold: bool = False) -> str:
    n = t.counted
    bad = t.empty + t.wrong
    pct = f"{100 * bad / n:.1f}%" if n else "-"
    name = f"**{t.mutation}**" if bold else t.mutation
    arm = f"**{t.arm}**" if bold else t.arm
    return (
        f"| {arm} | {name} | {n} | {t.rejected} | {t.empty} | {t.wrong} "
        f"| {t.warned} | {pct} |"
    )


# ---- the published page ----------------------------------------------

DOC = Path(__file__).resolve().parents[1] / "docs" / "benchmarks" / "silent-failure.md"


def write_doc(graphs: list[str]) -> Path:
    """Regenerate docs/benchmarks/silent-failure.md from the run JSONs."""
    per_graph = {}
    for graph in graphs:
        path = PUB / f"silent-{graph}.json"
        if path.exists():
            per_graph[graph] = json.loads(path.read_text())
    if not per_graph:
        sys.exit("no silent-*.json results to report on")

    lines = [
        "# When a query is wrong, does anyone find out?",
        "",
        "Execution accuracy counts the queries a model gets right. It says",
        "nothing about the ones it gets wrong, and that is where the two",
        "languages differ most. A Cypher query naming a label that does not",
        "exist is legal Cypher: it matches nothing and returns an empty",
        "result, which is exactly what a question whose true answer is empty",
        "returns. theorem verifies the whole query against the live schema",
        "before running any of it, so the same mistake is refused.",
        "",
        "## Method",
        "",
        "Start from a query known to be correct, break one token in a way",
        "models actually break queries, run it, and record what the caller",
        "sees. Each arm's own correct query is mutated: theorem's are the",
        "generated queries that scored exactly right, Cypher's are",
        "CypherBench's gold queries. Four mutations, each applied at most",
        "once per query:",
        "",
        "| mutation | theorem | Cypher |",
        "|---|---|---|",
        "| class | `find player` becomes `find players` | `:Player` becomes `:Players` |",
        "| edge | `playsFor` becomes `playsFors` | `[:playsFor]` becomes `[:playsFors]` |",
        "| property | `where name =` becomes `where name_x =` | `.name` becomes `.name_x` |",
        "| direction | the arrival role is swapped for the other role | the arrow is reversed |",
        "",
        "Outcomes:",
        "",
        "- **rejected** &mdash; an error instead of an answer. The caller knows.",
        "- **empty** &mdash; ran, returned nothing. Indistinguishable from a true empty answer.",
        "- **wrong** &mdash; ran, returned rows that are not the right rows.",
        "- **inert** &mdash; the mutation did not change the answer; not counted.",
        "",
        "`empty` and `wrong` together are **undetectable**: the caller gets a",
        "result and has no signal that it is not the answer.",
        "",
    ]

    for graph, tallies in per_graph.items():
        lines += [f"## {graph}", "", *_table(tallies), ""]

    total = {}
    for tallies in per_graph.values():
        for t in tallies:
            acc = total.setdefault(
                t["arm"],
                dict.fromkeys(
                    ("rejected", "empty", "wrong", "inert", "skipped", "warned"), 0
                ),
            )
            for k in acc:
                acc[k] += t[k]
    lines += [
        "## Both graphs",
        "",
        "| arm | mutants | rejected | undetectable |",
        "|---|---:|---:|---:|",
    ]
    for arm, acc in total.items():
        n = acc["rejected"] + acc["empty"] + acc["wrong"]
        bad = acc["empty"] + acc["wrong"]
        lines.append(f"| {arm} | {n} | {acc['rejected']} | {100 * bad / n:.1f}% |")

    lines += [
        "",
        "## What this does and does not show",
        "",
        "**The one case theorem does not catch is direction, and only when",
        "both of an edge's roles hold the same class.** `hasFather(subj:",
        "person, obj: person)` is type-correct whichever role you arrive at,",
        "so swapping them is a different question rather than an invalid one,",
        "and no schema check can tell. `nba` has no same-class edge and",
        "theorem catches everything on it; `fictional_character` has five, and",
        "half the direction mutants there survive. Cypher has the same blind",
        "spot and reports none of the other three either.",
        "",
        "**Neo4j does notify the driver.** A missing label, relationship type",
        "or property raises a `01N42` notification alongside a successful",
        "result. It is a warning on a call that succeeded, not an error, and",
        "it never fires on a reversed arrow. The `warned` column counts them",
        "so the comparison is not accused of hiding one. Every published",
        "text2cypher pipeline, including CypherBench's own harness, reads the",
        "rows and not the notifications.",
        "",
        "**A mutation is not a model.** This measures what a language does",
        "with a broken query, not how often a model breaks one. How often is",
        "the execution-accuracy benchmark, which is a separate page.",
        "",
        f"Reproduce: `uv run python -m eval.run_silent --graph {next(iter(per_graph))}`.",
        "",
    ]
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text("\n".join(lines) + "\n")
    return DOC


def _table(tallies: list[dict]) -> list[str]:
    out = [
        "| arm | mutation | mutants | rejected | empty | wrong | warned | undetectable |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    by_arm: dict[str, list[dict]] = {}
    for t in tallies:
        by_arm.setdefault(t["arm"], []).append(t)
    for arm, ts in by_arm.items():
        acc = dict.fromkeys(("rejected", "empty", "wrong", "warned"), 0)
        for t in sorted(ts, key=lambda t: t["mutation"]):
            for k in acc:
                acc[k] += t[k]
            out.append(_doc_row(arm, t["mutation"], t))
        out.append(_doc_row(f"**{arm}**", "**all**", acc))
    return out


def _doc_row(arm: str, mutation: str, t: dict) -> str:
    n = t["rejected"] + t["empty"] + t["wrong"]
    bad = t["empty"] + t["wrong"]
    pct = f"{100 * bad / n:.1f}%" if n else "-"
    return (
        f"| {arm} | {mutation} | {n} | {t['rejected']} | {t['empty']} "
        f"| {t['wrong']} | {t['warned']} | {pct} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="nba")
    ap.add_argument(
        "--report",
        nargs="*",
        metavar="GRAPH",
        help="regenerate the published page from existing results and exit",
    )
    ap.add_argument("--arm", choices=["theorem", "cypher", "both"], default="both")
    ap.add_argument("--limit", type=int, default=200, help="questions per arm")
    ap.add_argument("--queries", type=Path, help="a frozen queries JSON to mutate")
    ap.add_argument(
        "--exec-file",
        dest="exec_file",
        type=Path,
        help="the scored run that says which of those queries were right",
    )
    args = ap.parse_args()
    if args.report is not None:
        print(f"wrote {write_doc(args.report or ['nba', 'fictional_character'])}")
        return 0

    questions = questions_for(args.graph)
    tallies: list[Tally] = []
    if args.arm in ("theorem", "both"):
        queries = correct_theorem_queries(args.graph, args.queries, args.exec_file)
        if not queries:
            sys.exit(
                "no scored theorem queries found for this graph. Pass --queries "
                "and --exec, or run the public benchmark first."
            )
        print(f"[{args.graph}] mutating {len(queries)} correct theorem queries")
        tallies += theorem_arm(args.graph, queries, args.limit)
    if args.arm in ("cypher", "both"):
        tallies += cypher_arm(args.graph, questions, args.limit)

    report = render(tallies)
    print(report)
    out = PUB / f"silent-{args.graph}.json"
    out.write_text(
        json.dumps(
            [
                {k: v for k, v in t.__dict__.items() if k != "examples"}
                | {"examples": t.examples}
                for t in tallies
            ],
            indent=1,
        )
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
